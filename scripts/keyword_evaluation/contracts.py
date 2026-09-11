from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

VERSION = 'keyword-evaluation-v1'
PROFILE = 'MOBILE_NO_LOCATION_ORGANIC20_V2'
STORE_PROFILE = 'MOBILE_STORE_LOCATION_ORGANIC20_V3'
LIST_PROFILE = 'MOBILE_PLACE_LIST_STORE_LOCATION_ORGANIC20_V4'
LOCATION_PROFILES = (STORE_PROFILE, LIST_PROFILE)
DEFAULT_RULES = {
    'demand_floor': 10, 'high_demand_floor': 100, 'high_percentile': .75,
    'direct_low': .30, 'direct_high': .60, 'keyword_low': .20, 'keyword_high': .50,
    'review_min': 3, 'ttl_days': 7, 'max_skew_days': 7, 'top_n': 10, 'budget': 20,
}


def keyword_key(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('키워드는 문자열이어야 합니다')
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


def searchad_key(value: str) -> str:
    return re.sub(r'\s+', '', value).casefold()


def place_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,50}', value.strip()):
        raise ValueError('INVALID_PLACE_ID')
    return value.strip()


def aware_time(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('TIMEZONE_UNVERIFIED')
    return result.astimezone(timezone.utc)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(type(value).__name__)


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False, default=_json_default)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def percentile(value, population):
    if len(population) < 5 or len(set(population)) < 2:
        return None
    return (sum(x < value for x in population) + .5 * sum(x == value for x in population)) / len(population)


def settings(overrides: dict) -> dict:
    if set(overrides) - set(DEFAULT_RULES):
        raise ValueError('UNKNOWN_RULE_SETTING')
    result = DEFAULT_RULES | overrides
    for key, value in result.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError('INVALID_RULE_SETTING')
    for key in ('high_percentile', 'direct_low', 'direct_high', 'keyword_low', 'keyword_high'):
        if not 0 <= result[key] <= 1:
            raise ValueError('INVALID_RULE_SETTING')
    for key in ('review_min', 'ttl_days', 'max_skew_days', 'top_n', 'budget'):
        if type(result[key]) is not int or result[key] < 1:
            raise ValueError('INVALID_RULE_SETTING')
    if result['top_n'] != 10 or result['budget'] > 20:
        raise ValueError('PILOT_SCOPE_EXCEEDED')
    if result['direct_low'] >= result['direct_high'] or result['keyword_low'] >= result['keyword_high']:
        raise ValueError('RULE_CONFLICT')
    return result
