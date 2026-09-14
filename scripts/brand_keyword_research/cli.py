"""검토 후보 설정으로 브랜드 비교 보고서를 생성한다. 기본은 DB 조회 전용."""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from scripts.keyword_evaluation.cli import _load, _write
from scripts.keyword_evaluation.contracts import digest
from .core import validate_config, analyze, report


def save_report(root, state):
    result = analyze(state)
    _write(root/'input.json', state)
    _write(root/'comparison.json', result)
    (root/'report.md').write_text(report(state, result), encoding='utf-8')
    from .summary import write_csvs
    write_csvs(root, state, result, result['keyword_summary'])
    _write(root/'verification.json', dict(input_hash=digest(state), comparison_hash=digest(result),
                                         rank_rows=len(result['rows']), incomplete_rows=result['incomplete_rows']))
    return result


def execute(config, root, repo, collect=False, start=None, end=None):
    validate_config(config)
    if root.exists(): raise ValueError('새 출력 경로를 지정하세요')
    root.mkdir(parents=True)
    _write(root/'config.json', config)
    stage = 'READ'
    try:
        inventory = None
        if config.get('scope') == 'ALL_STORES':
            stage = 'INVENTORY'
            config, inventory = repo.prepare(config, collect=collect, root=root)
            validate_config(config)
        inventory_at = datetime.now(timezone.utc).isoformat()
        stage = 'READ'
        state = repo.read(config, start, end)
        if inventory is not None:
            state.update(inventory=inventory, inventory_as_of=inventory_at)
        receipt = {}
        if collect:
            _write(root/'before.json', state)
            stage = 'COLLECT'
            receipt = repo.collect(state, root)
            stage = 'VERIFY_READ'
            state = repo.read(config, start, end)
            if inventory is not None:
                state.update(inventory=inventory, inventory_as_of=inventory_at)
        stage = 'REPORT'
        result = save_report(root, state)
        partial = bool(result['incomplete_rows'] or result.get('excluded_stores') or receipt.get('aborted')
                       or receipt.get('persistence_failures') or result['warnings'])
        _write(root/'status.json', dict(status='PARTIAL' if partial else 'COMPLETE', collected=collect,
                                       receipt=receipt, incomplete_rows=result['incomplete_rows'],
                                       excluded_stores=result.get('excluded_stores', 0)))
        return 2 if partial else 0
    except Exception as exc:
        _write(root/'status.json', dict(status='FAILED', stage=stage, error_type=type(exc).__name__,
                                       message='해당 단계 실패. 원자료를 보존했으며 새 경로로 재실행하세요.'))
        return 1


def replay(source, root):
    if root.exists(): raise ValueError('새 출력 경로를 지정하세요')
    state = _load(source); validate_config(state['config'])
    root.mkdir(parents=True)
    result = save_report(root, state)
    _write(root/'status.json', dict(status='REPLAY', incomplete_rows=result['incomplete_rows']))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--config', type=Path)
    source.add_argument('--replay', type=Path, help='기존 실행 input.json, 네트워크 없이 재현')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start', help='매출 시작일 포함 YYYY-MM-DD')
    parser.add_argument('--end', help='매출 종료일 미포함 YYYY-MM-DD')
    parser.add_argument('--env-file', type=Path, default=Path('.env'))
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--all-stores', action='store_true', help='ERP 한촌 운영 매장 전체를 조회하여 집계')
    parser.add_argument('--batch-size', type=int, default=None, help='전체 매장 순위 수집 배치 크기 1~100 (기본 100)')
    parser.add_argument('--allow-write', action='store_true')
    parser.add_argument('--allow-network', action='store_true')
    args = parser.parse_args(argv)
    if args.replay:
        if args.collect or args.start or args.end or args.all_stores or args.batch_size is not None:
            parser.error('재현은 기간·매장 범위 변경·수집과 함께 사용할 수 없습니다')
        return replay(args.replay, args.output)
    if args.collect and not (args.allow_write and args.allow_network):
        parser.error('수집에는 --allow-write --allow-network가 필요합니다')
    config = _load(args.config)
    if args.all_stores:
        config['scope'] = 'ALL_STORES'
    if args.batch_size is not None:
        if config.get('scope') != 'ALL_STORES': parser.error('--batch-size는 전체 매장 모드에서 사용합니다')
        config['batch_size'] = args.batch_size
    validate_config(config)
    if args.output.exists(): parser.error('새 출력 경로를 지정하세요')
    from scripts.keyword_evaluation.cli import _connection
    from .repository import Repository
    try:
        connection = _connection(args.env_file)
    except Exception as exc:
        args.output.mkdir(parents=True)
        _write(args.output/'config.json', config)
        _write(args.output/'status.json', dict(status='FAILED', stage='CONNECT', error_type=type(exc).__name__,
                                              message='DB 연결 실패. 환경 설정과 접근 권한을 확인하세요.'))
        print('DB 연결 실패. status.json을 확인하세요.')
        return 1
    try:
        code = execute(config, args.output, Repository(connection, args.env_file), args.collect, args.start, args.end)
        print(f'결과: {args.output} / 종료 코드 {code}', flush=True)
        return code
    finally:
        connection.close()


if __name__ == '__main__':
    raise SystemExit(main())
