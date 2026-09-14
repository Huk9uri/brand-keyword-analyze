"""운영 매장 모집단을 보존하고 조사 가능 여부를 판정한다."""
from collections import Counter
from copy import deepcopy
from datetime import timezone

from scripts.keyword_evaluation.store_location import validate_location


# 매장 뷰에서 누락될 수 있는 신규 매장도 ERP 모집단에 남긴다.
INVENTORY_SQL = """
WITH stores AS (
 SELECT LTRIM(RTRIM(CD_STORE)) STORE_CODE, MAX(NM_STORE) ERP_STORE_NAME
 FROM SEIERP_IYN_BAK.dbo.FROP_STORE
 WHERE CD_CORP=N'01' AND CD_BRAND=N'001' AND CD_TYPE1=N'001'
   AND CD_OPERATION=N'002' AND ISNULL(RTRIM(DT_CLOSE),N'')=N''
   AND NULLIF(LTRIM(RTRIM(CD_STORE)),N'') IS NOT NULL
 GROUP BY LTRIM(RTRIM(CD_STORE))
)
SELECT e.STORE_CODE,e.ERP_STORE_NAME,s.NAVER_STORE_NAME,s.NAVER_PLACE_ID,s.PLACE_ID_STATUS,
       l.latitude,l.longitude,l.verified_at,l.resolver_version
FROM stores e LEFT JOIN dbo.vw_naver_store_hours_targets s
 ON s.BRAND_CODE=N'001' AND s.STORE_CODE=e.STORE_CODE
LEFT JOIN dbo.naver_place_location l ON l.place_id=s.NAVER_PLACE_ID
ORDER BY e.STORE_CODE
"""


def _text(value):
    return '' if value is None else str(value).strip()


def build_inventory(records, config, as_of):
    overrides = {t['place_id']: t for t in config.get('targets', [])}
    groups = {}
    for row in records:
        code = _text(row['STORE_CODE'])
        if not code:
            raise ValueError('STORE_CODE_MISSING')
        groups.setdefault(code, []).append(row)
    inventory = []
    for code, records_for_store in sorted(groups.items()):
        row = records_for_store[0]
        place = _text(row.get('NAVER_PLACE_ID')) or None
        override = overrides.get(place, {})
        item = dict(store_code=code, store_name=_text(row.get('NAVER_STORE_NAME')) or _text(row.get('ERP_STORE_NAME')) or code,
                    place_id=place, target_store_id=override.get('target_store_id', 'IYN-'+code),
                    status='ELIGIBLE', search_location=None)
        identities = {(_text(r.get('NAVER_PLACE_ID')), _text(r.get('PLACE_ID_STATUS'))) for r in records_for_store}
        if not place:
            item['status'] = 'PLACE_ID_MISSING'
        elif len(identities) != 1 or row.get('PLACE_ID_STATUS') != 'CONSISTENT' or not place.isascii() or not place.isdigit():
            item['status'] = 'PLACE_ID_UNVERIFIED'
        else:
            location = deepcopy(override.get('search_location'))
            try:
                if not location and all(row.get(k) is not None for k in ('latitude', 'longitude', 'verified_at')):
                    verified = row['verified_at']
                    if verified.tzinfo is None:
                        verified = verified.replace(tzinfo=timezone.utc)
                    location = dict(latitude=float(row['latitude']), longitude=float(row['longitude']),
                                    place_id=place, source=row.get('resolver_version') or 'naver_place_location',
                                    verified_at=verified.isoformat())
                if location:
                    validate_location(location, place, as_of)
                    item['search_location'] = location
                else:
                    item['status'] = 'LOCATION_MISSING'
            except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
                item['status'] = 'LOCATION_INVALID'
        inventory.append(item)
    counts = Counter(r['place_id'] for r in inventory if r['place_id'])
    for item in inventory:
        if item['place_id'] and counts[item['place_id']] > 1:
            item.update(status='DUPLICATE_PLACE_ID', search_location=None)
    return inventory


def config_from_inventory(config, inventory):
    resolved = deepcopy(config)
    resolved['scope'] = 'ALL_STORES'
    resolved['targets'] = [{k: r[k] for k in ('store_code', 'store_name', 'place_id', 'target_store_id', 'search_location')}
                           for r in inventory if r['status'] == 'ELIGIBLE']
    return resolved


def configure_all_stores(config, records, as_of):
    inventory = build_inventory(records, config, as_of)
    return config_from_inventory(config, inventory), inventory
