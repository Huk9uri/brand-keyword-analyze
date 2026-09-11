from __future__ import annotations

from .contracts import keyword_key, searchad_key, aware_time
from .sources import latest, freshness, select_rank, select_keywords


def low_cost(candidate, target, data, rules):
    key = keyword_key(candidate['normalized_keyword'])
    knowledge = data['knowledge']
    evidence = [{'evidence_type': 'CANDIDATE', 'source_refs': {'candidate_id': candidate['candidate_id'],
                 'candidate_run_id': candidate['run_id']}, 'observed_values': candidate, 'decision': {}}]
    reasons = []
    intent = knowledge.get('intent', {}).get(key, 'UNKNOWN')
    fit = 'UNKNOWN'
    if key in {keyword_key(w) for w in data['official_menus']}:
        fit = 'PASS'
    evidence.append({'evidence_type': 'RULE', 'source_refs': {'rule_version': knowledge['version']},
                     'observed_values': {'intent': intent, 'menu_evidence': data['menu_evidence']}, 'decision': {}})
    mentions = {}
    for r in data['reviews']:
        if r['candidate_id'] != candidate['candidate_id']:
            continue
        evidence.append({'evidence_type': 'REVIEW', 'source_refs': {k: r[k] for k in
                         ('review_term_id', 'source_type', 'source_review_id', 'run_id')},
                         'observed_values': r, 'decision': {}})
        if (r.get('source_collect_status') == 'success' and r.get('verified_support') is True
                and r.get('verification_evidence') and r.get('support_kind') == 'CONTEXT'
                and r.get('source_context') and r.get('support_excerpt')
                and keyword_key(r['support_excerpt']) in keyword_key(r['source_context'])):
            review_key = (r['source_type'], r['source_review_id'])
            mentions[review_key] = max(mentions.get(review_key, 0), r['time_weight'])
    if fit != 'PASS' and len(mentions) >= rules['review_min']:
        fit = 'PASS'
    # 명시적인 복합 조건 판정은 근거가 있는 승인 규칙만 허용한다.
    constraints = knowledge.get('fit_constraints', {}).get(key, {})
    if constraints:
        fit = constraints['decision']
        if not constraints.get('evidence'):
            fit = 'UNKNOWN'
        if constraints.get('requires_service') and fit == 'PASS':
            fit = 'UNKNOWN'
        evidence.append({'evidence_type': 'RULE', 'source_refs': {'rule_version': knowledge['version']},
                         'observed_values': constraints, 'decision': {'fit': fit}})
    if target.get('operation_status') != 'VERIFIED':
        reasons.append('STORE_OPERATION_CONFLICT')
    if not target.get('identity_evidence'):
        reasons.append('IDENTITY_UNVERIFIED')
    if intent not in ('DINING', 'NON_DINING'):
        reasons.append('INTENT_UNCERTAIN')
    if fit not in ('PASS', 'FAIL'):
        reasons.append('FIT_CONFLICT' if fit == 'CONFLICT' else 'FIT_UNCERTAIN')
    volume = latest([v for v in data['volumes'] if v['searchad_lookup_key'] == searchad_key(candidate['normalized_keyword'])
                     and v['provider'] == 'NAVER_SEARCHAD'], aware_time(data['as_of_at']), 'fetched_at', 'volume_snapshot_id')
    raw = {k: None for k in ('pc_count', 'mobile_count', 'total_count', 'pc_interval', 'mobile_interval', 'total_interval',
                            'organic_count', 'ad_count', 'direct_count', 'unknown_competitor_count', 'direct_share', 'direct_share_interval',
                            'keyword_exact_count', 'keyword_synonym_only_count', 'keyword_coverage_count',
                            'keyword_exact_ratio', 'keyword_intent_ratio', 'own_organic_rank')}
    raw.update(review_count=len(mentions), weighted_mentions=sum(mentions.values()), own_visibility_state='UNKNOWN')
    if volume:
        raw.update({k: volume.get(k) for k in ('pc_count', 'mobile_count', 'total_count',
                                             'pc_interval', 'mobile_interval', 'total_interval')})
        evidence.append({'evidence_type': 'VOLUME', 'source_refs': {'volume_snapshot_id': volume['volume_snapshot_id']},
                         'observed_values': volume, 'decision': {}})
        if not volume.get('period_verified') or volume.get('period_type') == 'UNVERIFIED':
            reasons.append('PERIOD_UNVERIFIED')
        if not freshness(volume, aware_time(data['as_of_at']), 'fetched_at', rules['ttl_days']):
            reasons.append('STALE')
        if volume['observation_status'] not in ('EXACT', 'NOT_PROVIDED'):
            reasons.append('DEMAND_' + volume['observation_status'])
    else:
        reasons.append('DEMAND_MISSING')
    return dict(candidate_id=candidate['candidate_id'], target_place_id=target['place_id'],
                normalized_keyword=candidate['normalized_keyword'], store_name=target['store_name'],
                volume_snapshot_id=volume['volume_snapshot_id'] if volume else None, rank_snapshot_id=None,
                raw_scores=raw, normalized_scores={}, gate_results={'A': intent, 'B': fit},
                reason_codes=reasons, evidence=evidence,
                volume_status=volume['observation_status'] if volume else 'MISSING')


def classify(result, candidate, target, data, rules):
    reasons = result['reason_codes']
    gates = result['gate_results']
    def finish(label, extra=None):
        if extra:
            reasons.append(extra)
        result['final_class'] = label
        raw = result['raw_scores']
        gates.setdefault('C', result['volume_status'])
        gates.setdefault('D', 'VALID' if raw['direct_share'] is not None else 'UNKNOWN')
        gates.setdefault('E', 'UNKNOWN')
        gates.setdefault('F', raw['own_visibility_state'])
        if label == 'EXCLUDED':
            for key in ('D','E','F'):
                gates[key] = 'NOT_APPLICABLE'
        result['normalized_scores'].update(
            intent_gate_value=1 if gates['A']=='DINING' else 0 if gates['A']=='NON_DINING' else None,
            fit_gate_value=1 if gates['B']=='PASS' else 0 if gates['B']=='FAIL' else None,
            direct_share=raw['direct_share'], keyword_exact_ratio=raw['keyword_exact_ratio'],
            keyword_intent_ratio=raw['keyword_intent_ratio'])
        result['reason_codes'] = sorted(set(reasons))
        result['quality'] = {'blocking_reasons': result['reason_codes'] if label == 'REVIEW_REQUIRED' else [],
                             'source_reasons': result['reason_codes'],
                             'gates': {key: {'value': value, 'rule_version': data['knowledge']['version'],
                                             'evidence_numbers': list(range(1,len(result['evidence'])+1))}
                                       for key,value in gates.items()}}
        return result
    if any(r in reasons for r in ('STORE_OPERATION_CONFLICT', 'IDENTITY_UNVERIFIED', 'FIT_CONFLICT')):
        return finish('REVIEW_REQUIRED')
    if gates['A'] == 'NON_DINING' or gates['B'] == 'FAIL':
        return finish('EXCLUDED', 'INTENT_NON_DINING' if gates['A'] == 'NON_DINING' else 'FIT_FAIL')
    if reasons:
        return finish('REVIEW_REQUIRED')
    if result['volume_status'] == 'NOT_PROVIDED':
        return finish('EXCLUDED', 'DEMAND_NOT_PROVIDED')
    raw = result['raw_scores']
    if raw['total_count'] == 0:
        return finish('EXCLUDED', 'ZERO_DEMAND')
    if raw['total_count'] < rules['demand_floor']:
        return finish('REVIEW_REQUIRED', 'LOW_DEMAND_THRESHOLD')
    as_of = aware_time(data['as_of_at'])
    from .store_location import rank_profile
    rank = select_rank(data['ranks'], target, candidate['normalized_keyword'], as_of, data.get('rank_links', []), rank_profile(data))
    if not rank:
        return finish('REVIEW_REQUIRED', 'RANK_MISSING')
    result['rank_snapshot_id'] = rank['snapshot_id']
    result['evidence'].append({'evidence_type': 'RANK', 'source_refs': {k: rank[k] for k in ('snapshot_id', 'run_id', 'task_key')},
                               'observed_values': rank, 'decision': {}})
    if rank['collect_status'] != 'SUCCESS':
        return finish('REVIEW_REQUIRED', 'RANK_PARTIAL' if rank['collect_status'] == 'PARTIAL' else 'RANK_FAILED')
    if not freshness(rank, as_of, 'collected_at', rules['ttl_days']):
        return finish('REVIEW_REQUIRED', 'STALE')
    cards = rank['results']
    organic = [c for c in cards if not c['is_ad']]
    if ([c['raw_position'] for c in cards] != list(range(1, len(cards)+1))
            or [c['organic_rank'] for c in organic] != list(range(1, len(organic)+1))
            or len({c['place_id'] for c in organic}) != len(organic)
            or any(c['is_ad'] and c['organic_rank'] is not None for c in cards)):
        return finish('REVIEW_REQUIRED', 'RANK_INVALID')
    own = next((c['organic_rank'] for c in organic if c['place_id'] == target['place_id']), None)
    state = ('OBSERVED' if own else 'NOT_IN_TOP20' if len(organic) >= 20 else
             'NOT_OBSERVED_IN_COMPLETE_LIST' if rank['result_end_reached'] else 'DEPTH_INSUFFICIENT')
    raw.update(own_organic_rank=own, own_visibility_state=state, ad_count=len(cards)-len(organic))
    result['normalized_scores']['own_rank_score'] = (21-own)/20 if own and own <= 20 else None
    if not organic or (len(organic) < rules['top_n'] and not rank['result_end_reached']) or state == 'DEPTH_INSUFFICIENT':
        return finish('REVIEW_REQUIRED', 'DEPTH_INSUFFICIENT')
    top = organic[:rules['top_n']]
    knowledge = data['knowledge']
    if not knowledge.get('own_registry_complete'):
        return finish('REVIEW_REQUIRED', 'OWN_REGISTRY_INCOMPLETE')
    category_rules = knowledge.get('categories', {}).get(keyword_key(candidate['normalized_keyword']), {})
    exposure_basis = knowledge.get('competitor_basis') == 'SEARCH_EXPOSURE'
    direct, unknown = [], 0
    for c in top:
        kind = ('OWN_BRAND' if c['place_id'] in knowledge['own_place_ids'] else
                'SEARCH_EXPOSURE' if exposure_basis else category_rules.get(c.get('category'), 'UNKNOWN'))
        if kind in ('DIRECT', 'SEARCH_EXPOSURE'):
            direct.append(c)
        unknown += kind == 'UNKNOWN'
        result['evidence'].append({'evidence_type': 'RULE', 'source_refs': {'snapshot_id': rank['snapshot_id'],
                                 'raw_position': c['raw_position'], 'rule_version': knowledge['version']},
                                 'observed_values': c, 'decision': {'competitor_type': kind}})
    raw.update(organic_count=len(top), direct_count=None if exposure_basis else len(direct), unknown_competitor_count=unknown)
    if exposure_basis:
        raw['exposure_competitor_count'] = len(direct)
        gates['D'] = 'VALID'
    else:
        raw['direct_share_interval'] = [len(direct)/len(top), (len(direct)+unknown)/len(top)]
    if unknown:
        return finish('REVIEW_REQUIRED', 'COMPETITOR_UNKNOWN')
    if not exposure_basis:
        raw['direct_share'] = len(direct)/len(top)
    exact, synonym, coverage = 0, 0, 0
    key = keyword_key(candidate['normalized_keyword'])
    synonyms = {keyword_key(s) for s in knowledge.get('synonyms', {}).get(key, [])}
    for c in direct:
        words, refs, error = select_keywords(data['keyword_snapshots'], c['place_id'], as_of,
                                            aware_time(rank['collected_at']), rules)
        match = 'UNKNOWN'
        if error:
            reasons.append(error)
        else:
            coverage += 1
            normalized = {keyword_key(w['normalized_keyword']) for w in words}
            if key in normalized:
                exact += 1
                match = 'EXACT'
            elif normalized & synonyms:
                synonym += 1
                match = 'SYNONYM'
            else:
                match = 'NONE'
        result['evidence'].append({'evidence_type': 'KEYWORDLIST', 'source_refs': refs,
                                 'observed_values': words, 'decision': {'match': match, 'error': error}})
    raw['keyword_coverage_count'] = coverage
    if reasons:
        return finish('REVIEW_REQUIRED')
    raw.update(keyword_exact_count=exact, keyword_synonym_only_count=synonym,
               keyword_exact_ratio=exact/len(direct) if direct else None,
               keyword_intent_ratio=(exact+synonym)/len(direct) if direct else None)
    gates['E'] = 'VALID' if direct else 'NOT_APPLICABLE'
    if exposure_basis:
        return finish('REVIEW_REQUIRED', 'COMPETITION_CALIBRATION_REQUIRED')
    low_keyword = not direct or raw['keyword_intent_ratio'] <= rules['keyword_low']
    if raw['direct_share'] <= rules['direct_low'] and low_keyword and own:
        return finish('VACANT', 'VACANT_RULE_V1')
    p = result['normalized_scores'].get('demand_percentile')
    high = raw['total_count'] >= rules['high_demand_floor'] and p is not None and p >= rules['high_percentile']
    if high and (raw['direct_share'] >= rules['direct_high'] or
                 (direct and raw['keyword_intent_ratio'] >= rules['keyword_high'])):
        return finish('COMPETITIVE', 'COMPETITIVE_RULE_V1')
    return finish('REVIEW_REQUIRED', 'THRESHOLD_UNCERTAIN')
