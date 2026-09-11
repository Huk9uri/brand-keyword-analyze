"""원본 후보를 보존하는 근거 기반 선별과 단계별 수집 계획."""
from collections import Counter

from .contracts import aware_time, digest, keyword_key, searchad_key, settings
from .sources import freshness, latest


def screen_bundle(data, policy):
    if not policy.get('version') or not policy.get('evidence'):
        raise ValueError('UNVERSIONED_SCREENING_POLICY')
    targets = {t['place_id']: t for t in data['targets']}
    menus = {searchad_key(w): w for w in data['official_menus']}
    relations = {searchad_key(k): v for k,v in policy.get('menu_relations', {}).items()}
    as_of = aware_time(data['as_of_at'])
    rules = settings(data.get('rules', {}))
    rows, groups = [], {}
    for c in sorted(data['candidates'], key=lambda c: c['candidate_id']):
        query = keyword_key(c['normalized_keyword'])
        key, place = searchad_key(query), c['place_id']
        target = targets[place]
        group_key = digest([place, query])
        groups.setdefault(group_key, dict(group_key=group_key, place_id=place, query=query, candidate_ids=[]))['candidate_ids'].append(c['candidate_id'])
        evidence = [dict(kind='CANDIDATE', candidate_id=c['candidate_id'], run_id=c['run_id'],
                         sources=[k for k in ('from_menu','from_review','from_searchad_related') if c.get(k)])]
        for r in data['reviews']:
            if r['candidate_id'] == c['candidate_id']:
                evidence.append(dict(kind='REVIEW', review_term_id=r['review_term_id'],
                                     source_type=r['source_type'], source_review_id=r['source_review_id'],
                                     excerpt=r.get('evidence_excerpt'), verified_support=r.get('verified_support', False)))
        status, category, reason, priority = 'HOLD', 'UNCONFIRMED', '매장 적합성 근거 확인 필요', 3
        blocked = next((w for w in policy.get('non_dining_terms', []) if searchad_key(w) in key), None)
        # 수식어를 임의 제거하지 않는다. 명시적인 메뉴/상위 표현만 인정한다.
        base = key[:-2] if key.endswith('맛집') else key
        support = [menus[base]] if base in menus else [w for w in relations.get(base, []) if searchad_key(w) in menus]
        if blocked:
            status, category, reason = 'EXCLUDED', 'NON_DINING', '매장 방문과 다른 목적: '+blocked
            evidence.append(dict(kind='POLICY', version=policy['version'], matched_term=blocked, evidence=policy['evidence']))
        elif support:
            status, category, priority = 'PRIORITY', 'OFFICIAL_MENU' if key in menus else 'MENU_RELATED', 0 if key in menus else 1
            reason = '공식 메뉴 일치' if key in menus else '공식 메뉴에서 파생된 방문 목적 또는 상위 표현'
            evidence.append(dict(kind='MENU', menus=support, source=data['menu_evidence'],
                                 relation='EXACT' if key in menus else 'DERIVED', policy_version=policy['version']))
        facts = [f for f in policy.get('store_facts', {}).get(place, []) if keyword_key(f['keyword']) == query]
        valid = [f for f in facts if f.get('verified') is True and f.get('evidence') and f.get('source')
                 and f.get('verified_at') and aware_time(f['verified_at']) <= as_of]
        if valid and not blocked:
            decisions = {f.get('decision', 'PASS') for f in valid}
            evidence.extend(dict(kind='STORE_FACT', **f) for f in valid)
            if decisions == {'PASS'}:
                status, category, reason = 'PRIORITY', valid[0].get('category', 'STORE_INFO'), '매장별 검증 근거 일치'
                priority = 0 if category == 'REGION_MENU' else 2
            elif decisions == {'FAIL'}:
                status, category, reason = 'EXCLUDED', 'STORE_MISMATCH', '매장별 부적합 근거 확인'
            else:
                status, category, reason = 'HOLD', 'CONFLICT', '매장별 근거 충돌'
        if target.get('operation_status') != 'VERIFIED' or not target.get('identity_evidence'):
            status, reason = 'HOLD', '매장 운영 또는 식별 확인 필요'
        volume = latest([v for v in data['volumes'] if v['searchad_lookup_key'] == key and v['provider'] == 'NAVER_SEARCHAD'],
                        as_of, 'fetched_at', 'volume_snapshot_id')
        volume_state = 'MISSING'
        if volume:
            volume_state = volume['observation_status']
            if not freshness(volume, as_of, 'fetched_at', rules['ttl_days']):
                volume_state = 'STALE'
            elif not volume.get('period_verified'):
                volume_state = 'UNVERIFIED'
        rows.append(dict(candidate_id=c['candidate_id'], place_id=place, store_name=target['store_name'],
                         original_keyword=c['normalized_keyword'], query=query, group_key=group_key,
                         lookup_key=key, status=status, category=category, reason=reason, priority=priority,
                         evidence=evidence, volume_status=volume_state,
                         volume_snapshot_id=volume['volume_snapshot_id'] if volume else None,
                         total_count=volume.get('total_count') if volume else None))
    return dict(version=policy['version'], policy=policy, input_hash=digest(data), as_of_at=data['as_of_at'],
                rows=rows, groups=list(groups.values()), counts=dict(Counter(r['status'] for r in rows)))


def collection_plan(data, screening):
    if screening['input_hash'] != digest(data):
        raise ValueError('SCREENING_INPUT_MISMATCH')
    volume_keywords, queue, seen = [], [], set()
    ordered = sorted(screening['rows'], key=lambda r: (r['priority'],
                     -(r['total_count'] if r['volume_status'] == 'EXACT' and r['total_count'] is not None else -1),
                     r['query'], r['place_id'], r['candidate_id']))
    for row in ordered:
        if row['status'] != 'PRIORITY' or row['group_key'] in seen:
            continue
        seen.add(row['group_key'])
        if row['volume_status'] not in ('EXACT', 'CENSORED', 'NOT_PROVIDED'):
            if row['lookup_key'] not in volume_keywords:
                volume_keywords.append(row['lookup_key'])
        else:
            queue.append(dict(candidate_id=row['candidate_id'], target_place_id=row['place_id'],
                              query=row['query'], group=row['category'], order=len(queue)+1))
    return dict(volume_keywords=volume_keywords, rank_queue=queue)


def rank_input(data, screening):
    """최종 평가 임계치와 독립된, 기존 수집기의 입력 계약."""
    return dict(input_manifest=data, rules=settings(data.get('rules', {})),
                collection_queue=collection_plan(data, screening)['rank_queue'])


def exposure_rows(data, screening):
    from .collection import _reusable_rank
    from .sources import select_rank
    from .store_location import rank_profile
    evaluated = rank_input(data, screening)
    targets = {t['place_id']: t for t in data['targets']}
    result = []
    for row in screening['rows']:
        if row['status'] != 'PRIORITY':
            continue
        target = targets[row['place_id']]
        rank = select_rank(data['ranks'], target, row['query'], aware_time(data['as_of_at']),
                           data.get('rank_links', []), rank_profile(data))
        valid = _reusable_rank(evaluated, dict(query=row['query']), target)
        organic = [c for c in rank['results'] if not c['is_ad']] if valid else []
        own = next((c['organic_rank'] for c in organic if c['place_id'] == row['place_id']), None)
        competitors = [c for c in organic[:10] if c['place_id'] not in data['knowledge']['own_place_ids']]
        result.append(dict(candidate_id=row['candidate_id'], store_name=row['store_name'], query=row['query'],
                           status=row['status'], total_count=row['total_count'], volume_status=row['volume_status'],
                           rank_snapshot_id=rank['snapshot_id'] if rank else None,
                           rank_status='VALID' if valid else rank['collect_status'] if rank else 'MISSING',
                           own_organic_rank=own,
                           visibility='OBSERVED' if own else 'NOT_IN_TOP20' if len(organic)>=20 else
                           'NOT_OBSERVED_IN_COMPLETE_LIST' if valid else 'UNKNOWN',
                           competitors=competitors, competitor_count=len(competitors) if valid else None))
    return result
