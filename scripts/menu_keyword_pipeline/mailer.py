"""TLS SMTP 발송과 결과별 중복 방지. SMTP 수락은 수신함 도착을 보증하지 않는다."""
import hashlib
import json
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from .workflow import write


def smtp_send(message,config):
    mode=config['security']
    if mode not in ('ssl','starttls'):raise ValueError('TLS_REQUIRED')
    client=smtplib.SMTP_SSL(config['host'],config['port'],timeout=30,context=ssl.create_default_context()) if mode=='ssl' else smtplib.SMTP(config['host'],config['port'],timeout=30)
    try:
        if mode=='starttls':client.starttls(context=ssl.create_default_context())
        client.login(config['username'],config['password'])
        return client.send_message(message)
    finally:
        try:client.quit()
        except Exception:client.close()


def deliver(root,config,*,send=smtp_send,preview=False):
    root=Path(root)
    recipients=config['recipients']
    if not recipients or any(not isinstance(x,str) or '\n' in x or '\r' in x or '@' not in x for x in [config['sender'],*recipients]):raise ValueError('INVALID_ADDRESS')
    status=json.loads((root/'status.json').read_text(encoding='utf-8'))
    if status.get('stage')!='DONE':raise ValueError('ANALYSIS_NOT_FINISHED')
    subject=f"[키워드 분석 {status['status']}] {root.name}"
    body=(root/'summary.md').read_text(encoding='utf-8')
    detail=(root/'report.md').read_bytes()
    stores=(root/'store-reports.md').read_bytes() if (root/'store-reports.md').exists() else None
    identity=json.dumps([config['sender'],sorted(recipients),subject,body,hashlib.sha256(detail).hexdigest(),
                        hashlib.sha256(stores).hexdigest() if stores is not None else None],ensure_ascii=False)
    key=hashlib.sha256(identity.encode()).hexdigest()
    ledger=root/'mail-delivery.json'
    if ledger.exists():
        old=json.loads(ledger.read_text(encoding='utf-8'))
        if old['status'] in ('SENDING','UNKNOWN','ACCEPTED','PARTIAL_ACCEPTED'):
            if old['key']!=key:raise ValueError('EXISTING_DELIVERY_REQUIRES_REVIEW')
            return old
    msg=EmailMessage();msg['Subject']=subject;msg['From']=config['sender'];msg['To']=', '.join(recipients)
    msg['Message-ID']=f'<{key}@keyword-report.local>'
    msg.set_content(body)
    msg.add_attachment(detail,maintype='text',subtype='markdown',filename='report.md')
    if stores is not None:msg.add_attachment(stores,maintype='text',subtype='markdown',filename='store-reports.md')
    (root/'mail-preview.eml').write_bytes(msg.as_bytes())
    if preview:return dict(status='PREVIEW',key=key)
    lock=root/'mail-send.lock'
    try:
        with lock.open('x',encoding='utf-8') as f:f.write(key)
    except FileExistsError:raise ValueError('DELIVERY_LOCKED') from None
    try:
        # 잠금을 획득하기 전에 다른 실행이 발송을 끝냈을 수 있다.
        if ledger.exists():
            old=json.loads(ledger.read_text(encoding='utf-8'))
            if old['status'] in ('SENDING','UNKNOWN','ACCEPTED','PARTIAL_ACCEPTED'):
                if old['key']!=key:raise ValueError('EXISTING_DELIVERY_REQUIRES_REVIEW')
                return old
        write(root,'mail-delivery.json',dict(status='SENDING',key=key))
        try:
            refused=send(msg,config)
            result=dict(status='PARTIAL_ACCEPTED' if refused else 'ACCEPTED',key=key,refused=list(refused),note='SMTP 수락 상태. 수신함 도착은 별도 확인 필요.')
        except Exception as exc:
            result=dict(status='UNKNOWN',key=key,error_type=type(exc).__name__,note='발송 결과를 확인하기 전 자동 재전송하지 않습니다.')
        write(root,'mail-delivery.json',result)
        return result
    finally:lock.unlink(missing_ok=True)
