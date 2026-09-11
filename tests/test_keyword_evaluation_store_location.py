from copy import deepcopy

import pytest

from scripts.keyword_evaluation.collection import build_rank_tasks
from scripts.keyword_evaluation.pipeline import evaluate_bundle
from test_keyword_evaluation_shared_rank import five_stores
from test_keyword_evaluation_engine import bundle

LOCAL = 'MOBILE_STORE_LOCATION_ORGANIC20_V3'


def located_bundle():
    data = five_stores()
    data['rank_profile'] = LOCAL
    for i, target in enumerate(data['targets']):
        target['search_location'] = dict(latitude=37.4+i*.01, longitude=127.0+i*.01,
            place_id=target['place_id'], source='naver_place_location', verified_at='2026-09-08T00:00:00Z')
    return data


def test_local_search_keeps_twenty_five_tasks_with_each_store_coordinates():
    data = located_bundle()
    evaluated = evaluate_bundle(data)
    tasks = build_rank_tasks(evaluated)
    assert len(tasks) == 25
    for target in data['targets']:
        own = [t for t in tasks if t.target_store_id == target['target_store_id']]
        assert len(own) == 5
        assert all(t.latitude == target['search_location']['latitude'] and
                   t.longitude == target['search_location']['longitude'] for t in own)
        assert all(t.location_name == LOCAL for t in own)


@pytest.mark.parametrize('change', ['missing', 'partial', 'invalid', 'wrong_place', 'future'])
def test_invalid_store_location_fails_before_collection(change):
    data = located_bundle()
    location = data['targets'][0]['search_location']
    if change == 'missing': del data['targets'][0]['search_location']
    if change == 'partial': del location['longitude']
    if change == 'invalid': location['latitude'] = 0
    if change == 'wrong_place': location['place_id'] = '999'
    if change == 'future': location['verified_at'] = '2030-01-01T00:00:00Z'
    with pytest.raises(ValueError, match='SEARCH_LOCATION'):
        evaluate_bundle(data)


def test_coordinate_free_or_other_store_observation_is_not_reused():
    data = located_bundle()
    rank = deepcopy(bundle()['ranks'][0])
    data['ranks'] = [rank]
    result = evaluate_bundle(data)
    assert all(r['rank_snapshot_id'] is None for r in result['results'])
    rank.update(profile=LOCAL, search_location=deepcopy(data['targets'][0]['search_location']))
    result = evaluate_bundle(data)
    rows = [r for r in result['results'] if r['normalized_keyword'] == rank['normalized_query']]
    assert sum(r['rank_snapshot_id'] is not None for r in rows) == 1
    rank['search_location']['latitude'] += .1
    assert all(r['rank_snapshot_id'] is None for r in evaluate_bundle(data)['results'])


def test_source_export_verifies_persisted_coordinates(monkeypatch):
    from scripts.keyword_evaluation.source_export import export_bundle
    data = located_bundle()
    rank = deepcopy(bundle()['ranks'][0])
    rank.update(location_name=LOCAL, latitude=37.4, longitude=127.0)
    class Source:
        def __init__(self, conn): pass
        def candidates(self, run, place): return [c for c in data['candidates'] if c['place_id']==place]
        def reviews(self, run, place): return []
        def volumes(self, key): return []
        def ranks(self, run): return [deepcopy(rank)]
        def keywords(self, place): return []
        def query(self, sql, params): return []
    monkeypatch.setattr('scripts.keyword_evaluation.source_export.ReadOnlySource', Source)
    config = dict(bundle=data, rank_runs=[dict(run_id=rank['run_id'], profile=LOCAL, time_offset='+00:00',
                  store_locations={t['target_store_id']:t['search_location'] for t in data['targets']})])
    exported = export_bundle(None, config)
    assert exported['ranks'][0]['search_location']['latitude'] == 37.4
    assert 'latitude' not in exported['ranks'][0]
    evaluate_bundle(exported)
    rank['location_name'] = 'old'
    with pytest.raises(ValueError, match='SEARCH_LOCATION_SNAPSHOT'):
        export_bundle(None, config)


def test_live_collection_rejects_old_coordinate_free_input():
    from scripts.keyword_evaluation.collection import collect_ranks
    with pytest.raises(ValueError, match='MOBILE_STORE_LOCATION'):
        collect_ranks(evaluate_bundle(bundle()), None, None, None)
