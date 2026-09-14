"""전체 매장 순위를 작은 SQL 묶음으로 읽는다. 실패도 최신 관측 그대로 보존한다."""
from datetime import timezone

from scripts.keyword_evaluation.contracts import LIST_PROFILE, keyword_key


def read_rank_observations(query, config, now):
    targets = {t['target_store_id']: t for t in config['targets']}
    wanted = [(t['target_store_id'], keyword_key(c['query']),
               t['search_location']['latitude'], t['search_location']['longitude'])
              for t in config['targets'] for c in config['candidates']]
    ranks = []
    for start in range(0, len(wanted), 50):
        batch = wanted[start:start+50]
        values = ','.join(['(%s,%s,%s,%s)']*len(batch))
        params = tuple(v for item in batch for v in item)+(LIST_PROFILE, now.replace(tzinfo=None))
        rows = query(f"""
            WITH wanted(target_store_id,normalized_query,latitude,longitude) AS (SELECT * FROM (VALUES {values}) v(a,b,c,d))
            SELECT s.* FROM wanted w CROSS APPLY (
              SELECT TOP 1 snapshot_id,run_id,target_store_id,normalized_query,device_type,
                     collect_status,collected_at,result_end_reached,latitude,longitude
              FROM dbo.naver_keyword_discovery_snapshot s
              WHERE s.target_store_id=w.target_store_id AND s.normalized_query=w.normalized_query
                AND s.device_type='MOBILE' AND s.location_name=%s
                AND ROUND(s.latitude,7)=ROUND(w.latitude,7) AND ROUND(s.longitude,7)=ROUND(w.longitude,7)
                AND s.collected_at<=%s
              ORDER BY s.collected_at DESC,s.snapshot_id DESC
            ) s""", params)
        for original in rows:
            r = dict(original)
            location = targets[r['target_store_id']]['search_location']
            r.update(run_id=str(r['run_id']), profile=LIST_PROFILE, results=[])
            observed_at = r['collected_at']
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            r['collected_at'] = observed_at.isoformat()
            r['search_location'] = dict(location, latitude=float(r.pop('latitude')), longitude=float(r.pop('longitude')))
            ranks.append(r)
    by_id = {r['snapshot_id']: r for r in ranks}
    ids = list(by_id)
    for start in range(0, len(ids), 500):
        batch = ids[start:start+500]
        placeholders = ','.join(['%s']*len(batch))
        for original in query(f"""SELECT snapshot_id,raw_position,organic_rank,place_id,place_name,category,is_ad
            FROM dbo.naver_keyword_discovery_result WHERE snapshot_id IN ({placeholders})
            ORDER BY snapshot_id,raw_position""", tuple(batch)):
            card = dict(original)
            by_id[card.pop('snapshot_id')]['results'].append(card)
    return ranks
