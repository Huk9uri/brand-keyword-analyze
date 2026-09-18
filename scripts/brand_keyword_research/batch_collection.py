"""누락 순위만 작은 배치로 수집하고 중단 지점을 보존한다."""
from scripts.keyword_evaluation.collection import build_rank_tasks
from scripts.keyword_evaluation.contracts import keyword_key
from scripts.keyword_evaluation.cli import _write


_METRIC_FIELDS = (
    'browser_create_count', 'browser_close_count', 'search_attempt_count', 'retry_count',
    'damaged_restart_count', 'profile_change_restart_count',
    'browser_create_seconds', 'browser_close_seconds', 'search_seconds',
    'explicit_wait_seconds', 'total_elapsed_seconds',
)


def _plan_batches(queue, batch_size, group_key=None):
    if group_key is None:
        return [queue[offset:offset+batch_size] for offset in range(0, len(queue), batch_size)], 0

    groups = []
    for item in queue:
        key = group_key(item)
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(item)

    batches = []
    current = []
    boundary_splits = 0
    for _, group in groups:
        if len(group) > batch_size:
            if current:
                batches.append(current)
                current = []
            chunks = [group[offset:offset+batch_size] for offset in range(0, len(group), batch_size)]
            batches.extend(chunks)
            boundary_splits += len(chunks) - 1
        elif current and len(current) + len(group) > batch_size:
            batches.append(current)
            current = list(group)
        else:
            current.extend(group)
    if current:
        batches.append(current)
    return batches, boundary_splits


def collect_in_batches(evaluated, connection, config, root, batch_size=100, *, collect_fn=None, group_key=None):
    if type(batch_size) is not int or not 1 <= batch_size <= 100:
        raise ValueError('배치 크기는 1~100 정수')
    if collect_fn is None:
        from scripts.keyword_evaluation.collection import collect_ranks
        collect_fn = collect_ranks
    tasks = build_rank_tasks(evaluated)
    needed = {(t.target_store_id, keyword_key(t.query)) for t in tasks}
    targets = {t['place_id']: t for t in evaluated['input_manifest']['targets']}
    queue = [q for q in evaluated['collection_queue']
             if (targets[q['target_place_id']]['target_store_id'], keyword_key(q['query'])) in needed]
    batches, boundary_splits = _plan_batches(queue, batch_size, group_key)
    receipt = dict(processed=0, aborted=False, persistence_failures=0, batches=[],
                   planned=len(queue), remaining=len(queue), reused_tasks=len(evaluated['collection_queue'])-len(queue),
                   reused=not queue, boundary_splits=boundary_splits,
                   metrics={field: 0 for field in _METRIC_FIELDS})
    _write(root/'rank-plan.json', queue)
    for batch_number, batch in enumerate(batches, 1):
        folder = root/f'batch-{batch_number:04d}'
        folder.mkdir()
        _write(folder/'plan.json', batch)
        print(f'순위 배치 {batch_number}: {len(batch)}건 / 전체 신규 {len(queue)}건', flush=True)
        try:
            current = collect_fn(dict(evaluated, collection_queue=batch), connection, config, folder/'artifacts')
        except Exception as exc:
            _write(folder/'failure.json', dict(error_type=type(exc).__name__, message='배치 실패. DB 유효 자료를 재사용하여 새 경로로 재실행하세요.'))
            raise
        _write(folder/'receipt.json', current)
        receipt['batches'].append(current)
        receipt['processed'] += current['processed']
        receipt['persistence_failures'] += current.get('persistence_failures', 0)
        for field in _METRIC_FIELDS:
            receipt['metrics'][field] += current.get('metrics', {}).get(field, 0)
        receipt['remaining'] = len(queue)-receipt['processed']
        if current.get('aborted') or current.get('persistence_failures') or current['processed'] != len(batch):
            receipt.update(aborted=True, abort_reason=current.get('abort_reason') or 'BATCH_INCOMPLETE_OR_SAVE_FAILED')
            break
    _write(root/'rank-receipt.json', receipt)
    return receipt
