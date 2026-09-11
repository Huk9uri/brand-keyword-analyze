from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import canonical
from .pipeline import evaluate_bundle
from .review import export_review, comparison


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(canonical(value)+'\n')


def _connection(env_file):
    import pymssql
    from dotenv import dotenv_values
    v = dotenv_values(env_file)
    if v.get('KEYWORD_DISCOVERY_DB_DATABASE') != 'naverDB':
        raise ValueError('DB_TARGET_MISMATCH')
    return pymssql.connect(server=v['DB_SERVER'], port=v['DB_PORT'], database=v['KEYWORD_DISCOVERY_DB_DATABASE'],
                           user=v['KEYWORD_DISCOVERY_DB_USER'], password=v['KEYWORD_DISCOVERY_DB_PASSWORD'],
                           encryption='require', autocommit=False, use_datetime2=True, login_timeout=10, timeout=30)


def main(argv=None):
    parser = argparse.ArgumentParser(description='키워드 평가: 기본 오프라인, 수집·저장은 별도 명령')
    parser.add_argument('command', choices=['evaluate','export-source','collect-volume','collect-rank','collect-keywords','save','save-reviews','compare'])
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--env-file', type=Path, default=Path('.env'))
    parser.add_argument('--reviews', type=Path)
    parser.add_argument('--allow-write', action='store_true')
    parser.add_argument('--allow-network', action='store_true')
    parser.add_argument('--show-automatic', action='store_true')
    args = parser.parse_args(argv)
    connection = None
    try:
        writes = args.command in ('collect-volume','collect-rank','collect-keywords','save','save-reviews')
        network = args.command.startswith('collect-')
        if writes and not args.allow_write:
            raise ValueError('DB 쓰기에는 별도 승인 후 --allow-write가 필요합니다')
        if network and not args.allow_network:
            raise ValueError('실제 수집에는 별도 승인 후 --allow-network가 필요합니다')
        data = _load(args.input)
        if args.command == 'evaluate':
            if args.output is None:
                raise ValueError('--output 디렉터리가 필요합니다')
            if args.output.exists():
                raise ValueError('기존 출력 경로는 덮어쓰지 않습니다')
            evaluated = evaluate_bundle(data)
            args.output.mkdir(parents=True)
            _write(args.output/'evaluation.json', evaluated)
            _write(args.output/'collection_queue.json', evaluated['collection_queue'])
            export_review(evaluated, args.output/'review.csv', show_automatic=args.show_automatic)
            print(f"평가 {len(evaluated['results'])}개, 수집 후보 {len(evaluated['collection_queue'])}개")
            return 0
        if args.output is None or args.output.exists():
            raise ValueError('새 --output 파일 경로가 필요합니다')
        if not args.output.parent.is_dir():
            raise ValueError('출력 파일의 상위 디렉터리를 먼저 준비하세요')
        if args.command == 'compare':
            if not args.reviews:
                raise ValueError('--reviews가 필요합니다')
            _write(args.output, comparison(data, _load(args.reviews)))
            return 0
        connection = _connection(args.env_file)
        from .repository import EvaluationRepository, VolumeRepository
        if args.command == 'export-source':
            from .source_export import export_bundle
            result = export_bundle(connection, data)
        elif args.command == 'save':
            result = EvaluationRepository(connection).save(data)
        elif args.command == 'save-reviews':
            result = EvaluationRepository(connection).save_reviews(data)
        elif args.command == 'collect-volume':
            from .collection import collect_volumes
            from scripts.yuksudang_volume.searchad import SearchAdClient
            from scripts.yuksudang_volume.config import NaverConfig
            from dotenv import dotenv_values
            env = dotenv_values(args.env_file)
            config = NaverConfig(env['NAVER_SEARCHAD_CUSTOMER_ID'], env['NAVER_SEARCHAD_API_KEY'],
                                 env['NAVER_SEARCHAD_SECRET_KEY'], '', '')
            # 실제 공급자 원문을 받아 기존 손실 파서를 우회한다.
            client = SearchAdClient(config)
            evaluated = evaluate_bundle(data['bundle'])
            keywords = [r['normalized_keyword'] for r in evaluated['results']
                        if r['gate_results']['A'] == 'DINING' and r['gate_results']['B'] == 'PASS'
                        and not set(r['reason_codes']) & {'STORE_OPERATION_CONFLICT','IDENTITY_UNVERIFIED','FIT_CONFLICT'}]
            observations = collect_volumes(keywords, client._request, data['period'])
            result = VolumeRepository(connection).save(observations)
        else:
            from .collection import collect_ranks, collect_keywords
            from scripts.keyword_discovery_rank.config import CollectorConfig
            from scripts.place_keyword_collector.config import PlaceKeywordConfig
            evaluated = evaluate_bundle(data['input_manifest'])
            root = args.env_file.resolve().parent
            artifact_root = args.output.parent/('evaluation-artifacts-'+args.output.stem)
            if args.command == 'collect-rank':
                result = collect_ranks(evaluated, connection, CollectorConfig.from_env(root), artifact_root)
            else:
                result = collect_keywords(evaluated, connection, PlaceKeywordConfig.from_env(root), artifact_root)
        _write(args.output, result)
        return 0
    except Exception as exc:
        # 연결 라이브러리의 예외 본문에 비밀이 포함될 수 있어 그대로 표시하지 않는다.
        print(f'실행 실패: {exc}' if isinstance(exc, ValueError) else '실행 실패: 입력·출력 또는 저장 계약을 확인하세요', file=sys.stderr)
        return 2
    finally:
        if connection is not None:
            connection.close()


if __name__ == '__main__':
    raise SystemExit(main())
