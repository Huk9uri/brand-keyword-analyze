"""완료된 분석의 모델 비교·요약·메일 준비 및 발송. 비밀값은 환경에서 읽는다."""
import argparse
import json
import os
from pathlib import Path
from dotenv import dotenv_values
from .summary import generate,make_packet
from .benchmark import compare
from .mailer import deliver
from .workflow import write
from .store_summaries import run as generate_stores, MODEL
from .overview import generate as generate_overview
from .gmail_sender import deliver as gmail_deliver


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--model')
    p.add_argument('--store-code',help='해당 매장의 모든 비교 조합을 포함한 요약')
    p.add_argument('--prepare-input',action='store_true',help='API 호출 없이 입력 JSON만 생성')
    p.add_argument('--compare-models',action='store_true')
    p.add_argument('--workers',type=int,choices=range(1,5),default=1,help='매장별 LLM 동시 호출 수 (기본 1)')
    group=p.add_mutually_exclusive_group()
    group.add_argument('--preview-mail',action='store_true')
    group.add_argument('--send-mail',action='store_true')
    args=p.parse_args(argv)
    if args.store_code and (args.send_mail or args.preview_mail):
        p.error('매장별 입력·요약은 현재 메일 발송과 함께 사용할 수 없습니다')
    env={**dotenv_values(args.env_file),**os.environ}
    try:
        if args.prepare_input:
            import hashlib
            name='summary-input-v2.json' if args.store_code is None else 'summary-input-store-'+hashlib.sha256(args.store_code.encode()).hexdigest()[:16]+'.json'
            packet=make_packet(args.output,store_code=args.store_code)
            if args.store_code:
                from .recommendation import compact
                packet=compact(packet)
            write(args.output,name,packet)
            print(str(args.output/name))
            return 0
        if args.compare_models:
            results=compare(args.output,env.get('OPENAI_API_KEY'),store_code=args.store_code)
            return 0 if all(r['status']=='VALIDATED' for r in results) else 1
        model=args.model or MODEL
        if args.store_code:
            receipt=generate(args.output,model,env.get('OPENAI_API_KEY'),store_code=args.store_code)
        else:
            receipt=generate_stores(args.output,env.get('OPENAI_API_KEY'),model=model,overview=generate_overview,workers=args.workers)
        if receipt['status']!='VALIDATED':
            write(args.output,'delivery-status.json',receipt)
            return 2
        if args.preview_mail or args.send_mail:
            config=dict(sender=env.get('MAIL_FROM'),token_file=env.get('GMAIL_TOKEN_FILE',str(args.env_file.resolve().parent/'.secrets/gmail-token.json')),
                        recipients=[s.strip() for s in env.get('MAIL_TO','').split(',') if s.strip()])
            receipt=gmail_deliver(args.output,config,preview=args.preview_mail)
        write(args.output,'delivery-status.json',receipt)
        print(json.dumps(receipt,ensure_ascii=True))
        return 0 if receipt['status'] in ('VALIDATED','PREVIEW','ACCEPTED') else 2
    except Exception as exc:
        # 외부 오류 본문에 인증정보나 수신자 정보가 포함될 수 있으므로 종류만 기록한다.
        write(args.output,'delivery-status.json',dict(status='FAILED',error_type=type(exc).__name__))
        print('요약·발송 실패: 설정 및 delivery-status.json을 확인하세요.')
        return 1


if __name__=='__main__':raise SystemExit(main())
