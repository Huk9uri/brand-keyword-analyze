"""좌표는 검색 조건으로만 사용하며 평가 점수에는 사용하지 않는다."""
import math

from .contracts import PROFILE, STORE_PROFILE, LOCATION_PROFILES, aware_time


def rank_profile(data):
    profile = data.get('rank_profile', PROFILE)
    if profile not in (PROFILE, *LOCATION_PROFILES):
        raise ValueError('INVALID_RANK_PROFILE')
    return profile


def validate_location(location, place, as_of):
    if not isinstance(location, dict) or set(location) != {'latitude', 'longitude', 'place_id', 'source', 'verified_at'}:
        raise ValueError('SEARCH_LOCATION_MISSING_OR_INVALID')
    lat, lon = location['latitude'], location['longitude']
    if (type(lat) not in (float, int) or type(lon) not in (float, int)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not 33 <= lat <= 39 or not 124 <= lon <= 132
            or location['place_id'] != place or not location['source']):
        raise ValueError('SEARCH_LOCATION_INVALID')
    if aware_time(location['verified_at']) > as_of:
        raise ValueError('SEARCH_LOCATION_FUTURE')


def validate_locations(data):
    profile = rank_profile(data)
    permitted = set()
    as_of = aware_time(data['as_of_at'])
    for target in data['targets']:
        location = target.get('search_location')
        if profile in LOCATION_PROFILES:
            validate_location(location, target['place_id'], as_of)
            permitted.add(id(location))
    for rank in data['ranks']:
        location = rank.get('search_location')
        if location is not None and rank.get('profile') in LOCATION_PROFILES:
            # 미래 관측도 입력에 보존하지만 기준 시점 이후의 관측은 선택하지 않는다.
            validate_location(location, location.get('place_id'), aware_time(rank['collected_at']))
            permitted.add(id(location))
    return permitted


def same_location(rank, target):
    observed, expected = rank.get('search_location'), target.get('search_location')
    return bool(observed and expected and observed['place_id'] == target['place_id']
                and all(round(observed[k], 7) == round(expected[k], 7) for k in ('latitude', 'longitude')))
