import copy
import pytest
from scripts.menu_keyword_pipeline.recommendation import compact,validate,markdown


def packet():
    row=dict(fact_id='P:001:냉면',query='냉면',decision='CANDIDATE',amount='1000',qty='3',volume=100,
             rank=None,rank_status='VALID',volume_status='EXACT',visibility='NOT_IN_TOP20',menus=['물냉면'],
             rank_at='2026-09-16',volume_at='2026-09-15',search_results=[{'place_name':'경쟁점'}],
             menu_sales=[dict(menu_name='물냉면',amount='1000',qty='3')],mapping={'condition':'확인 필요'},hold_reasons=[])
    return {'scope':{'type':'STORE','store_code':'001'},'stores':[dict(store_code='001',store_name='시험점',keywords=[row],
            quality={'missing_dates':[]},unmapped_menus=[dict(reason='UNMAPPED_MENU',menu_name='미연결',amount='10',qty='1')])],
            'quality':{'start':'2026-08-18','end':'2026-09-17','status':'REVIEW_REQUIRED'},'comparison':{'comparable_sales':False,'rows':[]},
            'analysis_status':'PARTIAL','analysis_as_of':'2026-09-17','definitions':{},'sources':{}}


def response():
    return dict(recommendations=[dict(evidence_id='P:001:냉면',reason='판매 근거와 검색 수요가 있어 시험할 가치가 있습니다.',
             priority_reason='다른 후보보다 검색 수요를 우선했습니다.',checks='현재 메뉴 운영 여부 확인',next_action='상위 20위 노출을 비교합니다.')],
             no_recommendation_reason='',existing_visibility='노출 현황을 확인합니다.',data_notes='부분 완료 자료입니다.')


def test_compact_removes_competitors_and_duplicate_facts():
    p=compact(packet())
    assert 'facts' not in p
    assert 'search_results' not in str(p) and '경쟁점' not in str(p)
    assert len(p['menus'])==1 and p['keywords'][0]['menu_ids']==['M1']
    assert p['unmapped_summary']['UNMAPPED_MENU']['record_count']==1
    assert '미연결' not in str(p)


def test_validate_and_render_link_source_without_exposing_id():
    p=compact(packet());d=response();validate(d,p);text=markdown(d,p)
    assert 'P:001' not in text and '1,000' in text and '냉면' in text
    assert text.index('우선 공략')<text.index('기존 키워드')


@pytest.mark.parametrize('change',[{'decision':'HOLD'},{'rank_status':'STALE'},{'volume':0},{'rank':2},{'volume_status':'CENSORED'}])
def test_invalid_recommendation_rejected(change):
    raw=packet();raw['stores'][0]['keywords'][0].update(change)
    with pytest.raises(ValueError):validate(response(),compact(raw))


def test_unknown_duplicate_and_excess_ids_rejected():
    p=compact(packet());d=response();d['recommendations'][0]['evidence_id']='P:002:냉면'
    with pytest.raises(ValueError):validate(d,p)


def test_hmr_beef_seaweed_soup_is_retained_but_not_recommendable():
    raw=packet()
    row=copy.deepcopy(raw['stores'][0]['keywords'][0])
    row.update(query='소고기미역국',fact_id='P:001:소고기미역국')
    raw['stores'][0]['keywords'].append(row)
    p=compact(raw)
    assert p['keywords'][0]['recommendable'] is True
    excluded=p['keywords'][1]
    assert excluded['recommendable'] is False
    assert excluded['amount']=='1000'
    assert 'HMR' in excluded['exclusion_reason']
    d=response();d['recommendations'][0]['evidence_id']=row['fact_id']
    with pytest.raises(ValueError,match='INVALID_RECOMMENDATION_EVIDENCE'):validate(d,p)
    d=response();d['recommendations']*=2
    with pytest.raises(ValueError):validate(d,p)


def test_requires_five_when_five_eligible_and_all_when_fewer():
    raw=packet();base=raw['stores'][0]['keywords'][0]
    raw['stores'][0]['keywords']=[dict(base,query=str(i),fact_id='P:001:'+str(i)) for i in range(6)]
    p=compact(raw);d=response()
    d['recommendations']=[dict(d['recommendations'][0],evidence_id='P:001:'+str(i)) for i in range(5)]
    validate(d,p)
    d['recommendations'].pop()
    with pytest.raises(ValueError,match='INVALID_RECOMMENDATION_COUNT'):validate(d,p)
    d=response();d['recommendations']*=4
    with pytest.raises(ValueError):validate(d,p)
