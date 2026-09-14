"""전체 모집단 기준 키워드 집계와 안전한 CSV 출력."""
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median


def _population(state):
    if 'inventory' in state:
        return state['inventory']
    return [dict(t, status='ELIGIBLE') for t in state['config']['targets']]


def _pct(numerator, denominator):
    return numerator * 100 / denominator if denominator else None


def summarize(state, result):
    """미확인은 비노출로 치환하지 않고 전체 모집단에 남긴다."""
    inventory = _population(state)
    eligible = [t for t in inventory if t.get('status') == 'ELIGIBLE']
    candidates = result.get('candidates')
    if candidates is None:
        candidates = [dict(next((r for r in result['rows'] if r['candidate_id'] == c['id']), {}),
                           candidate_id=c['id'], query=c['query']) for c in state['config']['candidates']]
    summaries = []
    for candidate in candidates:
        rows = {r['place_id']: r for r in result['rows'] if r['candidate_id'] == candidate['candidate_id']}
        counts = Counter()
        ranks = []
        valid = 0
        bands = dict(top3=0, rank4_10=0, rank11_20=0, not_in_top20=0, unknown=0)
        for target in inventory:
            if target.get('status') != 'ELIGIBLE':
                counts[target.get('status', 'EXCLUDED')] += 1
                continue
            row = rows.get(target.get('place_id'), {})
            status = row.get('rank_status', 'MISSING')
            rank = row.get('own_rank')
            if status == 'VALID' and rank is not None and (type(rank) is not int or rank < 1):
                status = 'INVALID_RANK'
            counts[status] += 1
            if status != 'VALID':
                continue
            valid += 1
            if rank is None or rank > 20:
                bands['not_in_top20'] += 1
            else:
                ranks.append(rank)
                bands['top3' if rank <= 3 else 'rank4_10' if rank <= 10 else 'rank11_20'] += 1
        total = len(inventory)
        bands['unknown'] = total-valid
        top10 = bands['top3'] + bands['rank4_10']
        top20 = top10 + bands['rank11_20']
        s = {k: v for k, v in candidate.items() if k.startswith(('volume_', 'sales_')) or k in ('candidate_id','query')}
        s.update(total_stores=total, eligible_stores=len(eligible), valid_stores=valid,
                 unknown_stores=total-valid, coverage_pct=_pct(valid,total),
                 top10_count=top10, top20_count=top20, top10_rate_pct=_pct(top10,valid),
                 top20_rate_pct=_pct(top20,valid), confirmed_top10_pct_all=_pct(top10,total),
                 confirmed_top20_pct_all=_pct(top20,total), rank_bands=bands,
                 mean_rank_top20=mean(ranks) if ranks else None,
                 median_rank_top20=median(ranks) if ranks else None, rank_status_counts=dict(counts))
        summaries.append(s)
    return summaries


def _csv_value(value):
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, str) and (value.lstrip().startswith(('=', '+', '-', '@'))
                                   or any(c in value for c in '\t\r\n')):
        return "'" + value
    return value


def write_csvs(root, state, result, summaries):
    """숫자 형식을 보존하며 사용자 문자열의 수식 실행을 막는다."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    tables = [('keyword-summary.csv', summaries, ['candidate_id','query','total_stores']),
              ('store-ranks.csv', result['rows'], ['candidate_id','query','place_id','rank_status','own_rank']),
              ('store-inventory.csv', _population(state), ['store_code','store_name','place_id','status'])]
    for filename, rows, defaults in tables:
        fields = defaults + sorted({key for row in rows for key in row} - set(defaults))
        with (root / filename).open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows({k: _csv_value(v) for k,v in row.items()} for row in rows)


def summary_markdown(summaries):
    def cell(value):
        return str(value).replace('|','／').replace('\n',' ').replace('\r',' ')
    def rate(value):
        return '산정 불가' if value is None else f'{value:.2f}%'
    lines = ['## 전체 매장 노출 요약', '',
             '| 검색어 | 전체 / 조사 가능 / 유효 | 미확인 | 커버리지 | TOP10 노출률 | TOP20 노출률 | 전체 중 확인 TOP10 / TOP20 | 순위 분포 1~3 / 4~10 / 11~20 / TOP20 미노출 / 미확인 | TOP20 평균 / 중앙값 |',
             '|---|---:|---:|---:|---:|---:|---:|---|---:|']
    for s in summaries:
        values = [s['query'], f"{s['total_stores']} / {s['eligible_stores']} / {s['valid_stores']}",
                  s['unknown_stores'], rate(s['coverage_pct']), rate(s['top10_rate_pct']), rate(s['top20_rate_pct']),
                  rate(s['confirmed_top10_pct_all'])+' / '+rate(s['confirmed_top20_pct_all']),
                  ' / '.join(str(s['rank_bands'][k]) for k in ('top3','rank4_10','rank11_20','not_in_top20','unknown')),
                  ' / '.join('산정 불가' if s[k] is None else f'{s[k]:.2f}' for k in ('mean_rank_top20','median_rank_top20'))]
        lines.append('| '+' | '.join(map(cell,values))+' |')
    lines += ['', 'TOP10·TOP20 노출률의 분모는 유효 관측 매장 수다. 커버리지와 전체 중 확인 비율의 분모는 전체 매장 수다. 분모가 0이면 산정 불가다.',
              '미확인에는 조사 제외·누락·부분 수집·실패·오래된 관측이 포함되며 비노출로 추정하지 않는다. 평균·중앙값은 TOP20 내 일반 순위만 사용한다.',
              '검색량은 키워드당 검색광고 제공 기간의 전국 PC·모바일 검색량이다. 지역별 검색량이 아니며 매장 수를 곱하지 않는다. 오래된 값·실패·자료 없음을 0으로 치환하지 않는다.', '']
    return '\n'.join(lines)
