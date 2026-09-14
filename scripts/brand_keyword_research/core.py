"""설정 검증 및 네트워크 없이 재현 가능한 비교 보고서."""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from scripts.keyword_evaluation.contracts import LIST_PROFILE, aware_time, keyword_key, searchad_key
from scripts.keyword_evaluation.collection import _reusable_rank
from scripts.keyword_evaluation.sources import latest, select_rank, freshness
from scripts.keyword_evaluation.store_location import validate_location
from scripts.keyword_evaluation.volume import validate_period


def validate_config(c):
    if c.get('version') != 1 or c.get('brand') != 'hanchon':
        raise ValueError('지원 설정: version=1, brand=hanchon')
    if type(c.get('ttl_days')) is not int or not 1 <= c['ttl_days'] <= 30:
        raise ValueError('ttl_days는 1~30 정수')
    candidates, targets = c.get('candidates', []), c.get('targets', [])
    scope = c.get('scope', 'CONFIGURED')
    if scope not in ('CONFIGURED', 'ALL_STORES'):
        raise ValueError('지원 조사 범위: CONFIGURED, ALL_STORES')
    if type(c.get('batch_size', 100)) is not int or not 1 <= c.get('batch_size', 100) <= 100:
        raise ValueError('배치 크기는 1~100 정수')
    if not 1 <= len(candidates) <= 20 or (scope == 'CONFIGURED' and (not targets or len(candidates)*len(targets) > 100)):
        raise ValueError('후보 1~20개, 순위 조사 최대 100건')
    for field, items in [('id', candidates), ('place_id', targets), ('target_store_id', targets)]:
        values = [r.get(field) for r in items]
        if any(not isinstance(v, str) or not v.strip() for v in values) or len(set(values)) != len(values):
            raise ValueError('식별자 누락 또는 중복: '+field)
    queries = [keyword_key(r['query']) for r in candidates]
    if any(not q for q in queries) or len(set(queries)) != len(queries):
        raise ValueError('검색어 누락 또는 중복')
    for r in candidates:
        if not r.get('evidence') or not r.get('condition'):
            raise ValueError('후보 근거와 적용 조건 필요')
        menus = r.get('pos_menu_names')
        if not isinstance(menus, list) or any(not isinstance(m, str) or not m.strip() for m in menus):
            raise ValueError('pos_menu_names는 메뉴명 목록; 미연결은 빈 목록')
        if len(set(menus)) != len(menus):
            raise ValueError('POS 메뉴명 중복')
    for t in targets:
        if not t.get('store_name'):
            raise ValueError('매장명 필요')
        location = t.get('search_location', {})
        validate_location(location, t['place_id'], aware_time(location['verified_at']))
    validate_period(c['volume_period'])
    if (c['volume_period'].get('period_type') != 'PROVIDER_MONTHLY'
            or c['volume_period'].get('period_start') is not None
            or c['volume_period'].get('period_end') is not None):
        raise ValueError('검색광고는 PROVIDER_MONTHLY만 지원하며 정확한 날짜를 지정할 수 없습니다')
    if c['volume_period'].get('period_verified') is not True:
        raise ValueError('검색량 기간 정의 검증 필요')


def period(latest_date, today, start=None, end=None):
    last = date.fromisoformat(str(latest_date)[:10])
    if bool(start) != bool(end):
        raise ValueError('기간 시작과 종료를 함께 지정')
    if start:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
    else:
        last = min(last, today-timedelta(days=1))
        if last.day == monthrange(last.year, last.month)[1]:
            a, b = last.replace(day=1), last+timedelta(days=1)
        else:
            b = last.replace(day=1)
            a = (b-timedelta(days=1)).replace(day=1)
    if a >= b or b > today or b > date.fromisoformat(str(latest_date)[:10])+timedelta(days=1) or (b-a).days > 93:
        raise ValueError('기간은 최신 자료까지 1~93일, 시작 포함·종료 미포함')
    return a.isoformat(), b.isoformat()


def rank_input(s):
    c = s['config']
    return {'input_manifest': {'targets': c['targets'], 'rank_profile': LIST_PROFILE,
                              'as_of_at': s['as_of_at'], 'ranks': s['ranks']},
            'rules': {'ttl_days': c['ttl_days']},
            'collection_queue': [dict(candidate_id=r['id']+':'+t['place_id'], query=r['query'],
                                      target_place_id=t['place_id'])
                                 for r in c['candidates'] for t in c['targets']]}


def analyze(s):
    c = s['config']; validate_config(c)
    as_of = aware_time(s['as_of_at']); evaluated = rank_input(s)
    for target in c['targets']:
        validate_location(target['search_location'], target['place_id'], as_of)
    sales = {r['menu_name']: r for r in s['sales']['rows']}
    rows, metrics = [], []
    for candidate in c['candidates']:
        query = candidate['query']; menus = candidate['pos_menu_names']
        matched = [sales[m] for m in menus if m in sales]
        sales_status = ('NOT_LINKED' if not menus else 'MISSING' if not matched else
                        'INCOMPLETE_MAPPING' if len(matched) != len(menus) else
                        'AMBIGUOUS_MAPPING' if any(r['mapping_names'] != 1 for r in matched) else 'OBSERVED')
        amount = str(sum(Decimal(r['amount']) for r in matched)) if sales_status == 'OBSERVED' else None
        volume = latest([v for v in s['volumes'] if v['searchad_lookup_key'] == searchad_key(query)
                         and v['provider'] == 'NAVER_SEARCHAD'], as_of, 'fetched_at', 'volume_snapshot_id')
        vs = 'MISSING' if volume is None else volume['observation_status']
        if volume and not freshness(volume, as_of, 'fetched_at', c['ttl_days']): vs = 'STALE'
        if volume and not volume.get('period_verified'): vs = 'UNVERIFIED'
        metrics.append(dict(candidate_id=candidate['id'], query=query, sales_amount=amount,
                            sales_status=sales_status, volume_status=vs,
                            volume_total=volume.get('total_count') if volume else None,
                            volume_pc=volume.get('pc_count') if volume else None,
                            volume_mobile=volume.get('mobile_count') if volume else None,
                            volume_interval=volume.get('total_interval') if volume else None,
                            volume_at=volume['fetched_at'] if volume else None,
                            volume_snapshot_id=volume['volume_snapshot_id'] if volume else None))
        for target in c['targets']:
            rank = select_rank(s['ranks'], target, query, as_of, profile=LIST_PROFILE)
            valid = _reusable_rank(evaluated, {'query': query}, target)
            status = 'VALID' if valid else rank['collect_status'] if rank else 'MISSING'
            if rank and not freshness(rank, as_of, 'collected_at', c['ttl_days']): status = 'STALE'
            elif rank and status == 'SUCCESS': status = 'INCOMPLETE'
            organic = [r for r in rank['results'] if not r['is_ad']] if valid else []
            own = next((r['organic_rank'] for r in organic if r['place_id'] == target['place_id']), None)
            visibility = ('OBSERVED' if own else 'NOT_IN_TOP20' if len(organic) >= 20 else
                          'NOT_OBSERVED_IN_COMPLETE_LIST' if valid else 'UNKNOWN')
            rows.append(dict(candidate_id=candidate['id'], query=query, store_name=target['store_name'],
                             place_id=target['place_id'], store_code=target.get('store_code'),
                             target_store_id=target['target_store_id'], sales_amount=amount, sales_status=sales_status,
                             sales_menus=matched, volume_status=vs,
                             volume_total=volume.get('total_count') if volume else None,
                             volume_interval=volume.get('total_interval') if volume else None,
                             volume_at=volume['fetched_at'] if volume else None,
                             volume_snapshot_id=volume['volume_snapshot_id'] if volume else None,
                             rank_status=status, visibility=visibility, own_rank=own,
                             rank_snapshot_id=rank['snapshot_id'] if rank else None,
                             rank_at=rank['collected_at'] if rank else None,
                             competitors=[r for r in organic[:10] if r['place_id'] not in s['own_place_ids']],
                             evidence=candidate['evidence'], condition=candidate['condition']))
    missing = sum(r['rank_status'] != 'VALID' or r['volume_status'] not in ('EXACT', 'CENSORED', 'NOT_PROVIDED')
                  or r['sales_status'] not in ('OBSERVED', 'NOT_LINKED') for r in rows)
    result = {'rows': rows, 'candidates': metrics, 'incomplete_rows': missing, 'warnings': list(s['sales']['warnings'])}
    from .summary import summarize
    result['keyword_summary'] = summarize(s, result)
    if 'inventory' in s:
        result['excluded_stores'] = sum(t['status'] != 'ELIGIBLE' for t in s['inventory'])
        if not s['inventory']:
            result['warnings'].append('운영 매장 모집단이 비어 있다. 전체 매장 조회 조건과 원천을 확인하세요.')
    return result


def cell(value):
    return str(value).replace('|', '／').replace('\r', ' ').replace('\n', ' ')


def report(s, result):
    sales = s['sales']
    lines = ['# 브랜드 키워드 반복 조사 보고서', '', f"기준 시각: {s['as_of_at']}",
             f"매출 기간: {sales['start']} 이상 ~ {sales['end']} 미만 / 원천 최신일: {sales['latest_date']}",
             f"POS 관측 매장: {sales.get('stores', '미확인')}개 / 관측 날짜: {sales.get('days', '미확인')}일", '',
             '검토된 후보의 비교 자료다. 자동 추천·등록·유입 증가 검증 결과가 아니다. 매출은 SC_AMT_TTL 합계이며 회계 확정 순매출·이익이 아니다.',
             ('POS 매출은 브랜드 관측 범위, 순위는 ERP 운영 매장 중 ID·좌표가 확인된 매장 기준이다.'
              if s['config'].get('scope') == 'ALL_STORES' else 'POS 매출은 브랜드 관측 범위, 순위는 설정된 표본 매장 좌표 기준이다.')
             + ' 각 매장의 실제 메뉴 판매를 보장하지 않는다.', '',
             '## 후보 비교', '', '| 검색어 | POS 금액 | 검색량 / 상태 | 자사 TOP10 | TOP20 | 미확인 매장 | 적용 조건 |',
             '|---|---:|---|---:|---:|---:|---|']
    for candidate in s['config']['candidates']:
        rows = [r for r in result['rows'] if r['candidate_id'] == candidate['id']]
        r = next(m for m in result['candidates'] if m['candidate_id'] == candidate['id'])
        valid = [x for x in rows if x['rank_status'] == 'VALID']
        a = sum(x['own_rank'] is not None and x['own_rank'] <= 10 for x in valid)
        b = sum(x['own_rank'] is not None and x['own_rank'] <= 20 for x in valid)
        summary = next(x for x in result['keyword_summary'] if x['candidate_id'] == candidate['id'])
        volume = f"{r['volume_total']:,}" if r['volume_status'] == 'EXACT' else '~'.join(map(str,r['volume_interval'])) if r['volume_status'] == 'CENSORED' and r['volume_interval'] else '미확인'
        lines.append('| '+' | '.join(map(cell, [candidate['query'], f"{Decimal(r['sales_amount']):,.0f}원" if r['sales_amount'] is not None else r['sales_status'],
                     volume+' / '+r['volume_status'], f'{a}/{len(valid)}' if valid else '산정 불가',
                     f'{b}/{len(valid)}' if valid else '산정 불가', summary['unknown_stores'], candidate['condition']]))+' |')
    from .summary import summary_markdown
    lines += ['', summary_markdown(result['keyword_summary'])]
    if 'inventory' in s:
        lines += ['## 전체 매장 명단과 조사 가능 여부', '',
                  f"모집단 조회 시각: {s.get('inventory_as_of', s['as_of_at'])}", '',
                  '| 매장 코드 | 매장 | Place ID | 조사 상태 |', '|---|---|---|---|']
        for item in s['inventory']:
            lines.append('| '+' | '.join(map(cell, [item['store_code'], item['store_name'], item['place_id'] or '없음', item['status']]))+' |')
    lines += ['', 'TOP10·TOP20 분모는 유효하게 수집된 매장 수다. 검색량은 최근 한 달 검색광고 도구 값으로 식당 방문 수가 아니며, 구간값·자료 없음·미노출을 0으로 치환하지 않는다.', '',
              '## 매장별 관측', '', '| 검색어 | 매장 | 자사 순위 / 판정 | 상태 | 순위 시각 | 검색량 시각 |', '|---|---|---|---|---|---|']
    for r in result['rows']:
        lines.append('| '+' | '.join(map(cell, [r['query'], r['store_name'], r['own_rank'] or r['visibility'],
                     r['rank_status'], r['rank_at'] or '없음', r['volume_at'] or '없음']))+' |')
    lines += ['', '## 후보 근거와 매출 연결', '']
    for candidate in s['config']['candidates']:
        lines.append(f"- {cell(candidate['query'])}: {cell(candidate['evidence'])}. POS 연결: {cell(', '.join(candidate['pos_menu_names']) or '없음')}.")
    lines += ['', '| POS 메뉴 | 금액 | 관측 매장 수 | 관측 날짜 수 |', '|---|---:|---:|---:|']
    menus = {m for c in s['config']['candidates'] for m in c['pos_menu_names']}
    for r in sales['rows']:
        if r['menu_name'] in menus:
            lines.append('| '+' | '.join(map(cell,[r['menu_name'], f"{Decimal(r['amount']):,.0f}원", r.get('stores','미확인'),r.get('days','미확인')]))+' |')
    lines += ['', '여러 메뉴명을 연결한 금액은 합산한다. 판매 매장·관측일수는 중복될 수 있어 합산하지 않으며 원자료 JSON에 메뉴별로 보존한다. 세트·사이즈를 자동 병합하지 않는다.', '',
              '## 상위 노출 경쟁점', '', '| 검색어 | 조회 매장 | 일반 TOP10 타 브랜드 매장 |', '|---|---|---|']
    for r in result['rows']:
        names = ', '.join(f"{p['organic_rank']}위 {p['place_name']}" for p in r['competitors'])
        lines.append(f"| {cell(r['query'])} | {cell(r['store_name'])} | {cell(names or ('확인 불충분' if r['rank_status'] != 'VALID' else '없음'))} |")
    lines += ['', '## 자료 한계', '', '- 순위는 매장별 좌표·모바일 플레이스 목록·일반 TOP20 기준이다. 광고를 제외하며 거리는 점수화하지 않는다.',
              '- 수집 시각이 다르므로 동일 시점의 통제 비교가 아니다. 오래된 관측·부분 수집은 유효 순위로 쓰지 않는다.',
              '- 신규 경쟁점 keywordList 보강, 매출 원인·수익성 분석, 자동 후보 선정, 스마트플레이스 유입 효과 검증은 이번 기능에 포함하지 않는다.']
    lines += ['- '+cell(w) for w in result['warnings']]
    return '\n'.join(lines)+'\n'
