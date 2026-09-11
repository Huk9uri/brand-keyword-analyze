from datetime import datetime, timezone

import pytest

from scripts.keyword_evaluation.contracts import keyword_key, searchad_key, aware_time, percentile
from scripts.keyword_evaluation.volume import parse_volume


def test_normalizations_do_not_merge_rank_queries():
    assert keyword_key(' Ａ  설렁탕 ') == 'a 설렁탕'
    assert keyword_key('왕 갈비탕') != keyword_key('왕갈비탕')
    assert searchad_key('왕 갈비탕') == searchad_key('왕갈비탕')


def test_naive_time_is_rejected_without_source_timezone():
    with pytest.raises(ValueError, match='TIMEZONE'):
        aware_time('2026-09-09T10:00:00')
    assert aware_time('2026-09-09T10:00:00+09:00').hour == 1


@pytest.mark.parametrize('raw,status,count,interval', [
    (0, 'EXACT', 0, [0, 0]), (10, 'EXACT', 10, [10, 10]),
    ('< 10', 'CENSORED', None, [0, 9]), ('10', 'INVALID', None, None),
    (True, 'INVALID', None, None), (-1, 'INVALID', None, None),
])
def test_volume_preserves_censoring(raw, status, count, interval):
    value = parse_volume('설렁탕', {'keywordList': [
        {'relKeyword': '설렁탕', 'monthlyPcQcCnt': 10, 'monthlyMobileQcCnt': raw}
    ]})
    assert value['observation_status'] == status
    assert value['mobile_count'] == count
    assert value['mobile_interval'] == interval
    assert value['raw_mobile'] == raw


def test_not_provided_is_not_transport_failure():
    assert parse_volume('설렁탕', {'keywordList': []})['observation_status'] == 'NOT_PROVIDED'
    assert parse_volume('설렁탕', {})['observation_status'] == 'INVALID'


def test_conflicting_duplicate_response_not_last_write_wins():
    rows = [{'relKeyword': '설렁탕', 'monthlyPcQcCnt': x, 'monthlyMobileQcCnt': 20} for x in (1, 2)]
    assert parse_volume('설렁탕', {'keywordList': rows})['failure_code'] == 'DUPLICATE_RESPONSE_CONFLICT'


def test_percentile_midrank_and_uninformative_population():
    assert percentile(10, [10, 10, 20, 30, 40]) == .2
    assert percentile(10, [10] * 5) is None
    assert percentile(10, [10, 20]) is None
