"""공유 순위 관측의 수집 계획과 명시적 후보 연결 검증."""
from .contracts import PROFILE, STORE_PROFILE, LOCATION_PROFILES, keyword_key


def build_rank_plan(evaluated):
    from .collection import _reusable_rank
    from scripts.keyword_discovery_rank.models import SearchTask, DeviceType, SourceType
    from scripts.keyword_discovery_rank.task_source import build_task_key

    targets = {t['place_id']: t for t in evaluated['input_manifest']['targets']}
    from .store_location import rank_profile
    profile = rank_profile(evaluated['input_manifest'])
    groups = {}
    # 선별기가 결정한 수집 순서를 유지한다. ID 정렬은 검색량 우선순위를 잃는다.
    for queued in evaluated['collection_queue']:
        key = (queued['target_place_id'] if profile in LOCATION_PROFILES else None, keyword_key(queued['query']))
        groups.setdefault(key, []).append(queued)
    tasks, observations = [], []
    for (_, query), group in groups.items():
        if all(_reusable_rank(evaluated, q, targets[q['target_place_id']]) for q in group):
            continue
        first = group[0]
        target = targets[first['target_place_id']]
        location = target['search_location'] if profile in LOCATION_PROFILES else {}
        task = SearchTask(str(first['candidate_id']), query, target['target_store_id'],
                          target['store_name'], profile, location.get('latitude'), location.get('longitude'),
                          SourceType.DATABASE, str(first['candidate_id']), DeviceType.MOBILE)
        tasks.append(task)
        if profile in LOCATION_PROFILES:
            continue
        observations.append(dict(task_key=build_task_key(task), normalized_query=query,
            source_target_store_id=task.target_store_id, device_type='MOBILE', profile=PROFILE,
            bindings=[dict(candidate_id=q['candidate_id'], target_place_id=q['target_place_id'],
                           target_store_id=targets[q['target_place_id']]['target_store_id']) for q in group]))
    return tasks, observations


def attach_shared_links(data, spec, ranks):
    links = data.setdefault('rank_links', [])
    observations = spec.get('shared_observations', [])
    seen = set()
    for observation in observations:
        key = observation['task_key']
        if key in seen or observation['profile'] != PROFILE or spec['profile'] != PROFILE or observation['device_type'] != 'MOBILE':
            raise ValueError('SHARED_RANK_OBSERVATION_MISMATCH')
        seen.add(key)
        for rank in ranks:
            if rank['task_key'] != key:
                continue
            if (str(rank['run_id']).lower() != str(spec['run_id']).lower()
                    or rank['target_store_id'] != observation['source_target_store_id']
                    or keyword_key(rank['normalized_query']) != observation['normalized_query']
                    or rank['device_type'] != observation['device_type'] or rank['profile'] != PROFILE):
                raise ValueError('SHARED_RANK_OBSERVATION_MISMATCH')
            for binding in observation['bindings']:
                links.append(dict(binding, snapshot_id=rank['snapshot_id'], run_id=rank['run_id'],
                                  task_key=key, normalized_query=observation['normalized_query'], profile=PROFILE))
    validate_shared_links(data)


def validate_shared_links(data):
    targets = {t['place_id']: t for t in data['targets']}
    candidates = {c['candidate_id']: c for c in data['candidates']}
    ranks = {r['snapshot_id']: r for r in data['ranks']}
    seen = set()
    for link in data.get('rank_links', []):
        rank = ranks.get(link.get('snapshot_id'))
        candidate = candidates.get(link.get('candidate_id'))
        target = targets.get(link.get('target_place_id'))
        identity = (link.get('snapshot_id'), link.get('candidate_id'))
        if (identity in seen or not rank or not candidate or not target
                or candidate['place_id'] != target['place_id']
                or link.get('target_store_id') != target['target_store_id']
                or link.get('run_id') != rank['run_id'] or link.get('task_key') != rank['task_key']
                or link.get('profile') != PROFILE or rank.get('profile') != PROFILE
                or rank['device_type'] != 'MOBILE'
                or keyword_key(candidate['normalized_keyword']) != keyword_key(rank['normalized_query'])
                or link.get('normalized_query') != keyword_key(rank['normalized_query'])):
            raise ValueError('SHARED_RANK_LINK_MISMATCH')
        seen.add(identity)
