from __future__ import annotations

import re
from datetime import date

from .contracts import canonical, digest, searchad_key


def validate_period(period):
    allowed = {'period_type','period_definition','period_start','period_end','period_verified'}
    if (set(period)-allowed or period.get('period_type') not in ('UNVERIFIED','PROVIDER_MONTHLY','EXACT_30D')
            or not isinstance(period.get('period_definition'), str)):
        raise ValueError('INVALID_PERIOD_METADATA')
    if period['period_type'] != 'UNVERIFIED' and not period['period_definition'].strip():
        raise ValueError('PERIOD_EVIDENCE_REQUIRED')
    start, end = period.get('period_start'), period.get('period_end')
    if bool(start) != bool(end):
        raise ValueError('INVALID_PERIOD_DATES')
    if start and date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError('INVALID_PERIOD_DATES')
    if period['period_type'] == 'EXACT_30D' and (not start or (date.fromisoformat(end)-date.fromisoformat(start)).days != 29):
        raise ValueError('INVALID_PERIOD_30D')


def _channel(value):
    if type(value) is int and 0 <= value <= 9223372036854775807:
        return value, [value, value], 'EXACT'
    if isinstance(value, str) and re.fullmatch(r'<\s*10', value.strip()):
        return None, [0, 9], 'CENSORED'
    return None, None, 'INVALID'


def parse_volume(keyword: str, payload: dict) -> dict:
    result = dict(request_keyword=keyword, response_keyword=None, searchad_lookup_key=searchad_key(keyword),
                  provider='NAVER_SEARCHAD', raw_pc=None, raw_mobile=None,
                  pc_count=None, mobile_count=None, total_count=None,
                  pc_interval=None, mobile_interval=None, total_interval=None,
                  observation_status='INVALID', response_json=None, response_hash=None,
                  failure_code=None, parser_version='search-volume-v1')
    if not isinstance(payload, dict) or not isinstance(payload.get('keywordList'), list):
        result['failure_code'] = 'INVALID_RESPONSE'
        return result
    rows = payload['keywordList']
    if any(not isinstance(row, dict) or not isinstance(row.get('relKeyword'), str) for row in rows):
        result['failure_code'] = 'INVALID_RESPONSE'
        return result
    matched = [row for row in rows if searchad_key(row['relKeyword']) == searchad_key(keyword)]
    if not matched:
        result.update(observation_status='NOT_PROVIDED', response_json={'keywordList': []})
        result['response_hash'] = digest(result['response_json'])
        return result
    safe = [{key: row.get(key) for key in ('relKeyword', 'monthlyPcQcCnt', 'monthlyMobileQcCnt')}
            for row in matched]
    result.update(response_json={'keywordList': safe}, response_hash=digest(safe))
    if len({canonical(row) for row in safe}) > 1:
        result['failure_code'] = 'DUPLICATE_RESPONSE_CONFLICT'
        return result
    row = safe[0]
    pc, pi, ps = _channel(row['monthlyPcQcCnt'])
    mobile, mi, ms = _channel(row['monthlyMobileQcCnt'])
    status = 'INVALID' if 'INVALID' in (ps, ms) else 'CENSORED' if 'CENSORED' in (ps, ms) else 'EXACT'
    total = pc + mobile if status == 'EXACT' else None
    if total is not None and total > 9223372036854775807:
        total, status = None, 'INVALID'
    result.update(response_keyword=row['relKeyword'], raw_pc=row['monthlyPcQcCnt'],
                  raw_mobile=row['monthlyMobileQcCnt'], pc_count=pc, mobile_count=mobile,
                  total_count=total, pc_interval=pi, mobile_interval=mi,
                  total_interval=[pi[0]+mi[0], pi[1]+mi[1]] if pi and mi else None,
                  observation_status=status)
    return result
