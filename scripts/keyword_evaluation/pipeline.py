from __future__ import annotations

from copy import deepcopy
from datetime import date
import re
from uuid import UUID

from .contracts import VERSION, aware_time, canonical, digest, keyword_key, searchad_key, place_id, percentile, settings
from .engine import low_cost, classify
from .volume import parse_volume, validate_period


def validate_bundle(data):
    allowed = {'schema_version', 'as_of_at', 'targets', 'candidate_runs', 'candidates', 'official_menus',
               'menu_evidence', 'reviews', 'volumes', 'knowledge', 'ranks', 'rank_links', 'rank_profile', 'keyword_snapshots', 'rules', 'source_timezones', 'review_as_of'}
    if set(data) - allowed or data.get('schema_version') != 1:
        raise ValueError('INVALID_INPUT_SCHEMA')
    canonical(data)
    from .store_location import validate_locations
    location_objects = validate_locations(data)
    def check_excluded(value):
        if isinstance(value, dict):
            excluded = {'distance_text', 'distance', 'skypos_sales', 'operation_keywords'}
            if id(value) not in location_objects:
                excluded.update(('latitude', 'longitude'))
            if set(value) & excluded:
                raise ValueError('EXCLUDED_INPUT')
            for child in value.values():
                check_excluded(child)
        elif isinstance(value, list):
            for child in value:
                check_excluded(child)
    check_excluded(data)
    aware_time(data['as_of_at'])
    targets = {place_id(t['place_id']): t for t in data['targets']}
    if len(targets) != len(data['targets']) or not targets or not data['menu_evidence']:
        raise ValueError('INVALID_TARGETS')
    if not 1 <= len(data['official_menus']) <= 5 or len({keyword_key(w) for w in data['official_menus']}) != len(data['official_menus']):
        raise ValueError('INVALID_OFFICIAL_MENUS')
    if len({t['target_store_id'] for t in targets.values()}) != len(targets):
        raise ValueError('AMBIGUOUS_JOIN')
    ids, keys = set(), set()
    for c in data['candidates']:
        if c['candidate_id'] in ids or type(c['candidate_id']) is not int:
            raise ValueError('DUPLICATE_CANDIDATE')
        ids.add(c['candidate_id'])
        target = targets.get(c['place_id'])
        if not target or c['candidate_scope'] != 'STORE' or c['brand_code'] != target['brand_code']:
            raise ValueError('CANDIDATE_IDENTITY_MISMATCH')
        if str(UUID(c['run_id'])).lower() != str(UUID(data['candidate_runs'][c['place_id']])).lower():
            raise ValueError('CANDIDATE_RUN_MISMATCH')
        if c.get('from_operation_keyword'):
            raise ValueError('EXCLUDED_SOURCE')
        if c.get('generated_at') and aware_time(c['generated_at']) > aware_time(data['as_of_at']):
            raise ValueError('FUTURE_CANDIDATE')
        key = (c['place_id'], keyword_key(c['normalized_keyword']))
        if key in keys or not key[1]:
            raise ValueError('AMBIGUOUS_JOIN')
        keys.add(key)
    candidates = {c['candidate_id']: c for c in data['candidates']}
    for r in data['reviews']:
        c = candidates.get(r['candidate_id'])
        if not c or any(r[k] != c[k] for k in ('run_id', 'brand_code', 'place_id', 'normalized_keyword')):
            raise ValueError('REVIEW_IDENTITY_MISMATCH')
        if r['source_type'] not in ('BLOG', 'VISITOR') or r['time_weight'] not in (.5, .8, 1):
            raise ValueError('INVALID_REVIEW')
        from scripts.keyword_candidate_discovery.models import AnalysisWindow
        window = AnalysisWindow(date.fromisoformat(data.get('review_as_of', '2026-09-09')))
        day = date.fromisoformat(r['review_date'])
        if not window.includes(day):
            raise ValueError('REVIEW_WINDOW_MISMATCH')
        if r['time_weight'] != window.weight_for(day):
            raise ValueError('REVIEW_WEIGHT_MISMATCH')
        if r.get('analyzed_at') and aware_time(r['analyzed_at']) > aware_time(data['as_of_at']):
            raise ValueError('FUTURE_REVIEW')
    knowledge = data['knowledge']
    if knowledge.get('competitor_basis', 'CATEGORY') not in ('CATEGORY', 'SEARCH_EXPOSURE'):
        raise ValueError('INVALID_COMPETITOR_BASIS')
    if not knowledge.get('version') or not knowledge.get('evidence'):
        raise ValueError('UNVERSIONED_RULES')
    if any(x not in ('DINING', 'MIXED', 'NON_DINING', 'UNKNOWN') for x in knowledge.get('intent', {}).values()):
        raise ValueError('INVALID_INTENT')
    for constraint in knowledge.get('fit_constraints', {}).values():
        if constraint.get('decision') not in ('PASS','FAIL','UNKNOWN','CONFLICT'):
            raise ValueError('INVALID_FIT_CONSTRAINT')
    for categories in knowledge.get('categories', {}).values():
        if any(x not in ('DIRECT', 'INDIRECT', 'NON_COMPETITOR', 'UNKNOWN') for x in categories.values()):
            raise ValueError('INVALID_COMPETITOR_RULE')
    for rows, time_key, id_key in ((data['volumes'], 'fetched_at', 'volume_snapshot_id'),
                                   (data['ranks'], 'collected_at', 'snapshot_id'),
                                   (data['keyword_snapshots'], 'checked_at', 'snapshot_id')):
        if len({r[id_key] for r in rows}) != len(rows):
            raise ValueError('DUPLICATE_SNAPSHOT')
        for row in rows:
            aware_time(row[time_key])
    rank_queries = {}
    for rank in data['ranks']:
        if aware_time(rank['collected_at']) > aware_time(data['as_of_at']):
            continue
        key = (rank['target_store_id'], rank['device_type'], rank.get('profile'), keyword_key(rank['normalized_query']))
        rank_queries.setdefault(key, set()).add(re.sub(r'\s+', ' ', rank['normalized_query']).strip())
    if any(len(values) > 1 for values in rank_queries.values()):
        raise ValueError('AMBIGUOUS_RANK_QUERY')
    for v in data['volumes']:
        validate_period({k:v[k] for k in ('period_type','period_definition','period_start','period_end','period_verified') if k in v})
        if v.get('period_type') not in ('UNVERIFIED','PROVIDER_MONTHLY','EXACT_30D'):
            raise ValueError('INVALID_PERIOD')
        if v['observation_status'] not in ('EXACT','CENSORED','NOT_PROVIDED','INVALID','FAILED'):
            raise ValueError('INVALID_VOLUME_STATUS')
        if searchad_key(v['request_keyword']) != v['searchad_lookup_key']:
            raise ValueError('VOLUME_KEY_MISMATCH')
        if v['observation_status'] in ('EXACT','CENSORED','NOT_PROVIDED'):
            observed = parse_volume(v['request_keyword'], v.get('response_json'))
            for key in ('observation_status','pc_count','mobile_count','total_count','raw_pc','raw_mobile'):
                if observed[key] != v.get(key) or type(observed[key]) is not type(v.get(key)):
                    raise ValueError('VOLUME_RESPONSE_MISMATCH')
        if v['observation_status'] == 'EXACT':
            values = [v[k] for k in ('pc_count', 'mobile_count', 'total_count')]
            if any(type(n) is not int or n < 0 for n in values) or values[0]+values[1] != values[2]:
                raise ValueError('INVALID_VOLUME')
    from .shared_rank import validate_shared_links
    validate_shared_links(data)
    return targets


def evaluate_bundle(bundle):
    data = deepcopy(bundle)
    targets = validate_bundle(data)
    rules = settings(data.get('rules', {}))
    candidates = sorted(data['candidates'], key=lambda c: c['candidate_id'])
    rows = [low_cost(c, targets[c['place_id']], data, rules) for c in candidates]
    populations = {}
    for place in targets:
        members = {}
        for r in rows:
            if (r['target_place_id'] == place and not r['reason_codes'] and r['volume_status'] == 'EXACT'
                    and r['gate_results'] == {'A': 'DINING', 'B': 'PASS'}):
                members[searchad_key(r['normalized_keyword'])] = r['raw_scores']['total_count']
        populations[place] = members
    common_keys = set.intersection(*(set(p) for p in populations.values()))
    common = {k: next(iter(populations.values()))[k] for k in sorted(common_keys)}
    for r in rows:
        pop = populations[r['target_place_id']]
        key = searchad_key(r['normalized_keyword'])
        r['normalized_scores'] = dict(demand_percentile=percentile(pop[key], list(pop.values())) if key in pop else None,
                                       common_demand_percentile=percentile(common[key], list(common.values())) if key in common else None,
                                       own_rank_score=None)
    queue = collection_queue(rows, data['official_menus'], rules)
    results = [classify(r, c, targets[c['place_id']], data, rules) for r, c in zip(rows, candidates)]
    selected = {q['candidate_id'] for q in queue}
    for result in results:
        if 'RANK_MISSING' in result['reason_codes'] and result['candidate_id'] not in selected:
            result['reason_codes'].append('NOT_COLLECTED_BUDGET')
            result['quality']['blocking_reasons'] = result['reason_codes']
    return dict(schema_version=1, calculation_version=VERSION, input_hash=digest(data),
                as_of_at=data['as_of_at'], input_manifest=data, rules=rules,
                demand_populations=populations, common_demand_population=common,
                collection_queue=queue, results=results)


def collection_queue(rows, menus, rules):
    queue = []
    menu_keys = {keyword_key(m) for m in menus}
    for place in sorted({r['target_place_id'] for r in rows}):
        eligible = [r for r in rows if r['target_place_id'] == place and not r['reason_codes']
                    and r['gate_results'] == {'A': 'DINING', 'B': 'PASS'} and r['volume_status'] == 'EXACT'
                    and r['raw_scores']['total_count'] >= rules['demand_floor']]
        order = lambda r: (-r['raw_scores']['total_count'], keyword_key(r['normalized_keyword']), r['candidate_id'])
        picked = {}
        groups = [('MENU', sorted([r for r in eligible if keyword_key(r['normalized_keyword']) in menu_keys], key=order), 5),
                  ('DEMAND', sorted(eligible, key=order), 10),
                  ('BOUNDARY', sorted(eligible, key=lambda r: (abs(r['raw_scores']['total_count']-rules['high_demand_floor']),
                                                               keyword_key(r['normalized_keyword']), r['candidate_id'])), 3)]
        uncertain = [r for r in rows if r['target_place_id'] == place and r['volume_status'] == 'EXACT'
                     and r['raw_scores']['total_count'] >= rules['demand_floor']
                     and set(r['reason_codes']) <= {'INTENT_UNCERTAIN', 'FIT_UNCERTAIN'}
                     and r['reason_codes'] and r['gate_results']['A'] != 'NON_DINING' and r['gate_results']['B'] != 'FAIL']
        groups.extend([('UNCERTAIN', sorted(uncertain, key=order), 2), ('FILL', sorted(eligible, key=order), rules['budget'])])
        for group, options, limit in groups:
            added = 0
            for r in options:
                if r['candidate_id'] not in picked and added < limit and len(picked) < rules['budget']:
                    picked[r['candidate_id']] = dict(candidate_id=r['candidate_id'], target_place_id=place,
                                                     query=r['normalized_keyword'], group=group, order=len(picked)+1)
                    added += 1
        queue.extend(picked.values())
    return queue
