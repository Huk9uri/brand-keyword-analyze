"""한촌 전용 읽기 어댑터와 기존 수집기 연결. SQL 식별자는 입력받지 않는다."""
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from scripts.keyword_evaluation.contracts import LIST_PROFILE, searchad_key, keyword_key
from scripts.keyword_evaluation.volume import parse_volume
from .core import period, analyze, rank_input


SALES_SQL = """
WITH mapping AS (
 SELECT c.CD_STMENU,MIN(b.NM_ITEM) menu_name,COUNT(DISTINCT b.NM_ITEM) names
 FROM SEIERP_IYN_BAK.dbo.FRMI_MENULINKCODE c
 JOIN SEIERP_IYN_BAK.dbo.BSIT_ITEM b ON b.CD_CORP=c.CD_CORP AND b.CD_SYSITEM=c.CD_SYSITEM
 WHERE c.CD_CORP='01' GROUP BY c.CD_STMENU
)
SELECT COALESCE(m.menu_name,p.CMDT_CD) menu_name,MAX(COALESCE(m.names,0)) mapping_names,
 SUM(p.SC_AMT_TTL) amount,SUM(p.SC_QTY) qty,COUNT(DISTINCT p.STR_NO) stores,
 COUNT(DISTINCT p.SDA_DT) days,COUNT_BIG(*) rows_count
FROM SKYPOS.dbo.prep_매출뷰 p LEFT JOIN mapping m ON m.CD_STMENU=p.CMDT_CD
WHERE p.BRD_CD='HC1001' AND p.gubun='01' AND p.SDA_DT >= %s AND p.SDA_DT < %s
GROUP BY COALESCE(m.menu_name,p.CMDT_CD)
"""


def iso(value):
    # V4 수집기와 검색광고 저장소가 UTC로 기록한 datetime2 값만 읽는다.
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


class Repository:
    def __init__(self, connection, env_file):
        self.connection, self.env_file = connection, env_file
        self.sales_cache = None

    def query(self, sql, params=()):
        cursor = self.connection.cursor(as_dict=True)
        try:
            cursor.execute(sql, params)
            return list(cursor.fetchall())
        finally:
            cursor.close()

    def sales(self, start, end, today):
        if self.sales_cache is not None:
            return self.sales_cache
        last = self.query("SELECT MAX(SDA_DT) latest FROM SKYPOS.dbo.T_POS_SALE_CMDT WHERE BRD_CD='HC1001' AND gubun='01'")[0]['latest']
        if last is None:
            raise ValueError('POS_DATA_MISSING')
        start, end = period(last.date().isoformat(), today, start, end)
        totals = self.query("""SELECT SUM(SC_AMT_TTL) amount,COUNT_BIG(*) rows_count,
            COUNT(DISTINCT STR_NO) stores,COUNT(DISTINCT SDA_DT) days
            FROM SKYPOS.dbo.prep_매출뷰 WHERE BRD_CD='HC1001' AND gubun='01'
            AND SDA_DT >= %s AND SDA_DT < %s""", (start, end))[0]
        rows = self.query(SALES_SQL, (start, end))
        amount = totals['amount'] or Decimal(0)
        if sum((r['amount'] or Decimal(0) for r in rows), Decimal(0)) != amount or sum(r['rows_count'] for r in rows) != totals['rows_count']:
            raise ValueError('SALES_JOIN_TOTAL_MISMATCH')
        warnings = []
        if (today-last.date()).days > 7:
            warnings.append('POS 최신 자료가 7일 이상 지연됐다. 현재 매출로 해석하지 않는다.')
        from datetime import date
        if totals['days'] != (date.fromisoformat(end)-date.fromisoformat(start)).days:
            warnings.append('브랜드 매출 관측 날짜에 공백이 있다. 매장별 완전성은 별도 검증 필요.')
        if not rows: warnings.append('선택 기간 POS 기록이 없다.')
        for r in rows:
            r['amount'] = str(r['amount']) if r['amount'] is not None else '0'
            r['qty'] = str(r['qty']) if r['qty'] is not None else None
        self.sales_cache = dict(start=start, end=end, latest_date=last.date().isoformat(),
                               total_amount=str(amount), row_count=totals['rows_count'],
                               stores=totals['stores'], days=totals['days'], rows=rows,
                               join_verified=True, warnings=warnings)
        return self.sales_cache

    def read(self, config, start=None, end=None):
        now = datetime.now(timezone.utc)
        stores = self.query("""SELECT NAVER_PLACE_ID FROM dbo.vw_naver_store_hours_targets
                               WHERE BRAND_CODE=N'001' AND PLACE_ID_STATUS=N'CONSISTENT'""")
        own = sorted({s['NAVER_PLACE_ID'] for s in stores if s['NAVER_PLACE_ID']})
        if any(t['place_id'] not in own for t in config['targets']):
            raise ValueError('TARGET_BRAND_IDENTITY_MISMATCH')
        sales = self.sales(start, end, now.astimezone(timezone(timedelta(hours=9))).date())
        volumes, ranks = [], []
        for key in dict.fromkeys(searchad_key(c['query']) for c in config['candidates']):
            vs = self.query("""SELECT TOP 1 * FROM dbo.naver_keyword_search_volume_snapshot
                WHERE provider='NAVER_SEARCHAD' AND searchad_lookup_key=%s AND fetched_at<=%s
                ORDER BY fetched_at DESC,volume_snapshot_id DESC""", (key, now.replace(tzinfo=None)))
            if not vs: continue
            v = vs[0]
            payload = json.loads(v['response_json']) if v['response_json'] else {}
            parsed = parse_volume(key, payload)
            if v['observation_status'] in ('EXACT', 'CENSORED', 'NOT_PROVIDED'):
                if any(parsed[k] != v[k] for k in ('observation_status', 'pc_count', 'mobile_count', 'total_count')):
                    raise ValueError('VOLUME_DB_RESPONSE_MISMATCH')
            volumes.append(dict(volume_snapshot_id=v['volume_snapshot_id'], provider=v['provider'],
                                searchad_lookup_key=key, fetched_at=iso(v['fetched_at']),
                                observation_status=v['observation_status'], total_count=v['total_count'],
                                total_interval=parsed.get('total_interval'), response_json=payload,
                                period_verified=(v['period_type']==config['volume_period']['period_type']
                                                 and v['period_definition']==config['volume_period']['period_definition']
                                                 and v['period_start'] is None and v['period_end'] is None)))
        for t in config['targets']:
            for candidate in config['candidates']:
                location = t['search_location']
                rs = self.query("""SELECT TOP 1 snapshot_id,run_id,target_store_id,normalized_query,device_type,
                    collect_status,collected_at,result_end_reached,latitude,longitude
                    FROM dbo.naver_keyword_discovery_snapshot WHERE target_store_id=%s AND normalized_query=%s
                    AND device_type='MOBILE' AND location_name=%s AND ROUND(latitude,7)=ROUND(%s,7)
                    AND ROUND(longitude,7)=ROUND(%s,7) AND collected_at<=%s
                    ORDER BY collected_at DESC,snapshot_id DESC""",
                    (t['target_store_id'], keyword_key(candidate['query']), LIST_PROFILE, location['latitude'],
                     location['longitude'], now.replace(tzinfo=None)))
                if not rs: continue
                r = rs[0]; r['run_id'] = str(r['run_id']); r['collected_at'] = iso(r['collected_at'])
                r['profile'] = LIST_PROFILE
                r['search_location'] = dict(location, latitude=float(r.pop('latitude')), longitude=float(r.pop('longitude')))
                r['results'] = self.query("""SELECT raw_position,organic_rank,place_id,place_name,category,is_ad
                    FROM dbo.naver_keyword_discovery_result WHERE snapshot_id=%s ORDER BY raw_position""", (r['snapshot_id'],))
                ranks.append(r)
        return dict(config=config, as_of_at=now.isoformat(), sales=sales, volumes=volumes, ranks=ranks, own_place_ids=own)

    def collect(self, state, root):
        from scripts.keyword_evaluation.cli import _write
        from scripts.keyword_evaluation.collection import collect_volumes, collect_ranks, build_rank_tasks
        from scripts.keyword_evaluation.repository import VolumeRepository
        from scripts.keyword_discovery_rank.config import _parse_bool, _parse_positive_int
        from types import SimpleNamespace
        from scripts.yuksudang_volume.config import NaverConfig
        from scripts.yuksudang_volume.searchad import SearchAdClient
        from dotenv import dotenv_values
        needed = list(dict.fromkeys(r['query'] for r in analyze(state)['rows']
                      if r['volume_status'] not in ('EXACT', 'CENSORED', 'NOT_PROVIDED')))
        if needed:
            env = dotenv_values(self.env_file)
            client = SearchAdClient(NaverConfig(env['NAVER_SEARCHAD_CUSTOMER_ID'], env['NAVER_SEARCHAD_API_KEY'], env['NAVER_SEARCHAD_SECRET_KEY'], '', ''))
            obs = collect_volumes(needed, client._request, state['config']['volume_period'])
            _write(root/'volume-observations.json', obs)
            _write(root/'volume-receipt.json', VolumeRepository(self.connection).save(obs))
        evaluated = rank_input(state)
        tasks = build_rank_tasks(evaluated)
        _write(root/'rank-plan.json', [dict(query=t.query, target_store_id=t.target_store_id,
                                           latitude=t.latitude, longitude=t.longitude) for t in tasks])
        print(f'신규 순위 조사 {len(tasks)}건', flush=True)
        if not tasks:
            return dict(aborted=False, processed=0, persistence_failures=0, reused=True)
        env = dotenv_values(self.env_file)
        browser_config = SimpleNamespace(
            headless=_parse_bool(env.get('KEYWORD_DISCOVERY_HEADLESS') or 'true', 'HEADLESS'),
            timeout_seconds=_parse_positive_int(env.get('KEYWORD_DISCOVERY_TIMEOUT_SECONDS') or '30', 'TIMEOUT'))
        receipt = collect_ranks(evaluated, self.connection, browser_config, root/'artifacts')
        _write(root/'rank-receipt.json', receipt)
        return receipt
