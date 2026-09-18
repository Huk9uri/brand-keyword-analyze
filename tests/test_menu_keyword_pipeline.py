from datetime import datetime, timezone
from decimal import Decimal
import pytest

from scripts.menu_keyword_pipeline.core import window, aggregate, evaluate, changes

NOW = datetime(2026, 9, 16, 0, 0, tzinfo=timezone.utc)
TARGET = dict(store_code='001', store_name='시험점', place_id='11', target_store_id='IYN-001',
              search_location=dict(latitude=37., longitude=127., place_id='11', source='test', verified_at=NOW.isoformat()))
RULES = dict(rank_ttl_days=7, volume_ttl_days=7)
MAPPING = [dict(query='냉면', pos_menu_names=['물냉면','비빔냉면']), dict(query='물냉면', pos_menu_names=['물냉면'])]


def test_window_uses_korean_midnight_and_excludes_today():
    assert window(NOW) == ('2026-08-17', '2026-09-16')
    assert window(datetime(2026, 9, 15, 14, 59, tzinfo=timezone.utc)) == ('2026-08-16','2026-09-15')
    assert window(datetime(2026, 3, 1, tzinfo=timezone.utc)) == ('2026-01-30','2026-03-01')


def test_sales_mapping_preserves_unknown_and_does_not_multiply_alias_sales():
    sales = [dict(store_code='001',menu_name=n,mapping_names=1,amount=a,qty=q) for n,a,q in
             [('물냉면','1000.10','2'),('비빔냉면','2000.20','3'),('새메뉴','500','1')]]
    out = aggregate([TARGET], sales, MAPPING)
    assert [(r['query'],r['amount'],r['qty']) for r in out['pairs']] == [('냉면','3000.30','5'),('물냉면','1000.10','2')]
    assert out['unmapped'][0]['menu_name']=='새메뉴'
    assert out['keywords']==['냉면','물냉면']


def test_ambiguous_or_nonpositive_sales_are_not_collection_targets():
    rows=[dict(store_code='001',menu_name='물냉면',mapping_names=2,amount='200',qty='1'),
          dict(store_code='001',menu_name='비빔냉면',mapping_names=1,amount='-100',qty='-1')]
    out=aggregate([TARGET],rows,MAPPING)
    assert not out['pairs']
    assert out['unmapped'][0]['reason']=='AMBIGUOUS_MENU'


def observation(status='SUCCESS',count=20):
    return dict(snapshot_id=1,target_store_id='IYN-001',normalized_query='냉면',device_type='MOBILE',
                profile='MOBILE_PLACE_LIST_STORE_LOCATION_ORGANIC20_V4', search_location=TARGET['search_location'],
                collect_status=status,collected_at=NOW.isoformat(),result_end_reached=False,
                results=[dict(place_id=str(100+i),raw_position=i,organic_rank=i,is_ad=False) for i in range(1,count+1)])


def volume(status='EXACT'):
    return dict(searchad_lookup_key='냉면',volume_snapshot_id=1,observation_status=status,total_count=100 if status=='EXACT' else None,
                period_verified=True,fetched_at=NOW.isoformat())


def result(rank=None,vol=None):
    pair=dict(store_code='001',query='냉면',amount='1000',qty='3',menus=['물냉면'])
    return evaluate([TARGET],[pair],[vol or volume()],[rank or observation()],NOW,RULES)[0]


def test_complete_unexposed_rank_becomes_candidate_but_partial_does_not():
    assert result()['decision']=='CANDIDATE'
    for r in [observation('PARTIAL'),observation(count=10)]:
        x=result(rank=r)
        assert x['decision']=='HOLD' and x['visibility']=='UNKNOWN' and x['rank'] is None


@pytest.mark.parametrize('status',['FAILED','CENSORED','NOT_PROVIDED','INVALID'])
def test_volume_unknown_does_not_become_zero_or_recommendation(status):
    x=result(vol=volume(status))
    assert x['decision']=='HOLD' and x['volume'] is None


def test_expired_rank_and_unverified_volume_are_held():
    r=observation();r['collected_at']='2026-09-01T00:00:00+00:00'
    assert result(rank=r)['decision']=='HOLD'
    v=volume();v['period_verified']=False
    assert result(vol=v)['decision']=='HOLD'


def test_visible_result_is_not_new_inflow_candidate():
    r=observation();r['results'][2]['place_id']='11'
    x=result(rank=r)
    assert x['decision']=='EXPOSED' and x['rank']==3


def test_comparison_does_not_call_failed_observation_removed():
    old=result(); new=result(rank=observation('PARTIAL'))
    diff=changes([new],[old],comparable_sales=False)
    assert diff[0]['change']=='HOLD' and diff[0]['amount_delta'] is None
    new=result();new['amount']='1500'
    assert changes([new],[old],comparable_sales=True)[0]['amount_delta']=='500'


def test_pos_code_reuse_and_daily_gaps_are_not_silent_sales_decreases():
    from scripts.menu_keyword_pipeline.sales import prepare_sales
    records=[dict(store_code='001',pos_code='P1',opened='20200101',closed=''),
             dict(store_code='002',pos_code='P1',opened='20200101',closed='20260910')]
    menu=[dict(pos_code='P1',menu_code='M1',amount='100',qty='1')]
    daily=[dict(pos_code='P1',sale_date='2026-09-15',amount='100',qty='1')]
    out=prepare_sales([TARGET],records,menu,daily,[dict(menu_code='M1',menu_name='물냉면',mapping_names=1)],'2026-08-17','2026-09-16')
    assert out['blocked_stores'][0]['reason']=='AMBIGUOUS_POS_CODE'
    assert not out['sales'] and out['quality']['comparable'] is False


def test_pos_join_totals_must_reconcile():
    from scripts.menu_keyword_pipeline.sales import prepare_sales
    with pytest.raises(ValueError,match='POS_TOTAL_MISMATCH'):
        prepare_sales([],[],[dict(pos_code='P',amount='100',qty='1')],[],[],'2026-08-17','2026-09-16')
