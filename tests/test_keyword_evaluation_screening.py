from scripts.keyword_evaluation import screening
from test_keyword_evaluation_engine import bundle


def policy():
    return dict(version='test-v1', evidence='승인된 후보 선별',
                menu_relations={'갈비탕': ['왕갈비탕']}, non_dining_terms=['창업', '밀키트'], store_facts={})


def data_with(*words):
    data = bundle()
    c = data['candidates'][0]
    data['candidates'] = [dict(c, candidate_id=i+1, normalized_keyword=w) for i,w in enumerate(words)]
    data['reviews'] = []
    return data


def test_whitespace_groups_preserve_synonyms_and_rank_query_spacing():
    data = data_with(' 설렁탕  맛집 ', '설렁탕 맛집', '설렁탕맛집', '설농탕')
    result = screening.screen_bundle(data, policy())
    assert len(result['groups']) == 3
    assert result['rows'][0]['query'] == '설렁탕 맛집'
    assert result['rows'][0]['group_key'] == result['rows'][1]['group_key']
    assert result['rows'][1]['group_key'] != result['rows'][2]['group_key']
    assert result['rows'][3]['status'] == 'HOLD'


def test_menu_claim_is_exact_and_unknown_service_is_held():
    data = data_with('설렁탕', '설렁탕밀키트', '24시간설렁탕', '한우설렁탕')
    rows = screening.screen_bundle(data, policy())['rows']
    assert [r['status'] for r in rows] == ['PRIORITY', 'EXCLUDED', 'HOLD', 'HOLD']
    assert rows[0]['evidence']


def test_store_evidence_does_not_leak_and_unverified_fact_does_not_pass():
    data = data_with('주차')
    p = policy()
    p['store_facts'] = {'999': [{'keyword':'주차','verified':True,'evidence':'타 매장 정보'}],
                        '100': [{'keyword':'주차','verified':False,'evidence':'미확인'}]}
    assert screening.screen_bundle(data,p)['rows'][0]['status'] == 'HOLD'
    p['store_facts']['100'][0]['verified'] = True
    p['store_facts']['100'][0]['source'] = '공식 매장 정보'
    p['store_facts']['100'][0]['verified_at'] = data['as_of_at']
    assert screening.screen_bundle(data,p)['rows'][0]['status'] == 'PRIORITY'


def test_zero_volume_and_no_own_rank_never_exclude_candidate():
    data = data_with('설렁탕')
    data['volumes'][0].update(total_count=0, pc_count=0, mobile_count=0)
    data['ranks'] = []
    result = screening.screen_bundle(data,policy())
    assert result['rows'][0]['status'] == 'PRIORITY'
    plan = screening.collection_plan(data,result)
    assert len(plan['rank_queue']) == 1
    assert plan['volume_keywords'] == []


def test_missing_volume_is_queued_before_rank_and_shared_between_stores():
    data = data_with('설렁탕')
    data['volumes'] = []
    data['targets'].append(dict(data['targets'][0],place_id='101',target_store_id='S2'))
    data['candidates'].append(dict(data['candidates'][0],candidate_id=2,place_id='101'))
    plan = screening.collection_plan(data,screening.screen_bundle(data,policy()))
    assert plan['volume_keywords'] == ['설렁탕']
    assert plan['rank_queue'] == []


def test_rank_tasks_follow_screening_priority_instead_of_candidate_id():
    from scripts.keyword_evaluation.collection import build_rank_tasks
    from scripts.keyword_evaluation.contracts import settings
    data = data_with('국밥', '설렁탕')
    data['ranks'] = []
    evaluated = dict(input_manifest=data, rules=settings({}), collection_queue=[
        dict(candidate_id=2,target_place_id='100',query='설렁탕',order=1),
        dict(candidate_id=1,target_place_id='100',query='국밥',order=2)])
    assert [t.query for t in build_rank_tasks(evaluated)] == ['설렁탕','국밥']


def test_censored_volume_can_proceed_but_failed_volume_cannot():
    data = data_with('설렁탕')
    data['volumes'][0]['observation_status'] = 'CENSORED'
    assert len(screening.collection_plan(data,screening.screen_bundle(data,policy()))['rank_queue']) == 1
    data['volumes'][0]['observation_status'] = 'FAILED'
    assert screening.collection_plan(data,screening.screen_bundle(data,policy()))['rank_queue'] == []


def test_confirmed_region_fact_and_unknown_region_are_separate():
    data = data_with('선릉역 설렁탕','부산 설렁탕')
    p = policy()
    p['store_facts']['100'] = [dict(keyword='선릉역 설렁탕',verified=True,decision='PASS',
                                  category='REGION_MENU',source='매장 주소 원천',evidence='선릉역 상권 확인',
                                  verified_at=data['as_of_at'])]
    rows = screening.screen_bundle(data,p)['rows']
    assert rows[0]['status'] == 'PRIORITY'
    assert rows[0]['priority'] == 0
    assert rows[1]['status'] == 'HOLD'


def test_offline_cli_accepts_frozen_bundle_without_database(tmp_path):
    import json
    from scripts.keyword_evaluation.screening_cli import main
    data = data_with('설렁탕')
    input_path, policy_path = tmp_path/'input.json', tmp_path/'policy.json'
    input_path.write_text(json.dumps(data),encoding='utf-8')
    policy_path.write_text(json.dumps(policy()),encoding='utf-8')
    output = tmp_path/'report'
    assert main(['--input',str(input_path),'--policy',str(policy_path),'--output',str(output)]) == 0
    saved = json.loads((output/'screening.json').read_text(encoding='utf-8'))
    assert saved['counts'] == {'PRIORITY':1}
    assert (output/'report.md').exists()


def test_exposure_keeps_unlisted_target_and_counts_every_non_own_category():
    data = data_with('설렁탕')
    data['ranks'][0]['results'][2]['place_id'] = '999'
    rows = screening.exposure_rows(data,screening.screen_bundle(data,policy()))
    assert rows[0]['status'] == 'PRIORITY'
    assert rows[0]['visibility'] == 'NOT_OBSERVED_IN_COMPLETE_LIST'
    assert rows[0]['own_organic_rank'] is None
    assert rows[0]['competitor_count'] == 10


def test_valid_existing_rank_is_reused_without_a_new_browser_task():
    from scripts.keyword_evaluation.collection import build_rank_tasks
    data = data_with('설렁탕')
    evaluated = screening.rank_input(data,screening.screen_bundle(data,policy()))
    assert build_rank_tasks(evaluated) == []


def test_snapshot_clock_does_not_round_into_future_second(monkeypatch):
    from datetime import datetime, timezone
    from scripts.keyword_evaluation import collection
    class FixedClock:
        @staticmethod
        def now(tz):
            return datetime(2026,9,10,1,58,35,974196,tzinfo=timezone.utc)
    monkeypatch.setattr(collection,'datetime',FixedClock)
    assert collection.utc_snapshot_time() == datetime(2026,9,10,1,58,35)
