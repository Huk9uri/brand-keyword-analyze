import json
from pathlib import Path
import pytest
from scripts.menu_keyword_pipeline.summary import make_packet


def dataset(root):
    def save(name,data): (root/name).write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    rows=[dict(store_code=c,store_name=c,query=q,amount='100',qty='2',menus=['실제메뉴'],decision=d,
               rank_status='VALID' if d!='HOLD' else 'STALE',volume_status='EXACT',volume=100,
               rank=2 if d=='EXPOSED' else None,rank_at='2026-09-16',volume_at='2026-09-15',rank_snapshot_id=1)
          for c,q,d in [('001','국','CANDIDATE'),('001','탕','EXPOSED'),('001','찜','HOLD'),('002','국','CANDIDATE')]]
    save('results.json',rows)
    save('status.json',dict(stage='DONE',status='PARTIAL'))
    save('quality.json',dict(start='2026-08-18',end='2026-09-17',status='REVIEW_REQUIRED',stores=[dict(store_code='001',missing_dates=['2026-09-01'])]))
    save('changes.json',dict(comparable_sales=False,rows=[dict(store_code='001',query='국',change='NEW_CANDIDATE',amount_delta=None)]))
    save('registry.json',dict(candidates=[dict(query=q,pos_menu_names=['실제메뉴'],condition='직접 대응') for q in ['국','탕','찜']]))
    save('sales.json',dict(sales=[dict(store_code='001',menu_name='실제메뉴',mapping_names=1,amount='100',qty='2')],targets=[dict(store_code='003',store_name='자료없음')],inventory=[],blocked_stores=[]))
    save('unmapped-menus.json',[dict(store_code='001',menu_name='미연결',reason='UNMAPPED_MENU')])
    save('observations.json',dict(ranks=[dict(snapshot_id=1,results=[dict(place_id='p',place_name='경쟁점',organic_rank=1,is_ad=False),dict(place_id='ad',is_ad=True)])]))


def test_all_stores_and_decisions_are_preserved(tmp_path):
    dataset(tmp_path);p=make_packet(tmp_path)
    assert p['version']==2
    assert [s['store_code'] for s in p['stores']]==['001','002','003']
    s=p['stores'][0]
    assert {r['decision'] for r in s['keywords']}=={'CANDIDATE','EXPOSED','HOLD'}
    assert s['quality']['missing_dates']==['2026-09-01']
    assert s['unmapped_menus'][0]['menu_name']=='미연결'
    r=s['keywords'][0]
    assert r['menus']==['실제메뉴'] and r['menu_sales'][0]['amount']=='100'
    assert r['mapping']['condition']=='직접 대응'
    assert r['rank_at']=='2026-09-16'
    assert r['search_results'][0]['place_name']=='경쟁점' and len(r['search_results'])==1
    assert r['change']['amount_delta'] is None
    assert s['keywords'][2]['hold_reasons']==['RANK_STALE']


def test_store_scope_does_not_include_other_store(tmp_path):
    dataset(tmp_path);p=make_packet(tmp_path,store_code='001')
    assert p['scope']=={'type':'STORE','store_code':'001'}
    assert len(p['stores'])==1 and len(p['stores'][0]['keywords'])==3
    assert '판매 확인 3건' in p['facts']['RUN']
    with pytest.raises(ValueError,match='UNKNOWN_STORE'):make_packet(tmp_path,store_code='999')


def test_optional_sources_missing_are_explicit(tmp_path):
    dataset(tmp_path);(tmp_path/'observations.json').unlink()
    p=make_packet(tmp_path)
    assert p['sources']['observations.json']=='MISSING'
    assert p['stores'][0]['keywords'][0]['search_results'] is None


def test_oversized_input_stops_before_paid_call(tmp_path,monkeypatch):
    from scripts.menu_keyword_pipeline import summary
    monkeypatch.setattr(summary,'make_packet',lambda *a,**k:{'large':'x'*150001})
    def forbidden(*args):raise AssertionError('oversized input must not call API')
    with pytest.raises(ValueError,match='INPUT_TOO_LARGE_SELECT_STORE'):
        summary.generate(tmp_path,'test','key',post=forbidden)
    assert (tmp_path/'summary-input.json').exists()


def test_store_generation_uses_only_requested_store_and_separate_output(tmp_path):
    from scripts.menu_keyword_pipeline.summary import generate
    dataset(tmp_path)
    def post(payload,key):
        p=json.loads(payload['input']);assert p['version']==3
        assert p['store']['store_code']=='001'
        out=dict(recommendations=[],no_recommendation_reason='관측 공백을 확인한 뒤 추천합니다.',existing_visibility='탕이 노출되어 있습니다.',data_notes='공백 확인이 필요합니다.')
        return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(out)}]}]}
    receipt=generate(tmp_path,'test','key',post=post,store_code='001')
    assert receipt['status']=='VALIDATED'
    assert not (tmp_path/'summary.md').exists()
    assert len(list((tmp_path/'store-summaries').glob('*/summary.md')))==1
