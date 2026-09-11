from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import json
import re

from .contracts import aware_time, canonical, searchad_key, STORE_PROFILE, LOCATION_PROFILES
from .repository import ReadOnlySource
from .volume import parse_volume


def source_time(value, offset):
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        if not isinstance(offset, str) or not re.fullmatch(r'[+-]\d{2}:\d{2}', offset):
            raise ValueError('TIMEZONE_UNVERIFIED')
        return aware_time(parsed.isoformat()+offset).isoformat()
    return aware_time(parsed).isoformat()


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k,v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def export_bundle(connection, config):
    source = ReadOnlySource(connection)
    result = deepcopy(config['bundle'])
    result.update(candidates=[], reviews=[], volumes=[], ranks=[], rank_links=[], keyword_snapshots=[])
    result['source_timezones'] = {k: config.get(k) for k in ('candidate_time_offset','keyword_time_offset','keyword_run_time_offsets','rank_runs')}
    # 영수증의 좌표 원본은 targets와 실제 스냅샷에서 검증한다. 시간대 메타데이터에는 중복하지 않는다.
    result['source_timezones']['rank_runs'] = [
        {k: spec[k] for k in ('run_id', 'profile', 'time_offset', 'shared_observations') if k in spec}
        for spec in config['rank_runs']]
    for target in result['targets']:
        place = target['place_id']
        run_id = result['candidate_runs'][place]
        candidates = source.candidates(run_id, place)
        if not candidates:
            raise ValueError('CANDIDATE_RUN_EMPTY')
        if target.get('expected_candidate_count') is not None and len(candidates) != target['expected_candidate_count']:
            raise ValueError('CANDIDATE_COUNT_MISMATCH')
        for row in candidates:
            row['run_id'] = str(row['run_id']).lower()
            if 'generated_at' in row:
                row['generated_at'] = source_time(row['generated_at'], config.get('candidate_time_offset'))
        result['candidates'].extend(candidates)
        for row in source.reviews(run_id, place):
            row['run_id'] = str(row['run_id']).lower()
            row['analyzed_at'] = source_time(row['analyzed_at'], config.get('candidate_time_offset'))
            # 원문 상태와 추출 결과를 실제 판매·서비스 확정으로 승격하지 않는다.
            row.update(verified_support=False, verification_evidence=None, support_kind=None)
            result['reviews'].append(row)
        identity = source.query('''SELECT BRAND_CODE,STORE_CODE,NAVER_PLACE_ID,PLACE_ID_STATUS
            FROM dbo.vw_naver_store_hours_targets WHERE NAVER_PLACE_ID=%s''', (place,))
        consistent = [r for r in identity if r['PLACE_ID_STATUS'] == 'CONSISTENT' and r['BRAND_CODE'] == '001']
        if len(consistent) != 1 or target['brand_code'] != '1':
            target['operation_status'] = 'CONFLICT'
        target['identity_observation'] = identity
        # 뷰가 일치해도 target_store_id의 별도 매핑 증거가 없으면 기존 UNKNOWN을 유지한다.
        if (len(consistent) == 1 and target['brand_code'] == '1' and target.get('identity_evidence')
                and target.get('operation_status') != 'CONFLICT'):
            target['operation_status'] = 'VERIFIED'
    for key in sorted({searchad_key(c['normalized_keyword']) for c in result['candidates']}):
        for row in source.volumes(key):
            payload = json.loads(row['response_json']) if row.get('response_json') else {}
            parsed = parse_volume(row['request_keyword'], payload)
            row.update(pc_interval=parsed['pc_interval'], mobile_interval=parsed['mobile_interval'],
                       total_interval=parsed['total_interval'], raw_pc=parsed['raw_pc'], raw_mobile=parsed['raw_mobile'],
                       response_json=payload,
                       period_verified=row['period_definition'] in config.get('verified_volume_periods', []),
                       fetched_at=source_time(row['fetched_at'], None))
            result['volumes'].append(row)
    for spec in config['rank_runs']:
        rows = source.ranks(spec['run_id'])
        for row in rows:
            latitude, longitude = row.pop('latitude', None), row.pop('longitude', None)
            location_name = row.pop('location_name', None)
            row.update(profile=spec['profile'], collected_at=source_time(row['collected_at'], spec.get('time_offset')),
                       run_id=str(row['run_id']).lower())
            if spec['profile'] in LOCATION_PROFILES:
                target = next((t for t in result['targets'] if t['target_store_id'] == row['target_store_id']), None)
                if target is None or location_name != spec['profile'] or latitude is None or longitude is None:
                    raise ValueError('SEARCH_LOCATION_SNAPSHOT_MISMATCH')
                row['search_location'] = dict(latitude=float(latitude), longitude=float(longitude),
                    place_id=target['place_id'], source='naver_keyword_discovery_snapshot', verified_at=row['collected_at'])
            result['ranks'].append(row)
        from .shared_rank import attach_shared_links
        attach_shared_links(result, spec, rows)
    places = {r['place_id'] for s in result['ranks'] for r in s['results'] if not r['is_ad']}
    for place in sorted(places):
        for row in source.keywords(place):
            run_id = str(row.get('run_id', '')).lower()
            row['run_id'] = run_id
            offsets = {k.lower(): v for k,v in config.get('keyword_run_time_offsets', {}).items()}
            row['checked_at'] = source_time(row['checked_at'], offsets.get(run_id, config.get('keyword_time_offset')))
            result['keyword_snapshots'].append(row)
    return _plain(result)
