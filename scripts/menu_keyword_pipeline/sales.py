"""POS 코드 재사용과 기간별 관측 공백을 보존하는 매장 매출 연결."""
from collections import defaultdict
from datetime import date,timedelta
from decimal import Decimal


def prepare_sales(targets,mappings,menu_rows,daily_rows,menu_mapping,start,end):
    for field in ('amount','qty'):
        if sum((Decimal(str(r[field] or 0)) for r in menu_rows),Decimal(0)) != sum((Decimal(str(r[field] or 0)) for r in daily_rows),Decimal(0)):
            raise ValueError('POS_TOTAL_MISMATCH')
    def active(r):
        opened=str(r.get('opened') or '').strip().replace('-','')[:8]
        closed=str(r.get('closed') or '').strip().replace('-','')[:8]
        return (not opened or opened<end.replace('-','')) and (not closed or closed>=start.replace('-',''))
    pos_owners=defaultdict(set);bycode=defaultdict(set)
    for r in mappings:
        pos=(r.get('pos_code') or '').strip()
        if pos and active(r):
            pos_owners[pos].add(r['store_code']);bycode[r['store_code']].add(pos)
    codes={};blocked=[]
    for t in targets:
        opts=bycode[t['store_code']]
        reason='POS_CODE_MISSING' if not opts else 'AMBIGUOUS_POS_CODE' if len(opts)!=1 or any(len(pos_owners[p])!=1 for p in opts) else None
        if reason: blocked.append(dict(store_code=t['store_code'],store_name=t['store_name'],reason=reason))
        else: codes[next(iter(opts))]=t['store_code']
    names={r['menu_code']:r for r in menu_mapping}
    sales=[]
    for row in menu_rows:
        if row['pos_code'] not in codes: continue
        m=names.get(row['menu_code'],{})
        sales.append(dict(store_code=codes[row['pos_code']],menu_code=row['menu_code'],menu_name=m.get('menu_name') or row['menu_code'],
                          mapping_names=m.get('mapping_names',0),amount=str(row['amount'] or 0),qty=str(row['qty'] or 0)))
    expected={(date.fromisoformat(start)+timedelta(days=i)).isoformat() for i in range((date.fromisoformat(end)-date.fromisoformat(start)).days)}
    days=defaultdict(set)
    for r in daily_rows:
        if r['pos_code'] in codes: days[codes[r['pos_code']]].add(str(r['sale_date'])[:10])
    all_days=set().union(*days.values()) if days else set()
    per_store=[dict(store_code=code,observed_days=len(days[code]),latest_observed=max(days[code],default=None),missing_dates=sorted(expected-days[code])) for code in sorted(codes.values())]
    gaps=sorted(expected-all_days)
    comparable=bool(per_store) and not blocked and not any(s['missing_dates'] for s in per_store)
    quality=dict(start=start,end=end,latest_observed_in_window=max(all_days,default=None),global_missing_dates=gaps,
                 stores=per_store,comparable=comparable,status='OBSERVED' if comparable else 'REVIEW_REQUIRED',
                 note='기록 공백은 적재 지연·휴무·무매출을 구분하지 못합니다. 완전 적재를 보증하지 않습니다. 공백이 있으면 매출 증감 계산을 보류합니다.')
    return dict(sales=sales,blocked_stores=blocked,quality=quality)
