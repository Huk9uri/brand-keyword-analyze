import csv
import json

import pytest

from scripts.keyword_evaluation.cli import main
from scripts.keyword_evaluation.collection import build_rank_tasks, collect_volumes
from scripts.keyword_evaluation.pipeline import evaluate_bundle
from test_keyword_evaluation_engine import bundle


def test_evaluate_defaults_to_offline_and_exports_review(tmp_path):
    source = tmp_path/'input.json'
    source.write_text(json.dumps(bundle(), ensure_ascii=False), encoding='utf-8')
    target = tmp_path/'output'
    assert main(['evaluate', '--input', str(source), '--output', str(target)]) == 0
    result = json.loads((target/'evaluation.json').read_text(encoding='utf-8'))
    assert result['results'][0]['final_class'] == 'VACANT'
    rows = list(csv.DictReader((target/'review.csv').open(encoding='utf-8-sig')))
    assert len(rows) == 5 and rows[0]['사람_시장유형'] == ''
    assert '자동분류' not in rows[0]


def test_existing_output_is_not_overwritten(tmp_path):
    source = tmp_path/'input.json'
    source.write_text(json.dumps(bundle()), encoding='utf-8')
    out = tmp_path/'out'
    out.mkdir()
    (out/'evaluation.json').write_text('original', encoding='utf-8')
    assert main(['evaluate', '--input', str(source), '--output', str(out)]) == 2
    assert (out/'evaluation.json').read_text() == 'original'


def test_write_requires_explicit_switch_before_connecting(tmp_path):
    assert main(['save', '--input', str(tmp_path/'missing.json')]) == 2


def test_rank_tasks_have_no_coordinates_or_location_resolution():
    data = bundle()
    tasks = build_rank_tasks(evaluate_bundle(data))
    assert len(tasks) == 4
    assert all(t.latitude is None and t.longitude is None for t in tasks)
    assert {t.source_id for t in tasks} == {'2','3','4','5'}


def test_short_rank_with_own_store_still_requires_collection_to_twenty():
    data = bundle()
    data['ranks'][0]['result_end_reached'] = False
    tasks = build_rank_tasks(evaluate_bundle(data))
    assert '1' in {t.source_id for t in tasks}


def test_volume_collection_deduplicates_stores_and_preserves_failures():
    calls = []
    def fetch(words):
        calls.append(words)
        return {'keywordList': [{'relKeyword': w, 'monthlyPcQcCnt': 10, 'monthlyMobileQcCnt': '<10'} for w in words]}
    observations = collect_volumes(['왕 갈비탕', '왕갈비탕'], fetch, {'period_type': 'UNVERIFIED', 'period_definition': ''})
    assert len(calls) == 1 and len(observations) == 1
    assert observations[0]['observation_status'] == 'CENSORED'
    def failing(_):
        raise RuntimeError('secret should not appear')
    failed = collect_volumes(['설렁탕'], failing, {'period_type': 'UNVERIFIED', 'period_definition': ''})
    assert failed[0]['observation_status'] == 'FAILED'
    assert 'secret' not in str(failed)


def test_period_metadata_cannot_override_observations():
    with pytest.raises(ValueError, match='PERIOD'):
        collect_volumes(['설렁탕'], lambda _: {'keywordList': []},
                        {'period_type':'UNVERIFIED', 'period_definition':'', 'total_count':1000})
