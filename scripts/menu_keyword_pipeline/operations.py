"""수집부터 요약·메일까지 연결하고 미완료 보고 단계를 이어 실행한다."""
import argparse
import json
from pathlib import Path
from datetime import datetime,timezone,timedelta
from uuid import uuid4
from . import cli,delivery_cli
from .workflow import write


def run(state,*,collect,report,scheduled=False):
    state=Path(state);state.mkdir(parents=True,exist_ok=True)
    lock=state/'operations.lock'
    try:
        with lock.open('x',encoding='utf-8') as f:f.write(datetime.now(timezone.utc).isoformat())
    except FileExistsError:return 3
    try:
        journal=state/'operations.json'
        old=json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else {}
        today=datetime.now(timezone(timedelta(hours=9))).date().isoformat()
        if scheduled and old.get('stage')=='DONE' and old.get('completed_date')==today:return 0
        root=Path(old['output']) if old.get('stage')=='DELIVERY_PENDING' else None
        if root is None:
            stamp=datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d-%H%M%S')
            root=state/f'run-{stamp}-{uuid4().hex}'
            write(state,'operations.json',dict(stage='COLLECTING',output=str(root.resolve())))
            result=collect(root)
            status=json.loads((root/'status.json').read_text(encoding='utf-8'))
            if result not in (0,2) or status.get('stage')!='DONE':
                write(state,'operations.json',dict(stage='COLLECTION_FAILED',output=str(root.resolve())))
                return 1
        write(state,'operations.json',dict(stage='DELIVERY_PENDING',output=str(root.resolve())))
        result=report(root)
        if result==0:write(state,'operations.json',dict(stage='DONE',output=str(root.resolve()),completed_date=today))
        return result
    finally:lock.unlink(missing_ok=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',type=Path,default=Path('outputs/scheduled-menu-keywords'))
    p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--registry',type=Path,default=Path('inputs/hanchon_menu_keywords.json'))
    p.add_argument('--model')
    p.add_argument('--send-mail',action='store_true')
    p.add_argument('--scheduled',action='store_true',help='한국 날짜 기준 당일 완료된 실행은 반복하지 않음')
    p.add_argument('--allow-write',action='store_true')
    p.add_argument('--allow-network',action='store_true')
    args=p.parse_args(argv)
    if not (args.allow_write and args.allow_network):p.error('--allow-write --allow-network가 필요합니다')
    def collect(root):
        return cli.main(['--output',str(root),'--env-file',str(args.env_file),'--registry',str(args.registry),'--collect','--allow-write','--allow-network'])
    def report(root):
        options=['--output',str(root),'--env-file',str(args.env_file)]
        if args.model:options+=['--model',args.model]
        if args.send_mail:options+=['--send-mail']
        return delivery_cli.main(options)
    return run(args.state,collect=collect,report=report,scheduled=args.scheduled)


if __name__=='__main__':raise SystemExit(main())
