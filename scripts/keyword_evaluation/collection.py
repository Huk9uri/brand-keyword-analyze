from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from .contracts import PROFILE, searchad_key, aware_time
from .sources import select_rank, freshness
from .volume import parse_volume, validate_period


def utc_snapshot_time():
    """datetime2(0)의 반올림으로 저장 시각이 실제 시각보다 미래가 되지 않게 한다."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def collect_volumes(keywords, fetch, period, *, clock=lambda: datetime.now(timezone.utc)):
    validate_period(period)
    unique = list(dict.fromkeys(searchad_key(k) for k in keywords))
    observations = []
    for start in range(0, len(unique), 5):
        chunk = unique[start:start+5]
        try:
            payload = fetch(chunk)
            rows = [parse_volume(k, payload) for k in chunk]
        except Exception as exc:
            if type(exc).__name__ == 'SearchAdAuthError':
                raise RuntimeError('검색광고 인증 실패: 수집 중단') from None
            rows = [parse_volume(k, {}) for k in chunk]
            for row in rows:
                row.update(observation_status='FAILED', failure_code='SEARCHAD_REQUEST_FAILED')
        for row in rows:
            row.update(fetched_at=clock().isoformat(), **period)
            observations.append(row)
    return observations


def build_rank_tasks(evaluated):
    from .shared_rank import build_rank_plan
    return build_rank_plan(evaluated)[0]


def _reusable_rank(evaluated, queued, target):
    data = evaluated['input_manifest']
    as_of = aware_time(data['as_of_at'])
    from .store_location import rank_profile
    rank = select_rank(data['ranks'], target, queued['query'], as_of, data.get('rank_links', []), rank_profile(data))
    if not rank or rank['collect_status'] != 'SUCCESS' or not freshness(rank, as_of, 'collected_at', evaluated['rules']['ttl_days']):
        return False
    cards = rank['results']
    organic = [c for c in cards if not c['is_ad']]
    return (bool(organic) and [c['raw_position'] for c in cards] == list(range(1,len(cards)+1))
            and [c['organic_rank'] for c in organic] == list(range(1,len(organic)+1))
            and len({c['place_id'] for c in organic}) == len(organic)
            and not any(c['is_ad'] and c['organic_rank'] is not None for c in cards)
            and (len(organic) >= 20 or rank['result_end_reached']))


def collect_ranks(evaluated, connection, config, artifact_root):
    from .contracts import STORE_PROFILE, LIST_PROFILE
    from .store_location import rank_profile
    profile = rank_profile(evaluated['input_manifest'])
    if profile != LIST_PROFILE:
        raise ValueError('MOBILE_STORE_LOCATION_ORGANIC20_V3 등 과거 입력 대신 매장 좌표와 MOBILE_PLACE_LIST_STORE_LOCATION_ORGANIC20_V4를 지정하세요')
    from scripts.keyword_discovery_rank.browser import BrowserFactory
    from scripts.keyword_discovery_rank.collector import KeywordDiscoveryCollector
    from scripts.keyword_discovery_rank.matching import OwnStore, OwnStoreMatcher
    from scripts.keyword_discovery_rank.parser import DomResultParser
    from scripts.keyword_discovery_rank.validation import ResultValidator
    from scripts.keyword_discovery_rank.repository import SnapshotRepository
    repository = SnapshotRepository(connection)
    repository.preflight()
    targets = evaluated['input_manifest']['targets']
    own = [OwnStore(t['target_store_id'], t['store_name'], t['place_id']) for t in targets]
    collector = KeywordDiscoveryCollector(
        BrowserFactory(headless=config.headless, timeout_seconds=config.timeout_seconds, result_limit=20,
                       organic_limit=True),
        DomResultParser(), ResultValidator(organic_limit=True), OwnStoreMatcher(own), repository,
        artifact_root=artifact_root, result_limit=20,
        request_interval_seconds=15, retry_backoff_seconds=60,
        clock=utc_snapshot_time)
    run_id = str(uuid4())
    from .shared_rank import build_rank_plan
    tasks, observations = build_rank_plan(evaluated)
    summary = collector.run(tasks, run_id)
    return dict(run_id=run_id, profile=profile, source_timezone='+00:00',
                result_limit_basis='ORGANIC', requested_organic_limit=20,
                time_offset='+00:00', shared_observations=observations,
                store_locations={t['target_store_id']: t['search_location'] for t in targets},
                processed=summary.processed_tasks, aborted=summary.aborted, abort_reason=summary.abort_reason,
                persistence_failures=summary.persistence_failures,
                statuses={k.value: v for k,v in summary.status_counts.items()},
                metrics=asdict(summary.metrics) if summary.metrics is not None else {})


def collect_keywords(evaluated, connection, config, artifact_root):
    from scripts.place_keyword_collector.browser import BrowserFactory
    from scripts.place_keyword_collector.collector import PlaceKeywordCollector
    from scripts.place_keyword_collector.parser import KeywordListParser
    from scripts.place_keyword_collector.repository import PlaceKeywordRepository
    from scripts.place_keyword_collector.models import RankPlaceTarget, RefreshPolicy
    repository = PlaceKeywordRepository(connection)
    repository.preflight()
    pending = {}
    for result in evaluated['results']:
        rank_run = next((e['source_refs']['run_id'] for e in result['evidence'] if e['evidence_type'] == 'RANK'), None)
        for e in result['evidence']:
            if e['evidence_type'] == 'KEYWORDLIST' and e['decision'].get('error') and rank_run:
                pending.setdefault(e['source_refs']['place_id'], rank_run)
    summaries = []
    for rank_run in sorted(set(pending.values())):
        collector = PlaceKeywordCollector(
            BrowserFactory(headless=config.headless, timeout_seconds=config.timeout_seconds),
            KeywordListParser(), repository, artifact_root=artifact_root,
            clock=utc_snapshot_time)
        run_id = str(uuid4())
        summary = collector.run([RankPlaceTarget(p, p) for p, rr in sorted(pending.items()) if rr == rank_run],
                                run_id, rank_run, RefreshPolicy.WEEKLY, force_refresh=True)
        summaries.append(dict(run_id=run_id, rank_run_id=rank_run, source_timezone='+00:00',
                              success=summary.success_count, empty=summary.empty_count, failed=summary.failed_count))
    return summaries
