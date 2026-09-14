"""누락 순위만 작은 배치로 수집하고 중단 지점을 보존한다."""
from scripts.keyword_evaluation.collection import build_rank_tasks
from scripts.keyword_evaluation.contracts import keyword_key
from scripts.keyword_evaluation.cli import _write


def collect_in_batches(evaluated, connection, config, root, batch_size=100, *, collect_fn=None):
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
    receipt = dict(processed=0, aborted=False, persistence_failures=0, batches=[],
                   planned=len(queue), remaining=len(queue), reused_tasks=len(evaluated['collection_queue'])-len(queue),
                   reused=not queue)
    _write(root/'rank-plan.json', queue)
    for offset in range(0, len(queue), batch_size):
        batch = queue[offset:offset+batch_size]
        folder = root/f'batch-{offset//batch_size+1:04d}'
        folder.mkdir()
        _write(folder/'plan.json', batch)
        print(f'순위 배치 {offset//batch_size+1}: {len(batch)}건 / 전체 신규 {len(queue)}건', flush=True)
        try:
            current = collect_fn(dict(evaluated, collection_queue=batch), connection, config, folder/'artifacts')
        except Exception as exc:
            _write(folder/'failure.json', dict(error_type=type(exc).__name__, message='배치 실패. DB 유효 자료를 재사용하여 새 경로로 재실행하세요.'))
            raise
        _write(folder/'receipt.json', current)
        receipt['batches'].append(current)
        receipt['processed'] += current['processed']
        receipt['persistence_failures'] += current.get('persistence_failures', 0)
        receipt['remaining'] = len(queue)-receipt['processed']
        if current.get('aborted') or current.get('persistence_failures') or current['processed'] != len(batch):
            receipt.update(aborted=True, abort_reason=current.get('abort_reason') or 'BATCH_INCOMPLETE_OR_SAVE_FAILED')
            break
    _write(root/'rank-receipt.json', receipt)
    return receipt
