from copy import deepcopy

import pytest

from scripts.brand_keyword_research.core import rank_input
from test_brand_keyword_research import state, rank


def large_state(count=205):
    s = state(); s['config']['scope'] = 'ALL_STORES'
    first = s['config']['targets'][0]
    s['config']['targets'] = []
    for i in range(count):
        target = deepcopy(first)
        target.update(place_id=str(i+1), target_store_id='EVAL-'+str(i+1))
        target['search_location']['place_id'] = str(i+1)
        s['config']['targets'].append(target)
    return s


def grouped_state(store_count=2, keyword_count=34):
    s = large_state(store_count)
    template = s['config']['candidates'][0]
    s['config']['candidates'] = [
        {**template, 'id': f'keyword-{i:02d}', 'query': f'검색어 {i:02d}'}
        for i in range(keyword_count)
    ]
    evaluated = rank_input(s)
    evaluated['collection_queue'].sort(key=lambda row: row['target_place_id'])
    return evaluated


def test_205_tasks_split_without_duplicates_or_dropped_stores(tmp_path):
    from scripts.brand_keyword_research.batch_collection import collect_in_batches
    seen = []
    def collect(evaluated, *args):
        queue = evaluated['collection_queue']; seen.extend(q['target_place_id'] for q in queue)
        return {'processed': len(queue), 'aborted': False, 'persistence_failures': 0}
    result = collect_in_batches(rank_input(large_state()), None, None, tmp_path, 100, collect_fn=collect)
    assert [b['processed'] for b in result['batches']] == [100, 100, 5]
    assert len(seen) == len(set(seen)) == 205
    assert result['remaining'] == 0
    assert len(list(tmp_path.glob('batch-*/receipt.json'))) == 3


def test_grouped_batches_do_not_split_store_that_fits_limit(tmp_path):
    from scripts.brand_keyword_research.batch_collection import collect_in_batches
    sizes = []

    def collect(evaluated, *args):
        queue = evaluated['collection_queue']
        sizes.append(len(queue))
        return {'processed': len(queue), 'aborted': False, 'persistence_failures': 0}

    result = collect_in_batches(
        grouped_state(), None, None, tmp_path, 50,
        collect_fn=collect, group_key=lambda row: row['target_place_id'],
    )

    assert sizes == [34, 34]
    assert result['boundary_splits'] == 0


def test_group_larger_than_limit_splits_without_drops_or_duplicates(tmp_path):
    from scripts.brand_keyword_research.batch_collection import collect_in_batches
    seen = []
    sizes = []

    def collect(evaluated, *args):
        queue = evaluated['collection_queue']
        sizes.append(len(queue))
        seen.extend(row['candidate_id'] for row in queue)
        return {'processed': len(queue), 'aborted': False, 'persistence_failures': 0}

    result = collect_in_batches(
        grouped_state(store_count=1, keyword_count=67), None, None, tmp_path, 50,
        collect_fn=collect, group_key=lambda row: row['target_place_id'],
    )

    assert sizes == [50, 17]
    assert len(seen) == len(set(seen)) == 67
    assert result['boundary_splits'] == 1


def test_batch_receipt_sums_collector_metrics(tmp_path):
    from scripts.brand_keyword_research.batch_collection import collect_in_batches

    def collect(evaluated, *args):
        size = len(evaluated['collection_queue'])
        return {
            'processed': size,
            'aborted': False,
            'persistence_failures': 0,
            'metrics': {
                'browser_create_count': 1,
                'browser_close_count': 1,
                'search_attempt_count': size,
                'retry_count': 0,
                'damaged_restart_count': 0,
                'profile_change_restart_count': 0,
                'browser_create_seconds': 2.5,
                'browser_close_seconds': 1.5,
                'search_seconds': size * 3.0,
                'explicit_wait_seconds': size * 15.0,
                'total_elapsed_seconds': size * 18.0 + 4.0,
            },
        }

    result = collect_in_batches(
        grouped_state(), None, None, tmp_path, 50,
        collect_fn=collect, group_key=lambda row: row['target_place_id'],
    )

    assert result['metrics'] == {
        'browser_create_count': 2,
        'browser_close_count': 2,
        'search_attempt_count': 68,
        'retry_count': 0,
        'damaged_restart_count': 0,
        'profile_change_restart_count': 0,
        'browser_create_seconds': 5.0,
        'browser_close_seconds': 3.0,
        'search_seconds': 204.0,
        'explicit_wait_seconds': 1020.0,
        'total_elapsed_seconds': 1232.0,
    }


@pytest.mark.parametrize('receipt', [
    {'processed': 1, 'aborted': True, 'persistence_failures': 0, 'abort_reason': 'SECURITY_CHECK_REQUIRED'},
    {'processed': 100, 'aborted': False, 'persistence_failures': 1},
])
def test_abort_or_failed_save_stops_later_batches(tmp_path, receipt):
    from scripts.brand_keyword_research.batch_collection import collect_in_batches
    result = collect_in_batches(rank_input(large_state()), None, None, tmp_path, 100,
                                collect_fn=lambda *args: receipt)
    assert len(result['batches']) == 1
    assert result['aborted'] is True
    assert result['remaining'] == 205 - receipt['processed']


def test_reexecution_reuses_valid_observation_and_only_plans_remaining(tmp_path):
    from scripts.brand_keyword_research.batch_collection import collect_in_batches
    s = large_state(2); s['ranks'] = [rank()]
    seen = []
    def collect(evaluated, *args):
        seen.extend(q['target_place_id'] for q in evaluated['collection_queue'])
        return {'processed': 1, 'aborted': False, 'persistence_failures': 0}
    result = collect_in_batches(rank_input(s), None, None, tmp_path, 100, collect_fn=collect)
    assert seen == ['2']
    assert result['reused_tasks'] == 1


@pytest.mark.parametrize('size', [0, 101, True, -1])
def test_invalid_batch_size_fails_before_collection(tmp_path, size):
    from scripts.brand_keyword_research.batch_collection import collect_in_batches
    with pytest.raises(ValueError):
        collect_in_batches(rank_input(large_state(1)), None, None, tmp_path, size)
