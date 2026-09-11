from copy import deepcopy
from datetime import date
import json

import pytest

from scripts.brand_keyword_research.core import validate_config, period, analyze, report
from scripts.brand_keyword_research.cli import execute, replay


def config():
    return {'version': 1, 'brand': 'hanchon', 'ttl_days': 7,
            'volume_period': {'period_type': 'PROVIDER_MONTHLY', 'period_definition': '최근 한 달',
                              'period_start': None, 'period_end': None, 'period_verified': True},
            'candidates': [{'id': 'soup', 'query': '황태탕', 'pos_menu_names': ['사골황태탕'],
                            'evidence': 'POS 관측', 'condition': '현재 판매 확인 필요'}],
            'targets': [{'place_id': '1', 'target_store_id': 'EVAL-1', 'store_name': '시험점',
                         'search_location': {'latitude': 37.5, 'longitude': 127.0, 'place_id': '1',
                                             'source': '확인 자료', 'verified_at': '2026-09-01T00:00:00+00:00'}}]}


def state():
    return {'config': config(), 'as_of_at': '2026-09-11T00:00:00+00:00', 'own_place_ids': ['1'],
            'sales': {'start': '2026-08-01', 'end': '2026-09-01', 'latest_date': '2026-09-10',
                      'total_amount': '100', 'warnings': [], 'rows': []}, 'volumes': [], 'ranks': []}


def rank(status='SUCCESS', count=20):
    from scripts.keyword_evaluation.contracts import LIST_PROFILE
    return {'snapshot_id': 1, 'run_id': 'run', 'normalized_query': '황태탕',
            'target_store_id': 'EVAL-1', 'device_type': 'MOBILE', 'profile': LIST_PROFILE,
            'collected_at': '2026-09-10T00:00:00+00:00', 'collect_status': status,
            'search_location': config()['targets'][0]['search_location'], 'result_end_reached': False,
            'results': [{'place_id': str(i+2), 'place_name': '타사', 'category': '식당',
                         'raw_position': i+1, 'organic_rank': i+1, 'is_ad': False} for i in range(count)]}


def test_period_uses_latest_complete_month_and_rejects_future():
    assert period('2026-09-10', date(2026, 9, 11)) == ('2026-08-01', '2026-09-01')
    assert period('2026-08-31', date(2026, 9, 11)) == ('2026-08-01', '2026-09-01')
    with pytest.raises(ValueError): period('2026-09-10', date(2026, 9, 11), '2026-09-01', '2026-10-01')


@pytest.mark.parametrize('change', ['duplicate_query', 'duplicate_target', 'no_evidence', 'brand', 'ttl'])
def test_invalid_config(change):
    c = config()
    if change == 'duplicate_query': c['candidates'].append({**c['candidates'][0], 'id': 'other'})
    if change == 'duplicate_target': c['targets'].append(deepcopy(c['targets'][0]))
    if change == 'no_evidence': c['candidates'][0]['evidence'] = ''
    if change == 'brand': c['brand'] = 'unknown'
    if change == 'ttl': c['ttl_days'] = -1
    with pytest.raises(ValueError): validate_config(c)


def test_missing_sales_are_not_zero_and_missing_rank_not_nonexposure():
    r = analyze(state())['rows'][0]
    assert r['sales_amount'] is None
    assert r['visibility'] == 'UNKNOWN'
    assert r['volume_status'] == 'MISSING'


@pytest.mark.parametrize('status,count', [('PARTIAL', 3), ('SUCCESS', 3)])
def test_short_incomplete_rank_not_valid(status, count):
    s = state(); s['ranks'] = [rank(status, count)]
    r = analyze(s)['rows'][0]
    assert r['visibility'] == 'UNKNOWN'
    assert r['rank_status'] != 'VALID'


def test_latest_failed_rank_does_not_reuse_older_success():
    s = state(); good = rank(); bad = rank('PARTIAL', 2)
    bad.update(snapshot_id=2, collected_at='2026-09-11T00:00:00+00:00')
    s['ranks'] = [good, bad]
    assert analyze(s)['rows'][0]['rank_status'] == 'PARTIAL'


def test_location_mismatch_and_stale_rank():
    s = state(); s['ranks'] = [rank()]
    s['ranks'][0]['search_location'] = {**s['ranks'][0]['search_location'], 'longitude': 128.0}
    assert analyze(s)['rows'][0]['rank_status'] == 'MISSING'
    s['ranks'] = [rank()]; s['ranks'][0]['collected_at'] = '2026-08-01T00:00:00+00:00'
    assert analyze(s)['rows'][0]['rank_status'] == 'STALE'


def test_complete_empty_and_valid_nonexposure_are_distinct():
    s = state(); s['ranks'] = [rank()]
    assert analyze(s)['rows'][0]['visibility'] == 'NOT_IN_TOP20'
    s['ranks'][0]['results'] = []; s['ranks'][0]['result_end_reached'] = True
    assert analyze(s)['rows'][0]['visibility'] == 'UNKNOWN'


def test_sales_all_exact_names_required_and_no_subset_total():
    s = state(); s['config']['candidates'][0]['pos_menu_names'].append('다른메뉴')
    s['sales']['rows'] = [{'menu_name': '사골황태탕', 'amount': '10', 'mapping_names': 1}]
    r = analyze(s)['rows'][0]
    assert r['sales_amount'] is None and r['sales_status'] == 'INCOMPLETE_MAPPING'


def test_report_escapes_table_and_has_no_zero_denominator():
    s = state(); s['config']['candidates'][0]['condition'] = '확인|필요\n다음'
    text = report(s, analyze(s))
    assert '0/0' not in text
    assert '확인／필요 다음' in text


class FakeRepo:
    def __init__(self): self.collect_calls = 0
    def read(self, cfg, start, end): return state()
    def collect(self, data, folder):
        self.collect_calls += 1
        return {'aborted': True}


def test_read_only_and_replay_identical(tmp_path):
    repo = FakeRepo(); root = tmp_path/'read'
    execute(config(), root, repo)
    assert repo.collect_calls == 0
    replay(root/'input.json', tmp_path/'replay')
    assert (root/'report.md').read_bytes() == (tmp_path/'replay'/'report.md').read_bytes()
    with pytest.raises(ValueError): execute(config(), root, repo)


def test_aborted_collection_is_partial_with_report(tmp_path):
    repo = FakeRepo(); root = tmp_path/'run'
    assert execute(config(), root, repo, collect=True) == 2
    assert json.loads((root/'status.json').read_text())['status'] == 'PARTIAL'
    assert (root/'report.md').exists()


def test_failure_keeps_sanitized_status(tmp_path):
    class Broken(FakeRepo):
        def read(self, *a): raise RuntimeError('password=do-not-leak')
    root = tmp_path/'fail'
    assert execute(config(), root, Broken()) == 1
    text = (root/'status.json').read_text(encoding='utf-8')
    assert 'do-not-leak' not in text and 'FAILED' in text


def volume():
    return dict(volume_snapshot_id=1, provider='NAVER_SEARCHAD', searchad_lookup_key='황태탕',
                fetched_at='2026-09-10T00:00:00+00:00', observation_status='CENSORED',
                total_count=None, total_interval=[0, 18], period_verified=True)


def test_latest_failed_volume_not_zero_or_old_volume():
    s = state(); s['volumes'] = [volume(), {**volume(), 'volume_snapshot_id': 2,
                                         'fetched_at': s['as_of_at'], 'observation_status': 'FAILED'}]
    r = analyze(s)['rows'][0]
    assert r['volume_status'] == 'FAILED' and r['volume_total'] is None


def test_ad_does_not_become_own_organic_position():
    s = state(); r = rank()
    for c in r['results']: c['raw_position'] += 1
    r['results'].insert(0, dict(place_id='1', place_name='자사 광고', category='식당',
                                raw_position=1, organic_rank=None, is_ad=True))
    s['ranks'] = [r]
    assert analyze(s)['rows'][0]['visibility'] == 'NOT_IN_TOP20'


def test_collect_reuses_valid_rank_but_plans_partial(monkeypatch, tmp_path):
    from scripts.brand_keyword_research.repository import Repository
    from scripts.keyword_evaluation import collection
    s = state(); s['volumes'] = [volume()]; s['ranks'] = [rank()]
    repo = Repository(None, tmp_path/'.env')
    assert repo.collect(s, tmp_path)['reused'] is True
    called = []
    monkeypatch.setattr(collection, 'collect_ranks', lambda evaluated, *args: called.append(evaluated) or {'aborted': True})
    folder = tmp_path/'partial'; folder.mkdir()
    s['ranks'] = [rank('PARTIAL', 2)]
    assert repo.collect(s, folder)['aborted'] is True
    assert len(called) == 1


def test_future_location_is_rejected():
    s = state(); s['config']['targets'][0]['search_location']['verified_at'] = '2027-01-01T00:00:00+00:00'
    with pytest.raises(ValueError): analyze(s)


def test_monthly_api_cannot_be_relabelled_exact_dates():
    c = config()
    c['volume_period'].update(period_type='EXACT_30D', period_start='2026-08-01', period_end='2026-08-30')
    with pytest.raises(ValueError): validate_config(c)


def test_repository_rank_query_uses_same_normalization_as_collector(tmp_path):
    from scripts.brand_keyword_research.repository import Repository
    c = config(); c['candidates'][0]['query'] = '  황태탕  '
    repo = Repository(None, tmp_path/'.env'); captured = []
    repo.sales = lambda *args: state()['sales']
    def query(sql, params=()):
        if 'vw_naver_store_hours_targets' in sql: return [{'NAVER_PLACE_ID': '1'}]
        if 'normalized_query' in sql: captured.append(params[1])
        return []
    repo.query = query
    repo.read(c)
    assert captured == ['황태탕']
