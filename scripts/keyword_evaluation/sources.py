from __future__ import annotations

from datetime import timedelta

from .contracts import aware_time, keyword_key, PROFILE, STORE_PROFILE, LOCATION_PROFILES


def latest(rows, as_of, time_key, id_key):
    eligible = [row for row in rows if aware_time(row[time_key]) <= as_of]
    return max(eligible, key=lambda row: (aware_time(row[time_key]), row[id_key]), default=None)


def freshness(row, as_of, time_key, days):
    return as_of - aware_time(row[time_key]) <= timedelta(days=days)


def select_rank(rows, target, keyword, as_of, links=(), profile=PROFILE):
    from .store_location import same_location
    shared = {link['snapshot_id'] for link in links
              if link['target_store_id'] == target['target_store_id'] and link['target_place_id'] == target['place_id']}
    return latest([r for r in rows if (r['target_store_id'] == target['target_store_id'] or (profile == PROFILE and r['snapshot_id'] in shared))
                   and keyword_key(r['normalized_query']) == keyword_key(keyword)
                   and r['device_type'] == 'MOBILE' and r.get('profile') == profile
                   and (profile not in LOCATION_PROFILES or same_location(r, target))],
                  as_of, 'collected_at', 'snapshot_id')


def select_keywords(rows, place, as_of, rank_at, rules):
    relevant = [r for r in rows if r['place_id'] == place]
    attempt = latest(relevant, as_of, 'checked_at', 'snapshot_id')
    valid = latest([r for r in relevant if r['collect_status'] in ('SUCCESS', 'EMPTY')],
                   as_of, 'checked_at', 'snapshot_id')
    refs = {'place_id': place, 'latest_attempt_snapshot_id': attempt['snapshot_id'] if attempt else None,
            'selected_check_snapshot_id': valid['snapshot_id'] if valid else None,
            'effective_snapshot_id': valid.get('effective_snapshot_id') if valid else None}
    if not valid:
        return None, refs, 'KEYWORDLIST_MISSING'
    if attempt['collect_status'] not in ('SUCCESS', 'EMPTY'):
        return None, refs, 'STALE_FALLBACK'
    if (not freshness(valid, as_of, 'checked_at', rules['ttl_days'])
            or abs(aware_time(valid['checked_at'])-rank_at) > timedelta(days=rules['max_skew_days'])):
        return None, refs, 'STALE'
    effective = next((r for r in relevant if r['snapshot_id'] == valid.get('effective_snapshot_id')), None)
    if (not effective or effective['collect_status'] not in ('SUCCESS', 'EMPTY')
            or aware_time(effective['checked_at']) > aware_time(valid['checked_at'])):
        return None, refs, 'KEYWORDLIST_INVALID'
    words = effective.get('keywords', [])
    if (len(words) != effective['keyword_count'] or len(words) != valid['keyword_count']
            or (valid['collect_status'] == 'EMPTY') != (len(words) == 0)
            or len({keyword_key(w['normalized_keyword']) for w in words}) != len(words)
            or [w['keyword_order'] for w in words] != list(range(1, len(words)+1))):
        return None, refs, 'KEYWORDLIST_INVALID'
    return words, refs, None
