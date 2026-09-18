import json
from functools import partial
from scripts.menu_keyword_pipeline.store_summaries import run
from scripts.menu_keyword_pipeline.summary import generate


def test_batch_resumes_failures_and_reuses_validated_stores(tmp_path):
    rows=[dict(store_code=code,store_name=code,query=query,decision='CANDIDATE',amount='100',qty='1',
               volume=100,volume_status='EXACT',rank_status='VALID',rank=None,visibility='NOT_IN_TOP20',menus=[])
          for code,query in [('001','냉면'),('002','만두'),('003','소고기미역국')]]
    for name,value in {'status.json':dict(stage='DONE',status='PARTIAL'),
                       'results.json':rows,'quality.json':dict(start='2026-08-18',end='2026-09-17',status='REVIEW_REQUIRED'),
                       'changes.json':dict(rows=[])}.items():
        (tmp_path/name).write_text(json.dumps(value),encoding='utf-8')
    calls=[];fail=[True]
    def post(payload,key):
        assert payload['model']=='gpt-5.6-luna'
        assert payload['reasoning']=={'effort':'none'}
        packet=json.loads(payload['input']);code=packet['store']['store_code'];calls.append(code)
        if code=='002' and fail[0]:raise TimeoutError()
        data=dict(recommendations=[dict(evidence_id=packet['keywords'][0]['evidence_id'],reason='판매 근거 있음',
                  priority_reason='검색량순',checks='현재 판매 확인',next_action='정보 확인')],
                  no_recommendation_reason='',existing_visibility='별도 확인',data_notes='부분 분석')
        return dict(status='completed',id='response-'+code,usage={'input_tokens':1,'output_tokens':1},
                    output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(data))])])
    generator=partial(generate,post=post)
    first=run(tmp_path,'key',generate_store=generator)
    assert first['status']=='PARTIAL' and first['completed_count']==1 and first['failed_count']==1
    assert first['skipped_stores']==['003']
    fail[0]=False
    second=run(tmp_path,'key',generate_store=generator)
    assert second['status']=='VALIDATED' and second['completed_count']==2
    assert calls==['001','002','002']
    assert '정상 2개' in (tmp_path/'summary.md').read_text(encoding='utf-8')


def test_cli_uses_batch_and_does_not_mail_partial_result(tmp_path,monkeypatch):
    from scripts.menu_keyword_pipeline import delivery_cli
    calls=[]
    def batch(root,key,model,**kwargs):calls.append(model);return {'status':'PARTIAL'}
    monkeypatch.setattr(delivery_cli,'generate_stores',batch)
    def mail(*args,**kwargs):raise AssertionError('부분 결과 발송 금지')
    monkeypatch.setattr(delivery_cli,'deliver',mail)
    assert delivery_cli.main(['--output',str(tmp_path),'--send-mail'])==2
    assert calls==['gpt-5.6-luna']
