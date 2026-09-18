"""최근 30일 POS 기반 매장별 키워드 발굴. 기본은 DB 읽기 전용."""
import argparse
import json
from pathlib import Path
from datetime import datetime,timezone,timedelta
from uuid import uuid4
from .core import validate_registry
from .workflow import execute,find_previous


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry',type=Path,default=Path('inputs/hanchon_menu_keywords.json'))
    p.add_argument('--output',type=Path,help='생략하면 outputs 아래에 한국 시간 실행 시각과 고유 ID로 자동 생성')
    p.add_argument('--previous',type=Path,help='이전 실행 출력 폴더. 생략하면 같은 상위 폴더의 최근 분석을 자동 선택')
    p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--collect',action='store_true')
    p.add_argument('--allow-write',action='store_true')
    p.add_argument('--allow-network',action='store_true')
    args=p.parse_args(argv)
    if args.collect and not (args.allow_write and args.allow_network): p.error('수집에는 --allow-write --allow-network가 필요합니다')
    if args.output is None:
        stamp=datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d-%H%M%S-%f')
        args.output=Path('outputs')/f'menu-keywords-{stamp}-{uuid4().hex}'
    if args.output.exists(): p.error('새 출력 경로를 지정하세요. 정상 저장된 자료는 DB에서 재사용합니다.')
    if args.previous and any(not (args.previous/n).is_file() for n in ('results.json','registry.json','quality.json')):
        p.error('이전 결과 폴더에 results.json, registry.json, quality.json이 필요합니다')
    registry=json.loads(args.registry.read_text(encoding='utf-8'));validate_registry(registry)
    previous=args.previous or (find_previous(args.output.parent) if args.output.parent.exists() else None)
    print(f'결과 저장 경로: {args.output.resolve()}',flush=True)
    from scripts.keyword_evaluation.cli import _connection
    from .repository import Adapter
    try: connection=_connection(args.env_file)
    except Exception as exc:
        from .workflow import write
        args.output.mkdir(parents=True)
        write(args.output,'status.json',dict(status='FAILED',stage='CONNECT',error_type=type(exc).__name__))
        print('DB 연결 실패. status.json을 확인하세요.')
        return 1
    try:
        status=execute(registry,args.output,Adapter(connection,args.env_file),collect=args.collect,previous=previous)
        print(json.dumps(status,ensure_ascii=True))
        return {'COMPLETE':0,'PARTIAL':2,'FAILED':1}[status['status']]
    finally: connection.close()


if __name__=='__main__':
    raise SystemExit(main())
