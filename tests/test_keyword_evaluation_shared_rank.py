from copy import deepcopy

import pytest

from scripts.keyword_evaluation.collection import build_rank_tasks
from scripts.keyword_evaluation.pipeline import evaluate_bundle
from test_keyword_evaluation_engine import bundle


def five_stores():
    data = bundle()
    target = deepcopy(data['targets'][0])
    candidates = deepcopy(data['candidates'])
    for i in range(1, 5):
        place = str(100 + i)
        data['targets'].append(dict(target, place_id=place, target_store_id=f'OTHER-{i}'))
        data['candidate_runs'][place] = data['candidate_runs']['100']
        data['candidates'].extend(dict(c, candidate_id=c['candidate_id']+i*5, place_id=place) for c in candidates)
    data['ranks'] = []
    return data


def test_five_stores_collect_each_menu_once():
    evaluated = evaluate_bundle(five_stores())
    assert len(evaluated['collection_queue']) == 25
    tasks = build_rank_tasks(evaluated)
    assert len(tasks) == 5
    assert len({t.query for t in tasks}) == 5


def test_shared_snapshot_reaches_all_five_stores_and_rejects_bad_link():
    from scripts.keyword_evaluation.shared_rank import build_rank_plan, attach_shared_links
    data = five_stores()
    tasks, observations = build_rank_plan(evaluate_bundle(data))
    original = bundle()['ranks'][0]
    observation = next(o for o in observations if o['normalized_query'] == original['normalized_query'])
    rank = dict(original, target_store_id=observation['source_target_store_id'], task_key=observation['task_key'])
    data['ranks'] = [rank]
    spec = dict(run_id=rank['run_id'], profile=rank['profile'], shared_observations=[observation])
    attach_shared_links(data, spec, [rank])
    evaluated = evaluate_bundle(data)
    rows = [r for r in evaluated['results'] if r['normalized_keyword'] == rank['normalized_query']]
    assert len(rows) == 5
    assert {r['rank_snapshot_id'] for r in rows} == {rank['snapshot_id']}
    assert len(build_rank_tasks(evaluated)) == 4
    broken = deepcopy(data)
    broken['rank_links'][0]['run_id'] = 'wrong-run'
    with pytest.raises(ValueError, match='SHARED_RANK'):
        evaluate_bundle(broken)


def test_partial_shared_snapshot_stays_review_required_and_is_recollected():
    from scripts.keyword_evaluation.shared_rank import build_rank_plan, attach_shared_links
    data = five_stores()
    _, observations = build_rank_plan(evaluate_bundle(data))
    rank = bundle()['ranks'][0]
    observation = next(o for o in observations if o['normalized_query'] == rank['normalized_query'])
    rank.update(target_store_id=observation['source_target_store_id'], task_key=observation['task_key'], collect_status='PARTIAL')
    data['ranks'] = [rank]
    attach_shared_links(data, dict(run_id=rank['run_id'], profile=rank['profile'], shared_observations=[observation]), [rank])
    result = evaluate_bundle(data)
    assert len(build_rank_tasks(result)) == 5
    assert all('RANK_PARTIAL' in r['reason_codes'] for r in result['results'] if r['normalized_keyword'] == rank['normalized_query'])


@pytest.mark.parametrize(('field', 'value'), [('run_id', 'other'), ('device_type', 'PC'),
    ('target_store_id', 'other'), ('normalized_query', 'other'), ('profile', 'old')])
def test_export_rejects_wrong_observation_identity(field, value):
    from scripts.keyword_evaluation.shared_rank import build_rank_plan, attach_shared_links
    data = five_stores()
    _, observations = build_rank_plan(evaluate_bundle(data))
    rank = bundle()['ranks'][0]
    observation = next(o for o in observations if o['normalized_query'] == rank['normalized_query'])
    rank.update(target_store_id=observation['source_target_store_id'], task_key=observation['task_key'])
    spec = dict(run_id=rank['run_id'], profile=rank['profile'], shared_observations=[observation])
    rank[field] = value
    data['ranks'] = [rank]
    with pytest.raises(ValueError, match='SHARED_RANK'):
        attach_shared_links(data, spec, [rank])


def test_export_builds_shared_links_from_receipt(monkeypatch):
    from scripts.keyword_evaluation.shared_rank import build_rank_plan
    from scripts.keyword_evaluation.source_export import export_bundle
    data = five_stores()
    _, observations = build_rank_plan(evaluate_bundle(data))
    rank = bundle()['ranks'][0]
    observation = next(o for o in observations if o['normalized_query'] == rank['normalized_query'])
    rank.update(target_store_id=observation['source_target_store_id'], task_key=observation['task_key'])

    class Source:
        def __init__(self, connection): pass
        def candidates(self, run, place): return [c for c in data['candidates'] if c['place_id']==place]
        def reviews(self, run, place): return []
        def volumes(self, key): return []
        def ranks(self, run): return [deepcopy(rank)]
        def keywords(self, place): return []
        def query(self, sql, params): return []

    monkeypatch.setattr('scripts.keyword_evaluation.source_export.ReadOnlySource', Source)
    spec = dict(run_id=rank['run_id'], profile=rank['profile'], time_offset='+00:00', shared_observations=[observation])
    exported = export_bundle(None, dict(bundle=data, rank_runs=[spec]))
    assert len(exported['ranks']) == 1
    assert len(exported['rank_links']) == 5
    assert {link['target_place_id'] for link in exported['rank_links']} == {'100','101','102','103','104'}


def test_new_shared_failure_overrides_prior_success_for_every_store():
    from scripts.keyword_evaluation.shared_rank import build_rank_plan, attach_shared_links
    data = five_stores()
    _, observations = build_rank_plan(evaluate_bundle(data))
    rank = bundle()['ranks'][0]
    observation = next(o for o in observations if o['normalized_query'] == rank['normalized_query'])
    rank.update(target_store_id=observation['source_target_store_id'], task_key=observation['task_key'])
    failed = dict(rank, snapshot_id=999, collected_at='2026-09-09T00:30:00Z', collect_status='LOAD_TIMEOUT', results=[])
    data['ranks'] = [rank, failed]
    attach_shared_links(data, dict(run_id=rank['run_id'], profile=rank['profile'], shared_observations=[observation]), data['ranks'])
    evaluated = evaluate_bundle(data)
    rows = [r for r in evaluated['results'] if r['normalized_keyword'] == rank['normalized_query']]
    assert {r['rank_snapshot_id'] for r in rows} == {999}
    assert all('RANK_FAILED' in r['reason_codes'] for r in rows)

