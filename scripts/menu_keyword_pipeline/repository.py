"""한촌 POS 읽기 및 기존 네이버 수집 어댑터. 새 DB 스키마는 만들지 않는다."""
import json
import time
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from dotenv import dotenv_values
from scripts.brand_keyword_research.repository import Repository,iso
from scripts.brand_keyword_research.batch_collection import collect_in_batches
from scripts.keyword_evaluation.collection import collect_volumes
from scripts.keyword_evaluation.repository import VolumeRepository
from scripts.keyword_evaluation.contracts import searchad_key
from scripts.keyword_evaluation.volume import parse_volume
from .core import window
from .sales import prepare_sales


POS_SQL="""
SELECT LTRIM(RTRIM(STR_NO)) pos_code,
       CASE WHEN GROUPING(CMDT_CD)=0 THEN 'MENU' ELSE 'DAY' END row_kind,
       CMDT_CD menu_code, CONVERT(varchar(10),SDA_DT,23) sale_date,
       SUM(SC_AMT_TTL) amount,SUM(SC_QTY) qty
FROM SKYPOS.dbo.prep_매출뷰
WHERE BRD_CD='HC1001' AND gubun='01' AND SDA_DT >= %s AND SDA_DT < %s
GROUP BY GROUPING SETS ((STR_NO,CMDT_CD),(STR_NO,SDA_DT))
"""
STORE_MAP_SQL="""
SELECT LTRIM(RTRIM(CD_STORE)) store_code,LTRIM(RTRIM(NO_POSCONNCODE)) pos_code,
       DT_OPEN opened,DT_CLOSE closed
FROM SEIERP_IYN_BAK.dbo.FROP_STORE WHERE CD_CORP='01' AND CD_BRAND='001'
"""
MENU_MAP_SQL="""
SELECT c.CD_STMENU menu_code,MIN(b.NM_ITEM) menu_name,COUNT(DISTINCT b.NM_ITEM) mapping_names
FROM SEIERP_IYN_BAK.dbo.FRMI_MENULINKCODE c
JOIN SEIERP_IYN_BAK.dbo.BSIT_ITEM b ON b.CD_CORP=c.CD_CORP AND b.CD_SYSITEM=c.CD_SYSITEM
WHERE c.CD_CORP='01' GROUP BY c.CD_STMENU
"""


def fetch_volumes(keywords,fetch,period,*,sleep=time.sleep,clock=lambda:datetime.now(timezone.utc)):
    """중복 제거, 청크 간 간격, 재시도. 실패값도 보존하며 0으로 대체하지 않는다."""
    pending=list(dict.fromkeys(searchad_key(k) for k in keywords)); final={};attempts=[];calls=0
    for attempt in range(3):
        if not pending: break
        if attempt: sleep(60*2**(attempt-1))
        retry=[]
        for offset in range(0,len(pending),5):
            if calls: sleep(15)
            chunk=pending[offset:offset+5];calls+=1
            obs=collect_volumes(chunk,fetch,period,clock=clock)
            for row in obs:
                key=row['searchad_lookup_key'];final[key]=row
                attempts.append(dict(query=key,attempt=attempt+1,status=row['observation_status']))
                if row['observation_status'] in ('FAILED','INVALID'): retry.append(key)
        pending=retry
    return list(final.values()),attempts


class Adapter:
    def __init__(self,connection,env_file):
        self.connection=connection;self.env_file=Path(env_file)
        self.repo=Repository(connection,self.env_file)

    def read_sales(self,registry,now):
        config,inventory=self.repo.prepare(dict(registry,scope='ALL_STORES'),collect=False)
        start,end=window(now)
        raw=self.repo.query(POS_SQL,(start,end))
        menus=[r for r in raw if r['row_kind']=='MENU'];daily=[r for r in raw if r['row_kind']=='DAY']
        mappings=self.repo.query(STORE_MAP_SQL);menu_mapping=self.repo.query(MENU_MAP_SQL)
        result=prepare_sales(config['targets'],mappings,menus,daily,menu_mapping,start,end)
        blocked={r['store_code'] for r in result['blocked_stores']}
        return dict(result,targets=[t for t in config['targets'] if t['store_code'] not in blocked],inventory=inventory,
                    source_queried_at=datetime.now(timezone.utc).isoformat(),pos_daily=daily,
                    pos_menu_totals=menus,store_mapping=mappings,menu_mapping=menu_mapping)

    def observations(self,targets,keywords,registry,now):
        volumes=[]
        period=registry['volume_period']
        for query in keywords:
            key=searchad_key(query)
            rows=self.repo.query("""SELECT TOP 1 * FROM dbo.naver_keyword_search_volume_snapshot
                WHERE provider='NAVER_SEARCHAD' AND searchad_lookup_key=%s AND fetched_at<=%s
                ORDER BY fetched_at DESC,volume_snapshot_id DESC""",(key,now.replace(tzinfo=None)))
            if not rows: continue
            v=rows[0];parsed=parse_volume(key,json.loads(v['response_json']) if v['response_json'] else {})
            consistent=all(parsed[k]==v[k] for k in ('observation_status','pc_count','mobile_count','total_count'))
            verified=(v['period_type']==period['period_type'] and v['period_definition']==period['period_definition']
                      and v['period_start'] is None and v['period_end'] is None)
            volumes.append(dict(volume_snapshot_id=v['volume_snapshot_id'],searchad_lookup_key=key,
                                observation_status=v['observation_status'] if consistent or v['observation_status']=='FAILED' else 'INVALID',
                                total_count=v['total_count'],total_interval=parsed.get('total_interval'),fetched_at=iso(v['fetched_at']),period_verified=verified))
        config=dict(targets=targets,candidates=[dict(query=q) for q in keywords])
        return volumes,self.repo.rank_observations(config,now)

    def collect_volume(self,keywords,registry):
        from scripts.yuksudang_volume.config import NaverConfig
        from scripts.yuksudang_volume.searchad import SearchAdClient
        env=dotenv_values(self.env_file)
        client=SearchAdClient(NaverConfig(env['NAVER_SEARCHAD_CUSTOMER_ID'],env['NAVER_SEARCHAD_API_KEY'],env['NAVER_SEARCHAD_SECRET_KEY'],'',''))
        rows,attempts=fetch_volumes(keywords,client._request,registry['volume_period'])
        receipt=VolumeRepository(self.connection).save(rows)
        return dict(receipt,attempts=attempts,saved=len(rows))

    def collect_rank(self,evaluated,root):
        env=dotenv_values(self.env_file)
        config=SimpleNamespace(headless=str(env.get('KEYWORD_DISCOVERY_HEADLESS') or 'true').lower() in ('true','1','yes'),
                               timeout_seconds=int(env.get('KEYWORD_DISCOVERY_TIMEOUT_SECONDS') or 30))
        collection_root=root/'rank-collection'
        collection_root.mkdir()
        return collect_in_batches(evaluated,self.connection,config,collection_root,batch_size=50,
                                  group_key=lambda row: row['target_place_id'])
