from copy import deepcopy
from datetime import datetime, timezone

import pytest

from scripts.brand_keyword_research.core import validate_config
from test_brand_keyword_research import config


AS_OF = datetime(2026, 9, 11, tzinfo=timezone.utc)


def store(code='001', place='1', **extra):
    return dict(STORE_CODE=code, ERP_STORE_NAME='시험점 '+code,
                NAVER_STORE_NAME=None, NAVER_PLACE_ID=place, PLACE_ID_STATUS='CONSISTENT',
                latitude=37.5, longitude=127.0, verified_at=AS_OF,
                resolver_version='place-location-v1', **extra)


def test_inventory_keeps_missing_ids_and_coordinates_without_smartplace():
    from scripts.brand_keyword_research.all_stores import build_inventory
    missing = store('002', None); missing['PLACE_ID_STATUS'] = 'NEW'
    no_location = store('003', '3'); no_location['latitude'] = None
    inventory = build_inventory([store(), missing, no_location], config(), AS_OF)
    assert len(inventory) == 3
    assert [r['status'] for r in inventory] == ['ELIGIBLE', 'PLACE_ID_MISSING', 'LOCATION_MISSING']
    assert inventory[0]['target_store_id'] == 'EVAL-1'
    assert inventory[0]['search_location'] == config()['targets'][0]['search_location']


def test_duplicate_place_mapping_excludes_both_stores_and_deduplicates_join_rows():
    from scripts.brand_keyword_research.all_stores import build_inventory
    rows = [store(), store(), store('002')]
    inventory = build_inventory(rows, config(), AS_OF)
    assert len(inventory) == 2
    assert {r['status'] for r in inventory} == {'DUPLICATE_PLACE_ID'}


def test_conflicting_identity_and_future_coordinates_remain_in_inventory():
    from scripts.brand_keyword_research.all_stores import build_inventory
    conflict = store('001'); conflict['PLACE_ID_STATUS'] = 'CONFLICT'
    future = store('002', '2'); future['verified_at'] = datetime(2027, 1, 1, tzinfo=timezone.utc)
    inventory = build_inventory([conflict, future], config(), AS_OF)
    assert [r['status'] for r in inventory] == ['PLACE_ID_UNVERIFIED', 'LOCATION_INVALID']


def test_all_store_configuration_accepts_more_than_100_pairs_and_no_eligible_stores():
    c = config(); c['scope'] = 'ALL_STORES'
    c['targets'] = []
    validate_config(c)
    template = config()['targets'][0]
    for i in range(101):
        target = deepcopy(template)
        target.update(place_id=str(i), target_store_id='IYN-'+str(i))
        target['search_location']['place_id'] = str(i)
        c['targets'].append(target)
    validate_config(c)
    c.pop('scope')
    with pytest.raises(ValueError): validate_config(c)


def test_inventory_selection_records_all_stores_but_only_eligible_targets():
    from scripts.brand_keyword_research.all_stores import configure_all_stores
    rows = [store(), store('002', None)]
    resolved, inventory = configure_all_stores(config(), rows, AS_OF)
    assert resolved['scope'] == 'ALL_STORES'
    assert len(resolved['targets']) == 1
    assert len(inventory) == 2
    assert resolved['targets'][0]['store_code'] == '001'
    assert 'scope' not in config()


def test_candidate_volume_is_kept_when_no_store_can_be_observed():
    from scripts.brand_keyword_research.core import analyze, report
    from test_brand_keyword_research import state, volume
    s = state(); s['config'].update(scope='ALL_STORES', targets=[])
    s['volumes'] = [volume()]
    s['inventory'] = [dict(store_code='001', store_name='누락점', place_id=None,
                            target_store_id='IYN-001', status='PLACE_ID_MISSING', search_location=None)]
    result = analyze(s)
    assert result['rows'] == []
    assert result['candidates'][0]['volume_interval'] == [0, 18]
    text = report(s, result)
    candidate_row = next(line for line in text.splitlines() if line.startswith('| 황태탕 |'))
    assert candidate_row.split('|')[6].strip() == '1'


def test_repository_prepare_uses_complete_inventory_and_only_resolves_missing_coordinates(tmp_path):
    from scripts.brand_keyword_research.repository import Repository
    from scripts.keyword_discovery_rank.place_location import PlaceLocation, PlaceLocationError
    repo = Repository(None, tmp_path/'.env')
    missing = store('002', '2'); missing['latitude'] = None
    failed = store('003', '3'); failed['latitude'] = None
    records = [store(), missing, failed, store('004', None)]
    repo.query = lambda *args: records
    class Resolver:
        def resolve(self, place):
            if place == '3': raise PlaceLocationError('not found')
            assert place == '2'
            return PlaceLocation(place, 37.1, 127.2, AS_OF, AS_OF, 'test')
    c = config(); c['scope'] = 'ALL_STORES'
    resolved, inventory = repo.prepare(c, collect=True, root=tmp_path, resolver=Resolver())
    assert len(resolved['targets']) == 2
    assert [i['status'] for i in inventory] == ['ELIGIBLE', 'ELIGIBLE', 'LOCATION_RESOLUTION_FAILED', 'PLACE_ID_MISSING']
    assert (tmp_path/'inventory-before.json').exists()


def test_bulk_rank_query_retains_location_parameters_and_groups_cards(tmp_path):
    from scripts.brand_keyword_research.repository import Repository
    from test_brand_keyword_research import rank
    repo = Repository(None, tmp_path/'.env')
    c = config(); c['scope'] = 'ALL_STORES'
    observed = rank(); cards = observed.pop('results')
    observed.pop('search_location'); observed.update(latitude=37.5, longitude=127.0, collected_at=AS_OF)
    seen = []
    def query(sql, params=()):
        seen.append((sql, params))
        if 'CROSS APPLY' in sql: return [observed]
        return [dict(card, snapshot_id=1) for card in cards]
    repo.query = query
    rows = repo.rank_observations(c, AS_OF)
    assert len(seen) == 2
    assert seen[0][1][:4] == ('EVAL-1', '황태탕', 37.5, 127.0)
    assert seen[1][1] == (1,)
    assert rows[0]['search_location']['place_id'] == '1'
    assert len(rows[0]['results']) == 20
