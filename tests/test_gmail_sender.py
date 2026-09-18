import base64
import json
from email import message_from_bytes
import pytest
from scripts.menu_keyword_pipeline.gmail_sender import deliver


def fixture(root):
    for name,value in {'status.json':{'stage':'DONE'},'quality.json':{'start':'2026-08-18','end':'2026-09-17'},
        'store-summary-status.json':{'status':'VALIDATED'},'overview-receipt.json':{'status':'VALIDATED'}}.items():
        (root/name).write_text(json.dumps(value),encoding='utf-8')
    (root/'summary.md').write_text('종합 요약입니다.',encoding='utf-8')
    return dict(sender='from@gmail.com',recipients=['to@gmail.com'],token_file='not-used')


def test_gmail_sends_summary_once_and_records_id(tmp_path):
    config=fixture(tmp_path);calls=[]
    class Response:
        status_code=200
        def json(self):return {'id':'gmail123'}
    def post(url,**kwargs):
        calls.append(url)
        msg=message_from_bytes(base64.urlsafe_b64decode(kwargs['json']['raw']))
        assert msg.get_content_type()=='multipart/alternative'
        plain,html=msg.get_payload()
        assert plain.get_content_type()=='text/plain'
        assert plain.get_payload(decode=True).decode('utf-8').strip()=='종합 요약입니다.'
        assert html.get_content_type()=='text/html'
        assert '<p>종합 요약입니다.</p>' in html.get_payload(decode=True).decode('utf-8')
        return Response()
    result=deliver(tmp_path,config,token_provider=lambda p:'secret',post=post)
    assert result['status']=='ACCEPTED' and result['message_id']=='gmail123'
    assert deliver(tmp_path,config,token_provider=lambda p:'secret',post=post)==result
    assert len(calls)==1
    assert 'secret' not in (tmp_path/'mail-delivery.json').read_text(encoding='utf-8')


def test_html_formats_markdown_and_escapes_raw_html():
    from scripts.menu_keyword_pipeline.gmail_sender import render_html
    html=render_html('# 요약\n\n## 후보\n\n**냉면**\n\n- 만두\n\n<script>alert(1)</script>')
    assert '<h1>요약</h1>' in html and '<h2>후보</h2>' in html
    assert '<strong>냉면</strong>' in html and '<li>만두</li>' in html
    assert '<script>' not in html and '&lt;script&gt;' in html


def test_unknown_send_not_retried(tmp_path):
    config=fixture(tmp_path);calls=[]
    def fail(*args,**kwargs):calls.append(True);raise TimeoutError()
    assert deliver(tmp_path,config,token_provider=lambda p:'token',post=fail)['status']=='UNKNOWN'
    assert deliver(tmp_path,config,token_provider=lambda p:'token',post=fail)['status']=='UNKNOWN'
    assert len(calls)==1


def test_auth_failure_does_not_record_sending(tmp_path):
    config=fixture(tmp_path)
    def fail(path):raise ValueError('GMAIL_AUTH_REQUIRED')
    with pytest.raises(ValueError):deliver(tmp_path,config,token_provider=fail)
    assert not (tmp_path/'mail-delivery.json').exists()
    assert not (tmp_path/'mail-send.lock').exists()


def test_unvalidated_summary_not_sent(tmp_path):
    config=fixture(tmp_path)
    (tmp_path/'store-summary-status.json').write_text('{"status":"PARTIAL"}')
    with pytest.raises(ValueError,match='SUMMARY_NOT_VALIDATED'):deliver(tmp_path,config)


def test_scheduled_success_runs_once_per_day(tmp_path):
    from scripts.menu_keyword_pipeline.operations import run
    calls=[]
    def collect(root):
        calls.append('collect');root.mkdir();(root/'status.json').write_text('{"stage":"DONE"}');return 0
    def report(root):calls.append('report');return 0
    assert run(tmp_path,collect=collect,report=report,scheduled=True)==0
    assert run(tmp_path,collect=collect,report=report,scheduled=True)==0
    assert calls==['collect','report']
