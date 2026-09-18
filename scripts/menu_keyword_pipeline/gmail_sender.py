"""Gmail API로 검증 완료된 종합 요약 발송. 전송 결과 불명 시 자동 재전송 금지."""
import base64
import hashlib
import json
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
import requests
from markdown_it import MarkdownIt
from .workflow import write

SCOPE='https://www.googleapis.com/auth/gmail.send'


def render_html(body):
    """원문 HTML을 실행하지 않고 이메일용 마크다운 서식을 렌더링한다."""
    content=MarkdownIt('commonmark',{'html':False}).render(body)
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"></head>'
        '<body><div style="max-width:760px;margin:0 auto;padding:24px;'
        'font-family:Arial,sans-serif;font-size:15px;line-height:1.7;color:#202124">'
        +content+'</div></body></html>')


def access_token(token_file,post=requests.post):
    path=Path(token_file)
    if not path.exists():raise ValueError('GMAIL_AUTH_REQUIRED')
    data=json.loads(path.read_text(encoding='utf-8'))
    if not all(data.get(k) for k in ('client_id','client_secret','refresh_token')):raise ValueError('GMAIL_AUTH_REQUIRED')
    response=post('https://oauth2.googleapis.com/token',data={
        'client_id':data['client_id'],'client_secret':data['client_secret'],'refresh_token':data['refresh_token'],
        'grant_type':'refresh_token'},timeout=(15,45))
    if response.status_code!=200:raise ValueError('GMAIL_AUTH_REFRESH_FAILED')
    token=response.json().get('access_token')
    if not token:raise ValueError('GMAIL_AUTH_REFRESH_FAILED')
    return token


def deliver(root,config,*,preview=False,token_provider=access_token,post=requests.post):
    root=Path(root)
    addresses=[config.get('sender'),*config.get('recipients',[])]
    if len(addresses)<2 or any(not isinstance(a,str) or '\n' in a or '\r' in a or parseaddr(a)[1]!=a or '@' not in a for a in addresses):
        raise ValueError('INVALID_ADDRESS')
    def read(name):return json.loads((root/name).read_text(encoding='utf-8'))
    if read('status.json').get('stage')!='DONE':raise ValueError('ANALYSIS_NOT_FINISHED')
    if read('store-summary-status.json').get('status')!='VALIDATED' or read('overview-receipt.json').get('status')!='VALIDATED':
        raise ValueError('SUMMARY_NOT_VALIDATED')
    body=(root/'summary.md').read_text(encoding='utf-8')
    quality=read('quality.json')
    subject=f"[매장 키워드 분석 요약] {quality.get('start')} ~ {quality.get('end')} (종료일 제외)"
    digest=hashlib.sha256(json.dumps([addresses[0],sorted(addresses[1:]),subject,body],ensure_ascii=False).encode()).hexdigest()
    ledger=root/'mail-delivery.json'
    def prior():
        if ledger.exists():
            old=read(ledger.name)
            if old.get('status') in ('SENDING','UNKNOWN','ACCEPTED','PARTIAL_ACCEPTED'):
                if old.get('key')!=digest:raise ValueError('EXISTING_DELIVERY_REQUIRES_REVIEW')
                return old
    old=prior()
    if old:return old
    msg=EmailMessage();msg['From']=addresses[0];msg['To']=', '.join(addresses[1:]);msg['Subject']=subject
    msg['Message-ID']=f'<{digest}@keyword-report.local>'
    msg.set_content(body)
    html=render_html(body)
    msg.add_alternative(html,subtype='html')
    (root/'mail-preview.html').write_text(html,encoding='utf-8')
    (root/'mail-preview.eml').write_bytes(msg.as_bytes())
    if preview:return dict(status='PREVIEW',provider='gmail_api',key=digest)
    lock=root/'mail-send.lock'
    try:
        with lock.open('x',encoding='utf-8') as f:f.write(digest)
    except FileExistsError:raise ValueError('DELIVERY_LOCKED') from None
    try:
        old=prior()
        if old:return old
        # 인증 실패는 아직 발송을 시도하지 않은 상태라 인증 보완 후 재시도 가능하다.
        token=token_provider(config['token_file'])
        write(root,ledger.name,dict(status='SENDING',provider='gmail_api',key=digest))
        try:
            response=post('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
                headers={'Authorization':'Bearer '+token},json={'raw':base64.urlsafe_b64encode(msg.as_bytes()).decode('ascii')},timeout=(15,60))
            if response.status_code==200 and response.json().get('id'):
                result=dict(status='ACCEPTED',message_id=response.json()['id'],note='Gmail API 발송 수락. 수신함 도착은 별도 확인 필요.')
            elif response.status_code in (400,401,403,404,429):
                result=dict(status='REJECTED',http_status=response.status_code)
            else:result=dict(status='UNKNOWN',http_status=response.status_code)
        except Exception as exc:
            result=dict(status='UNKNOWN',error_type=type(exc).__name__)
        result.update(provider='gmail_api',key=digest)
        write(root,ledger.name,result)
        return result
    finally:lock.unlink(missing_ok=True)
