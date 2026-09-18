"""외부 호출 없는 기간·판매·노출·변화 판정."""
from datetime import timedelta, timezone
from decimal import Decimal

from scripts.keyword_evaluation.collection import _reusable_rank
from scripts.keyword_evaluation.contracts import LIST_PROFILE, searchad_key, aware_time
from scripts.keyword_evaluation.sources import select_rank, latest, freshness


def window(now):
    end = now.astimezone(timezone(timedelta(hours=9))).date()
    return (end-timedelta(days=30)).isoformat(), end.isoformat()


def validate_registry(registry):
    if registry.get('version') != 1 or registry.get('brand') != 'hanchon':
        raise ValueError('지원 연결 목록: version=1, brand=hanchon')
    seen = set()
    for item in registry['candidates']:
        key = searchad_key(item['query'])
        if not key or key in seen or not item['pos_menu_names'] or len(set(item['pos_menu_names'])) != len(item['pos_menu_names']):
            raise ValueError('키워드 중복 또는 메뉴 연결 누락')
        seen.add(key)
    if not seen:
        raise ValueError('연결 목록이 비어 있습니다')
    for key in ('rank_ttl_days','volume_ttl_days'):
        if type(registry[key]) is not int or not 1 <= registry[key] <= 30:
            raise ValueError('유효기간은 1~30일 정수입니다')


def aggregate(targets, sales, mappings):
    wanted = {t['store_code'] for t in targets}
    known = {m for c in mappings for m in c['pos_menu_names']}
    totals, unmapped = {}, []
    for row in sales:
        if row['store_code'] not in wanted:
            continue
        if row['mapping_names'] != 1 or row['menu_name'] not in known:
            unmapped.append(dict(row, reason='AMBIGUOUS_MENU' if row['mapping_names'] != 1 else 'UNMAPPED_MENU'))
            continue
        key = (row['store_code'],row['menu_name'])
        a,q = totals.get(key,(Decimal(0),Decimal(0)))
        totals[key] = (a+Decimal(str(row['amount'])),q+Decimal(str(row['qty'])))
    pairs=[]
    for t in sorted(targets,key=lambda t:t['store_code']):
        for c in mappings:
            observed=[m for m in c['pos_menu_names'] if (t['store_code'],m) in totals]
            a=sum((totals[(t['store_code'],m)][0] for m in observed),Decimal(0))
            q=sum((totals[(t['store_code'],m)][1] for m in observed),Decimal(0))
            if a>0 and q>0:
                pairs.append(dict(store_code=t['store_code'],query=c['query'],amount=str(a),qty=str(q),menus=observed))
    return dict(pairs=pairs,unmapped=unmapped,keywords=sorted({p['query'] for p in pairs}))


def volume_for(volumes, query, now, days):
    v=latest([v for v in volumes if v['searchad_lookup_key']==searchad_key(query)],now,'fetched_at','volume_snapshot_id')
    if not v: return None,'MISSING'
    if not freshness(v,now,'fetched_at',days): return v,'STALE'
    if not v.get('period_verified'): return v,'UNVERIFIED'
    return v,v['observation_status']


def rank_input(targets,pairs,ranks,now,rules):
    bycode={t['store_code']:t for t in targets}
    return dict(input_manifest=dict(targets=targets,ranks=ranks,as_of_at=now.isoformat(),rank_profile=LIST_PROFILE),
                rules=dict(ttl_days=rules['rank_ttl_days']),
                collection_queue=[dict(candidate_id=p['store_code']+':'+p['query'],query=p['query'],target_place_id=bycode[p['store_code']]['place_id']) for p in pairs])


def evaluate(targets,pairs,volumes,ranks,now,rules):
    bycode={t['store_code']:t for t in targets}
    evaluated=rank_input(targets,pairs,ranks,now,rules)
    rows=[]
    for p in pairs:
        t=bycode[p['store_code']]
        v,vs=volume_for(volumes,p['query'],now,rules['volume_ttl_days'])
        r=select_rank(ranks,t,p['query'],now,profile=LIST_PROFILE)
        valid=_reusable_rank(evaluated,p,t)
        own=next((x['organic_rank'] for x in r['results'] if not x['is_ad'] and x['place_id']==t['place_id']),None) if valid else None
        rs='VALID' if valid else 'MISSING' if not r else 'STALE' if not freshness(r,now,'collected_at',rules['rank_ttl_days']) else r['collect_status'] if r['collect_status']!='SUCCESS' else 'INCOMPLETE'
        decision='HOLD' if not valid or vs!='EXACT' else 'EXPOSED' if own is not None else 'CANDIDATE'
        rows.append(dict(p,store_name=t['store_name'],place_id=t['place_id'],rank=own,rank_status=rs,
                         visibility='UNKNOWN' if not valid else 'OBSERVED' if own else 'NOT_IN_TOP20',
                         volume=v['total_count'] if vs=='EXACT' else None,volume_status=vs,
                         volume_interval=v.get('total_interval') if v else None,
                         rank_snapshot_id=r['snapshot_id'] if r else None,rank_at=r['collected_at'] if r else None,
                         volume_snapshot_id=v['volume_snapshot_id'] if v else None,volume_at=v['fetched_at'] if v else None,
                         decision=decision))
    return sorted(rows,key=lambda r:(r['store_code'],r['decision']!='CANDIDATE',-(r['volume'] or 0),-Decimal(r['qty']),r['query']))


def changes(current,previous,*,comparable_sales):
    old={(r['store_code'],r['query']):r for r in previous}
    new={(r['store_code'],r['query']):r for r in current}
    out=[]
    for key in sorted(old.keys()|new.keys()):
        a,b=old.get(key),new.get(key)
        if b is None:
            change='NO_CONFIRMED_SALES' if comparable_sales else 'HOLD'
        elif b['decision']=='HOLD': change='HOLD'
        elif a is None: change='NEW_CANDIDATE' if b['decision']=='CANDIDATE' else 'NEW_OBSERVATION'
        elif a['decision']!='CANDIDATE' and b['decision']=='CANDIDATE': change='NEW_CANDIDATE'
        elif a['decision']=='CANDIDATE' and b['decision']=='EXPOSED': change='NOW_EXPOSED'
        elif (a['rank'],a['volume'])!=(b['rank'],b['volume']): change='OBSERVATION_CHANGED'
        else: change='UNCHANGED'
        out.append(dict(store_code=key[0],query=key[1],change=change,
                        previous_decision=a['decision'] if a else None,current_decision=b['decision'] if b else None,
                        previous_rank=a['rank'] if a else None,rank=b['rank'] if b else None,
                        previous_volume=a['volume'] if a else None,volume=b['volume'] if b else None,
                        amount_delta=str(Decimal(b['amount'])-Decimal(a['amount'])) if comparable_sales and a and b else None,
                        qty_delta=str(Decimal(b['qty'])-Decimal(a['qty'])) if comparable_sales and a and b else None))
    return out
