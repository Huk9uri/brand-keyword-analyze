import json
from copy import deepcopy
from datetime import timedelta
from test_menu_keyword_pipeline import NOW,TARGET,observation,volume
from scripts.menu_keyword_pipeline.workflow import execute

REG=dict(version=1,brand='hanchon',mapping_version='test',rank_ttl_days=7,volume_ttl_days=7,
         candidates=[dict(query='냉면',pos_menu_names=['물냉면'])],volume_period={})


class MemoryAdapter:
    """네트워크·DB 경계만 대체하며 계산과 실행기는 실제 코드를 사용한다."""
    def __init__(self):
        self.volumes=[];self.ranks=[];self.volume_requests=[];self.rank_requests=[]
    def read_sales(self,registry,now):
        return dict(targets=[TARGET],inventory=[dict(TARGET,status='ELIGIBLE')],
                    sales=[dict(store_code='001',menu_name='물냉면',mapping_names=1,amount='100',qty='2')],
                    quality=dict(comparable=True,status='OBSERVED',start='2026-08-17',end='2026-09-16'),blocked_stores=[])
    def observations(self,targets,keywords,registry,now): return deepcopy(self.volumes),deepcopy(self.ranks)
    def collect_volume(self,keywords,registry):
        self.volume_requests.append(keywords);self.volumes=[volume()]
        return dict(saved=1)
    def collect_rank(self,evaluated,root):
        self.rank_requests.append(evaluated['collection_queue']);self.ranks=[observation()]
        return dict(aborted=False,persistence_failures=0)


def test_one_run_collects_only_sales_pairs_then_reuses_db_on_rerun(tmp_path):
    a=MemoryAdapter()
    first=execute(REG,tmp_path/'first',a,collect=True,clock=lambda:NOW)
    assert first['status']=='COMPLETE'
    assert a.volume_requests==[['냉면']]
    assert len(a.rank_requests[0])==1
    second=execute(REG,tmp_path/'second',a,collect=True,previous=tmp_path/'first',clock=lambda:NOW)
    assert second['status']=='COMPLETE'
    assert len(a.volume_requests)==1 and len(a.rank_requests)==1
    diff=json.loads((tmp_path/'second'/'changes.json').read_text(encoding='utf-8'))
    assert diff['rows'][0]['change']=='UNCHANGED'


def test_failure_is_partial_and_retry_only_failed_data_next_run(tmp_path):
    a=MemoryAdapter()
    def fail(evaluated,root):
        a.ranks=[observation('PARTIAL')];return dict(aborted=False,persistence_failures=0)
    a.collect_rank=fail
    out=execute(REG,tmp_path/'partial',a,collect=True,clock=lambda:NOW)
    assert out['status']=='PARTIAL'
    assert out['candidate_count']==0 and out['held_count']==1
    a.collect_rank=lambda e,r: (setattr(a,'ranks',[observation()]) or dict(aborted=False,persistence_failures=0))
    out=execute(REG,tmp_path/'retry',a,collect=True,previous=tmp_path/'partial',clock=lambda:NOW)
    assert out['status']=='COMPLETE' and len(a.volume_requests)==1


def test_read_only_run_never_collects_and_save_exception_preserves_failure(tmp_path):
    a=MemoryAdapter()
    out=execute(REG,tmp_path/'read',a,collect=False,clock=lambda:NOW)
    assert out['status']=='PARTIAL' and not a.volume_requests and not a.rank_requests
    def fail(*args): raise RuntimeError('save failed')
    a.collect_volume=fail
    out=execute(REG,tmp_path/'fail',a,collect=True,clock=lambda:NOW)
    assert out['status']=='FAILED' and out['stage']=='VOLUME'
    assert (tmp_path/'fail'/'sales.json').exists()


def test_unconfirmed_volume_does_not_trigger_rank_collection(tmp_path):
    a=MemoryAdapter();a.volumes=[volume('NOT_PROVIDED')]
    out=execute(REG,tmp_path/'held',a,collect=True,clock=lambda:NOW)
    assert out['status']=='PARTIAL' and not a.rank_requests and not a.volume_requests


def test_automatic_baseline_uses_latest_finished_pipeline_run(tmp_path):
    from scripts.menu_keyword_pipeline.workflow import find_previous
    a=MemoryAdapter()
    execute(REG,tmp_path/'first',a,collect=True,clock=lambda:NOW)
    execute(REG,tmp_path/'second',a,collect=True,clock=lambda:NOW+timedelta(seconds=1))
    (tmp_path/'unrelated').mkdir()
    (tmp_path/'unrelated'/'status.json').write_text('{"status":"COMPLETE"}')
    assert find_previous(tmp_path)==tmp_path/'second'


def test_volume_retry_preserves_success_and_only_retries_failed_chunk():
    from scripts.menu_keyword_pipeline.repository import fetch_volumes
    calls=[];delays=[]
    def fetch(keys):
        calls.append(keys)
        if len(calls)==1: raise OSError('temporary')
        return {'keywordList':[{'relKeyword':k,'monthlyPcQcCnt':10,'monthlyMobileQcCnt':20} for k in keys]}
    period=dict(period_type='PROVIDER_MONTHLY',period_definition='test',period_start=None,period_end=None,period_verified=True)
    rows,attempts=fetch_volumes(['냉면','냉면','만두'],fetch,period,sleep=delays.append,clock=lambda:NOW)
    assert calls==[['냉면','만두'],['냉면','만두']]
    assert len(rows)==2 and all(r['total_count']==30 for r in rows)
    assert 60 in delays and 15 in delays


def test_permanent_volume_error_is_not_zero():
    from scripts.menu_keyword_pipeline.repository import fetch_volumes
    calls=[]
    def fail(keys): calls.append(keys);raise OSError('failed')
    period=dict(period_type='PROVIDER_MONTHLY',period_definition='test')
    rows,_=fetch_volumes(['냉면'],fail,period,sleep=lambda _:None,clock=lambda:NOW)
    assert len(calls)==3 and rows[0]['observation_status']=='FAILED' and rows[0]['total_count'] is None


def test_erp_mapping_change_is_not_reported_as_sales_loss(tmp_path):
    a=MemoryAdapter()
    original=a.read_sales
    state={'mapping_names':1}
    def sales(registry,now):
        data=original(registry,now)
        data['menu_mapping']=[dict(menu_code='M1',menu_name='물냉면',mapping_names=state['mapping_names'])]
        data['sales'][0]['mapping_names']=state['mapping_names']
        return data
    a.read_sales=sales
    execute(REG,tmp_path/'first',a,collect=True,clock=lambda:NOW)
    state['mapping_names']=2
    execute(REG,tmp_path/'second',a,collect=True,previous=tmp_path/'first',clock=lambda:NOW)
    diff=json.loads((tmp_path/'second'/'changes.json').read_text(encoding='utf-8'))
    assert diff['comparable_sales'] is False
    assert not any(r['change']=='NO_CONFIRMED_SALES' for r in diff['rows'])
    assert diff['status']=='SOURCE_MAPPING_CHANGED'


def test_store_identity_loss_is_not_reported_as_sales_loss(tmp_path):
    a=MemoryAdapter()
    execute(REG,tmp_path/'first',a,collect=True,clock=lambda:NOW)
    original=a.read_sales
    def lost(registry,now):
        data=original(registry,now)
        data['targets']=[];data['sales']=[]
        data['inventory'][0]['status']='LOCATION_MISSING'
        return data
    a.read_sales=lost
    execute(REG,tmp_path/'second',a,collect=True,previous=tmp_path/'first',clock=lambda:NOW)
    diff=json.loads((tmp_path/'second'/'changes.json').read_text(encoding='utf-8'))
    assert not diff['comparable_sales'] and diff['rows']==[] and diff['status']=='SOURCE_MAPPING_CHANGED'


def test_real_batch_adapter_does_not_collide_with_workflow_plan(tmp_path,monkeypatch):
    from scripts.menu_keyword_pipeline.repository import Adapter
    a=MemoryAdapter()
    adapter=Adapter(None,tmp_path/'absent.env')
    def collected(e,*args):
        a.ranks=[observation()]
        return dict(processed=len(e['collection_queue']),aborted=False,persistence_failures=0)
    monkeypatch.setattr('scripts.keyword_evaluation.collection.collect_ranks',collected)
    a.collect_rank=adapter.collect_rank
    out=execute(REG,tmp_path/'actual-batch',a,collect=True,clock=lambda:NOW)
    assert out['status']=='COMPLETE'
