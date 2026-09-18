import json
import pytest
from scripts.menu_keyword_pipeline.summary import make_packet, validate_summary, generate
from scripts.menu_keyword_pipeline.mailer import deliver


def source(root):
    root.mkdir()
    files={'status.json':dict(status='PARTIAL',stage='DONE',pair_count=2,candidate_count=1,held_count=1),
           'quality.json':dict(start='2026-08-17',end='2026-09-16',status='REVIEW_REQUIRED'),
           'results.json':[dict(store_code='001',store_name='시험점',query='냉면',decision='CANDIDATE',amount='1000',qty='3',volume=100),
                           dict(store_code='002',store_name='다른점',query='냉면',decision='HOLD',amount='2000',qty='4',volume=None)],
           'changes.json':dict(status='COMPARED',comparable_sales=False,rows=[])}
    for n,d in files.items(): (root/n).write_text(json.dumps(d,ensure_ascii=False),encoding='utf-8')
    (root/'report.md').write_text('상세 보고서',encoding='utf-8')
    return root


def test_packet_distinguishes_partial_and_uses_only_aggregated_facts(tmp_path):
    p=make_packet(source(tmp_path/'run'))
    assert 'PARTIAL' in p['facts']['RUN']
    assert '1' in p['facts']['RUN']
    assert 'results' not in p and 'sales' not in p


def test_summary_cannot_invent_facts_or_rewrite_numbers(tmp_path):
    p=make_packet(source(tmp_path/'run'))
    data={'insights':[{'fact_id':'RUN','evidence':p['facts']['RUN'],'interpretation':'보류 건을 확인해야 합니다.'}]}
    validate_summary(data,p)
    data['insights'][0]['evidence']='전체 완료'
    with pytest.raises(ValueError): validate_summary(data,p)


def test_generate_rejects_incomplete_api_response(tmp_path):
    root=source(tmp_path/'run')
    with pytest.raises(ValueError): generate(root,'test-model','key',post=lambda *a,**k:{'status':'incomplete','output':[]})
    assert not (root/'summary.md').exists()


def test_mail_sent_once_and_ambiguous_send_not_retried(tmp_path):
    root=source(tmp_path/'run'); (root/'summary.md').write_text('요약',encoding='utf-8')
    calls=[]
    config=dict(host='smtp.test',port=465,security='ssl',sender='from@example.com',recipients=['to@example.com'],username='u',password='p')
    def send(msg,cfg):calls.append(msg);return {}
    assert deliver(root,config,send=send)['status']=='ACCEPTED'
    assert deliver(root,config,send=send)['status']=='ACCEPTED'
    assert len(calls)==1
    other=source(tmp_path/'other');(other/'summary.md').write_text('다른 요약',encoding='utf-8')
    def uncertain(msg,cfg):calls.append(msg);raise TimeoutError()
    assert deliver(other,config,send=uncertain)['status']=='UNKNOWN'
    assert deliver(other,config,send=send)['status']=='UNKNOWN'
    assert len(calls)==2


def test_cost_counts_reasoning_only_once():
    from scripts.menu_keyword_pipeline.benchmark import cost
    assert cost('gpt-5-mini',dict(input_tokens=10000,output_tokens=2000,output_tokens_details={'reasoning_tokens':500}))==pytest.approx(.0065)
    assert cost('gpt-5-mini',None) is None


def test_reused_summary_rebuilds_markdown_without_new_api_call(tmp_path):
    root=source(tmp_path/'run');packet=make_packet(root)
    data={'insights':[{'fact_id':'RUN','evidence':packet['facts']['RUN'],'interpretation':'보류 건을 확인해야 합니다.'}]}
    calls=[]
    def post(*args):
        calls.append(True)
        return {'status':'completed','usage':{'input_tokens':100,'output_tokens':50},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(data)}]}]}
    generate(root,'test','key',post=post)
    (root/'summary.md').write_text('변조된 숫자 999',encoding='utf-8')
    generate(root,'test','key',post=post)
    assert len(calls)==1
    assert '999' not in (root/'summary.md').read_text(encoding='utf-8')


def test_operations_retries_delivery_without_recollecting(tmp_path):
    from scripts.menu_keyword_pipeline.operations import run
    collected=[];reported=[]
    def collect(root):collected.append(root);source(root);return 2
    def report(root):reported.append(root);return 1 if len(reported)==1 else 0
    assert run(tmp_path,collect=collect,report=report)==1
    assert run(tmp_path,collect=collect,report=report)==0
    assert len(collected)==1 and reported[0]==reported[1]


def test_operations_lock_prevents_overlap(tmp_path):
    from scripts.menu_keyword_pipeline.operations import run
    (tmp_path/'operations.lock').touch()
    def unexpected(root):raise AssertionError('겹친 실행은 호출되면 안 됨')
    assert run(tmp_path,collect=unexpected,report=unexpected)==3
