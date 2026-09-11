from copy import deepcopy

import pytest

from scripts.keyword_evaluation.pipeline import evaluate_bundle
from scripts.keyword_evaluation.volume import parse_volume


def bundle():
    volumes = []
    candidates = []
    for i, (word, count) in enumerate([('설렁탕', 200), ('도가니탕', 10), ('왕갈비탕', 20), ('얼큰설렁탕', 30), ('소머리곰탕', 40)], 1):
        candidates.append(dict(candidate_id=i, run_id='00000000-0000-0000-0000-000000000001',
                               brand_code='1', candidate_scope='STORE', place_id='100',
                               normalized_keyword=word, from_operation_keyword=False))
        v = parse_volume(word, {'keywordList': [{'relKeyword': word, 'monthlyPcQcCnt': 0, 'monthlyMobileQcCnt': count}]})
        v.update(volume_snapshot_id=i, fetched_at='2026-09-09T00:00:00Z', period_type='PROVIDER_MONTHLY',
                 period_definition='테스트에서 검증한 월간 정의', period_verified=True)
        volumes.append(v)
    return dict(schema_version=1, as_of_at='2026-09-09T01:00:00Z',
                targets=[dict(place_id='100', brand_code='1', target_store_id='S1',
                              store_name='합성 매장', operation_status='VERIFIED', identity_evidence='fixture')],
                candidate_runs={'100': candidates[0]['run_id']}, candidates=candidates,
                official_menus=[c['normalized_keyword'] for c in candidates],
                menu_evidence='합성 공식 메뉴', reviews=[], volumes=volumes,
                knowledge=dict(version='fixture-v1', evidence='승인된 합성 규칙',
                               intent={c['normalized_keyword']: 'DINING' for c in candidates},
                               categories={'설렁탕': {'설렁탕': 'DIRECT', '카페': 'NON_COMPETITOR'}},
                               synonyms={}, own_place_ids=['100'], own_registry_complete=True),
                ranks=[dict(snapshot_id=10, run_id='00000000-0000-0000-0000-000000000002', task_key='a'*64,
                            target_store_id='S1', normalized_query='설렁탕', device_type='MOBILE',
                            profile='MOBILE_NO_LOCATION_ORGANIC20_V2', collect_status='SUCCESS',
                            collected_at='2026-09-09T00:00:00Z', result_end_reached=True,
                            results=[dict(raw_position=i, organic_rank=i, place_id='100' if i == 3 else str(200+i),
                                          is_ad=False, category='설렁탕' if i <= 2 else '카페') for i in range(1, 11)])],
                keyword_snapshots=[dict(snapshot_id=i, effective_snapshot_id=i, place_id=str(200+i),
                                        collect_status='EMPTY', checked_at='2026-09-09T00:00:00Z',
                                        keyword_count=0, keywords=[]) for i in (1, 2)])


def first(data):
    return evaluate_bundle(data)['results'][0]


def test_complete_vacancy_and_replay():
    data = bundle()
    assert first(data)['final_class'] == 'VACANT'
    assert first(data)['raw_scores']['direct_share'] == .2
    assert evaluate_bundle(data) == evaluate_bundle(deepcopy(data))


@pytest.mark.parametrize('mutation,reason', [
    (lambda x: x['ranks'][0].update(collect_status='PARTIAL'), 'RANK_PARTIAL'),
    (lambda x: x.update(keyword_snapshots=[]), 'KEYWORDLIST_MISSING'),
    (lambda x: x['targets'][0].update(operation_status='CONFLICT'), 'STORE_OPERATION_CONFLICT'),
    (lambda x: x['ranks'][0].update(profile='LEGACY'), 'RANK_MISSING'),
    (lambda x: x['volumes'][0].update(period_verified=False), 'PERIOD_UNVERIFIED'),
    (lambda x: x['ranks'][0]['results'][0].update(category='한식'), 'COMPETITOR_UNKNOWN'),
    (lambda x: x['knowledge'].update(own_registry_complete=False), 'OWN_REGISTRY_INCOMPLETE'),
])
def test_missing_quality_never_becomes_vacancy(mutation, reason):
    data = bundle()
    mutation(data)
    result = first(data)
    assert result['final_class'] == 'REVIEW_REQUIRED'
    assert reason in result['reason_codes']


def test_latest_failed_rank_does_not_fall_back():
    data = bundle()
    new = deepcopy(data['ranks'][0])
    new.update(snapshot_id=11, collected_at='2026-09-09T00:30:00Z', collect_status='LOAD_TIMEOUT')
    data['ranks'].append(new)
    assert 'RANK_FAILED' in first(data)['reason_codes']


def test_ads_do_not_count_in_denominator():
    data = bundle()
    ad = dict(raw_position=1, organic_rank=None, is_ad=True, place_id='999', category='설렁탕')
    for card in data['ranks'][0]['results']:
        card['raw_position'] += 1
    data['ranks'][0]['results'].insert(0, ad)
    assert first(data)['raw_scores']['direct_share'] == .2
    assert first(data)['raw_scores']['ad_count'] == 1


def test_observed_depth_not_twenty_when_target_absent():
    data = bundle()
    data['ranks'][0]['results'][2]['place_id'] = '203'
    data['ranks'][0]['result_end_reached'] = False
    result = first(data)
    assert result['raw_scores']['own_visibility_state'] == 'DEPTH_INSUFFICIENT'
    assert result['raw_scores']['own_organic_rank'] is None
    assert result['final_class'] == 'REVIEW_REQUIRED'


def test_latest_empty_is_valid_but_failed_fallback_is_stale():
    data = bundle()
    row = deepcopy(data['keyword_snapshots'][0])
    row.update(snapshot_id=3, collect_status='PARSE_ERROR', checked_at='2026-09-09T00:30:00Z')
    data['keyword_snapshots'].append(row)
    assert 'STALE_FALLBACK' in first(data)['reason_codes']


def test_duplicate_organic_place_is_not_silently_deduplicated():
    data = bundle()
    data['ranks'][0]['results'][1]['place_id'] = '201'
    assert 'RANK_INVALID' in first(data)['reason_codes']


def test_non_dining_does_not_require_rank():
    data = bundle()
    data['knowledge']['intent']['설렁탕'] = 'NON_DINING'
    data['ranks'] = []
    assert first(data)['final_class'] == 'EXCLUDED'


def test_candidate_run_mismatch_rejected():
    data = bundle()
    data['candidates'][0]['run_id'] = '00000000-0000-0000-0000-000000000099'
    with pytest.raises(ValueError, match='CANDIDATE_RUN'):
        evaluate_bundle(data)


def test_volume_cannot_disagree_with_observed_response():
    data = bundle()
    data['volumes'][0].update(pc_count=1000, mobile_count=1000, total_count=2000)
    with pytest.raises(ValueError, match='VOLUME'):
        evaluate_bundle(data)


def test_coordinates_are_rejected_in_evaluation_input():
    data = bundle()
    data['ranks'][0]['latitude'] = 37.5
    with pytest.raises(ValueError, match='EXCLUDED_INPUT'):
        evaluate_bundle(data)


def test_competition_high_demand_with_complete_non_exposure():
    data = bundle()
    data['ranks'][0]['results'][2]['place_id'] = '203'
    for card in data['ranks'][0]['results'][:7]:
        card['category'] = '설렁탕'
    data['keyword_snapshots'] = [dict(snapshot_id=i, effective_snapshot_id=i, place_id=str(200+i),
                                    collect_status='EMPTY', checked_at='2026-09-09T00:00:00Z',
                                    keyword_count=0, keywords=[]) for i in range(1,8)]
    assert first(data)['final_class'] == 'COMPETITIVE'


def test_unknown_fit_constraint_cannot_be_silently_accepted():
    data = bundle()
    data['knowledge']['fit_constraints'] = {'설렁탕': {'decision': 'PASSES', 'evidence': 'test'}}
    with pytest.raises(ValueError, match='FIT'):
        evaluate_bundle(data)


def test_all_six_gates_and_normalized_scores_present():
    result = first(bundle())
    assert set(result['gate_results']) == set('ABCDEF')
    assert result['normalized_scores']['direct_share'] == .2


def test_old_review_cannot_support_current_fit():
    data = bundle()
    c = data['candidates'][0]
    data['reviews'] = [dict(candidate_id=c['candidate_id'], run_id=c['run_id'], brand_code='1', place_id='100',
                           normalized_keyword='설렁탕', source_type='VISITOR', source_review_id=1,
                           review_term_id=1, time_weight=1, review_date='2020-01-01')]
    with pytest.raises(ValueError, match='REVIEW_WINDOW'):
        evaluate_bundle(data)


def test_confirmed_unfit_is_not_queued_even_with_mixed_intent():
    data = bundle()
    data['knowledge']['intent']['설렁탕'] = 'MIXED'
    data['knowledge']['fit_constraints'] = {'설렁탕': {'decision':'FAIL','evidence':'확정 충돌'}}
    evaluated = evaluate_bundle(data)
    assert evaluated['results'][0]['final_class'] == 'EXCLUDED'
    assert 1 not in {q['candidate_id'] for q in evaluated['collection_queue']}


def test_unknown_competitor_preserves_interval_without_zero_fill():
    data = bundle()
    data['ranks'][0]['results'][0]['category'] = '미확정'
    result = first(data)
    assert result['raw_scores']['direct_share'] is None
    assert result['raw_scores']['direct_share_interval'] == [.1, .2]


def test_unverifiable_review_excerpt_does_not_grant_fit():
    data = bundle()
    data['candidates'][0]['normalized_keyword'] = '혼밥'
    data['knowledge']['intent']['혼밥'] = 'DINING'
    c = data['candidates'][0]
    data['reviews'] = [dict(candidate_id=1,run_id=c['run_id'],brand_code='1',place_id='100',normalized_keyword='혼밥',
                           source_type='VISITOR',source_review_id=i,review_term_id=i,time_weight=1,review_date='2026-09-01',
                           source_collect_status='success',verified_support=True,verification_evidence='검토표',
                           support_kind='CONTEXT', source_context=None, support_excerpt='혼밥') for i in range(1,4)]
    assert first(data)['gate_results']['B'] == 'UNKNOWN'


def test_same_normalized_rank_key_with_distinct_queries_is_ambiguous():
    data=bundle()
    row=deepcopy(data['ranks'][0])
    row.update(snapshot_id=11,normalized_query='설렁탕 ')
    data['ranks'].append(row)
    # 공백 축약은 순위 수집기에도 적용되므로 같은 query다.
    assert first(data)['final_class']=='VACANT'
    data['candidates'][0]['normalized_keyword']='abc'
    data['ranks'][0]['normalized_query']='abc'
    data['ranks'][1]['normalized_query']='ＡＢＣ'
    with pytest.raises(ValueError,match='AMBIGUOUS'):
        evaluate_bundle(data)
