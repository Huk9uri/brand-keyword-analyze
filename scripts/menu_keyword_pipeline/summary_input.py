"""저장된 자료로 매장별 비교 입력을 구성한다. 외부 조회나 후보 재판정은 하지 않는다."""
import json
from collections import defaultdict


def pick(row,keys):
    return {k:row[k] for k in keys if k in row}


def enrich(root,rows,quality,changes,store_code=None):
    sources={}
    def optional(name,default):
        path=root/name
        sources[name]='AVAILABLE' if path.exists() else 'MISSING'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
    registry=optional('registry.json',{})
    sales=optional('sales.json',{})
    unmapped=optional('unmapped-menus.json',[])
    observations=optional('observations.json',{})
    mappings={x['query']:pick(x,('pos_menu_names','condition')) for x in registry.get('candidates',[])}
    rank_results={str(x['snapshot_id']):x.get('results',[]) for x in observations.get('ranks',[])}
    daily_quality={x['store_code']:x for x in quality.get('stores',[])}
    change_rows={(x['store_code'],x['query']):x for x in changes.get('rows',[])}
    menu_sales=defaultdict(list)
    for r in sales.get('sales',[]):
        if r.get('mapping_names')==1:
            menu_sales[(r['store_code'],r['menu_name'])].append(pick(r,('menu_code','menu_name','amount','qty')))
    unlinked=defaultdict(list)
    for r in unmapped:
        unlinked[r['store_code']].append(pick(r,('menu_code','menu_name','mapping_names','amount','qty','reason')))
    identities={}
    for r in [*sales.get('inventory',[]),*sales.get('targets',[]),*sales.get('blocked_stores',[]),*rows]:
        code=r['store_code']
        identities.setdefault(code,{}).update(pick(r,('store_code','store_name','place_id','status','reason','search_location')))
    if store_code is not None and store_code not in identities:raise ValueError('UNKNOWN_STORE')
    bystore=defaultdict(list)
    for r in rows:bystore[r['store_code']].append(r)
    stores=[];facts={}
    for code in sorted(identities):
        if store_code is not None and code!=store_code:continue
        keywords=[]
        for r in bystore[code]:
            item=dict(r)
            item['fact_id']='P:'+code+':'+r['query']
            item['mapping']=mappings.get(r['query'])
            item['menu_sales']=[x for name in r.get('menus',[]) for x in menu_sales[(code,name)]] if sources['sales.json']=='AVAILABLE' else None
            item['hold_reasons']=[]
            if r['decision']=='HOLD':
                if r.get('rank_status')!='VALID':item['hold_reasons'].append('RANK_'+str(r.get('rank_status','UNKNOWN')))
                if r.get('volume_status')!='EXACT':item['hold_reasons'].append('VOLUME_'+str(r.get('volume_status','UNKNOWN')))
            snapshot=str(r.get('rank_snapshot_id'))
            item['search_results']=[pick(x,('place_id','place_name','category','organic_rank')) for x in rank_results[snapshot]
                                    if not x.get('is_ad') and x.get('organic_rank') is not None] if snapshot in rank_results else None
            item['search_results_usable']=r.get('rank_status')=='VALID' and item['search_results'] is not None
            item['change']=change_rows.get((code,r['query']))
            facts[item['fact_id']]=f"{code} {r['store_name']} — {r['query']}: 기간 매출 {r['amount']}원, POS 수량 {r['qty']}, 전국 검색량 {r.get('volume')}, 판정 {r['decision']}, 순위 {r.get('rank')}, 노출 상태 {r.get('visibility','UNKNOWN')}."
            keywords.append(item)
        stores.append(dict(**identities[code],quality=daily_quality.get(code),keywords=keywords,
                           unmapped_menus=unlinked[code] if sources['unmapped-menus.json']=='AVAILABLE' else None))
    selected={s['store_code'] for s in stores}
    comparison=pick(changes,('status','comparable_sales','same_registry','same_source_mapping','note'))
    comparison['rows']=[r for r in changes.get('rows',[]) if r['store_code'] in selected]
    return dict(stores=stores,sources=sources,comparison=comparison,
                quality=pick(quality,('start','end','status','comparable','note','latest_observed_in_window','global_missing_dates')),
                definitions=dict(volume='전국 월간 검색광고 지표, 지역 수요 아님',rank='모바일 플레이스 광고 제외 상위 20위',
                    null_rank='유효 관측의 미노출인지 관측 실패인지 visibility와 rank_status로 구분',
                    menu_overlap='같은 POS 메뉴가 여러 키워드에 연결될 수 있음. 매출·수량·검색량 중복 합산 금지',
                    missing_dates='관측 공백이며 휴무·적재 지연·판매 없음 중 원인 확정 불가',
                    unavailable='지역 검색량·실제 유입·클릭·전환 데이터는 제공되지 않음'),
                scope=dict(type='STORE',store_code=store_code) if store_code else dict(type='ALL_STORES')),facts
