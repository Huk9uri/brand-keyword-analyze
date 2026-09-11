from __future__ import annotations

import csv
from pathlib import Path

from .contracts import canonical

LABELS = {'VACANT': '빈집', 'COMPETITIVE': '경쟁', 'EXCLUDED': '제외', 'REVIEW_REQUIRED': '검토필요'}
HUMAN_FIELDS = ['사람_외식의도','사람_매장적합성','사람_경쟁유형','사람_시장유형','사람_추천여부','사람_확신도','사람_사유']


def export_review(evaluated, path: Path, *, show_automatic=False):
    fields = ['입력해시','candidate_id','매장','place_id','키워드','PC','모바일','합계','검색량구간','분위수',
              '자연카드수','광고수','직접경쟁점수','직접경쟁점유율','keywordList완전일치비율','keywordList동일의도비율',
              '자사순위','노출상태','검색노출경쟁점수','관측근거']
    if show_automatic:
        fields += ['자동분류','자동사유']
    fields += HUMAN_FIELDS
    with path.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for r in evaluated['results']:
            raw = r['raw_scores']
            values = [evaluated['input_hash'],r['candidate_id'],r['store_name'],r['target_place_id'],r['normalized_keyword'],
                      raw['pc_count'],raw['mobile_count'],raw['total_count'],canonical(raw['total_interval']),
                      r['normalized_scores']['demand_percentile'],raw['organic_count'],raw['ad_count'],raw['direct_count'],
                      raw['direct_share'],raw['keyword_exact_ratio'],raw['keyword_intent_ratio'],
                      raw['own_organic_rank'],raw['own_visibility_state'],
                      raw.get('exposure_competitor_count'),
                      canonical([{'source_refs': e['source_refs'], 'observed_values': e['observed_values']}
                                 for e in r['evidence'] if e['evidence_type'] != 'RULE'])]
            if show_automatic:
                values += [LABELS[r['final_class']], ';'.join(r['reason_codes'])]
            values += ['']*len(HUMAN_FIELDS)
            writer.writerow({key: _cell(value) for key, value in zip(fields, values)})


def _cell(value):
    # 스프레드시트 수식으로 실행될 수 있는 텍스트는 텍스트로 내보낸다.
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def comparison(evaluated, reviews):
    """고정된 사람 판정 목록과 자동 결과의 매장별 혼동행렬."""
    results = {r['candidate_id']: r for r in evaluated['results']}
    seen, matrices = set(), {}
    for review in reviews:
        cid = review['candidate_id']
        if cid in seen or cid not in results or review['market_type'] not in LABELS:
            raise ValueError('INVALID_REVIEW_COMPARISON')
        if review.get('input_hash') != evaluated['input_hash']:
            raise ValueError('REVIEW_INPUT_MISMATCH')
        seen.add(cid)
        result = results[cid]
        store = matrices.setdefault(result['target_place_id'], {'counts': {}, 'reviewed': 0, 'matched': 0, 'operation_hold': 0})
        if 'STORE_OPERATION_CONFLICT' in result['reason_codes']:
            store['operation_hold'] += 1
            continue
        pair = review['market_type'] + ':' + result['final_class']
        store['counts'][pair] = store['counts'].get(pair, 0)+1
        store['reviewed'] += 1
        store['matched'] += review['market_type'] == result['final_class']
    for place in {r['target_place_id'] for r in results.values()}:
        store = matrices.setdefault(place, {'counts': {}, 'reviewed': 0, 'matched': 0, 'operation_hold': 0})
        rows = [r for r in results.values() if r['target_place_id'] == place]
        store['total'] = len(rows)
        store['automatic'] = sum(r['final_class'] != 'REVIEW_REQUIRED' for r in rows)
        store['accuracy'] = store['matched']/store['reviewed'] if store['reviewed'] else None
    return matrices
