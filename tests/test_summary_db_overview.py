import json
from pathlib import Path
import pytest
from scripts.menu_keyword_pipeline.summary_db import SummaryDB
from scripts.menu_keyword_pipeline.overview import aggregate,generate,validate


def populate(root):
    db=SummaryDB(root)
    for code in ['001','002']:
        result={'recommendations':[dict(evidence_id='P:'+code+':냉면',reason='판매 확인',checks='현재 판매 확인')]}
        packet=dict(store={'store_name':code},keywords=[dict(evidence_id='P:'+code+':냉면',query='냉면',volume=100,
                    amount='1000',qty='2',decision='CANDIDATE')],store_quality={'missing_dates':[]},unmapped_summary={})
        with db.conn:db.conn.execute('INSERT OR REPLACE INTO summaries VALUES(?,?,?,?,?,?,?)',
           (db.run_id,code,'hash',json.dumps(result),json.dumps(packet),'{}','보고서'))
    return db


def test_aggregate_unique_stores_and_does_not_sum_national_volume(tmp_path):
    db=populate(tmp_path)
    packet=aggregate(db)
    assert packet['store_count']==2 and packet['recommendation_count']==2
    assert packet['keywords'][0]['volume']==100
    assert packet['keywords'][0]['recommended_store_count']==2
    assert len(packet['keywords'][0]['stores'])==2
    assert packet['most_recommended_keywords']==['냉면']
    db.close()


def test_overview_recovers_database_failure_without_api_recall(tmp_path,monkeypatch):
    db=populate(tmp_path);calls=[]
    def post(payload,key):
        calls.append(payload)
        data=dict(executive='검색 유입을 시험합니다.',actions='현재 메뉴 확인',cautions='전국 검색량입니다.',
                  priorities=[dict(query='냉면',reason='여러 매장에서 추천됨')])
        return dict(status='completed',id='test',usage={'input_tokens':100,'output_tokens':50},
                    output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(data))])])
    real=db.save_overview
    def fail(*args):raise OSError('DB unavailable')
    monkeypatch.setattr(db,'save_overview',fail)
    with pytest.raises(OSError):generate(tmp_path,db,'key',post=post)
    monkeypatch.setattr(db,'save_overview',real)
    generate(tmp_path,db,'key',post=post)
    assert len(calls)==1
    assert db.conn.execute('SELECT count(*) FROM overviews').fetchone()[0]==1
    assert '정상 요약 매장 2개' in (tmp_path/'summary.md').read_text(encoding='utf-8')
    assert '확인 사항 — 코드 집계' in (tmp_path/'summary.md').read_text(encoding='utf-8')
    db.close()


def test_rejects_wrong_most_recommended_keyword():
    packet={'keywords':[{'query':'냉면'},{'query':'만두'}],'most_recommended_keywords':['만두']}
    data=dict(executive='요약',actions='확인',cautions='주의',
              priorities=[dict(query='냉면',reason='가장 많은 추천 매장에 연결됩니다.')])
    with pytest.raises(ValueError,match='INVALID_MOST_RECOMMENDED_CLAIM'):validate(data,packet)
