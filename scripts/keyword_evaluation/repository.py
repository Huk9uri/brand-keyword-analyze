from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4, UUID

from .contracts import canonical, digest, aware_time, searchad_key


def _insert(cursor, table, values, identity=None):
    # 테이블·컬럼은 이 모듈 내 상수에서만 생성하며 사용자 SQL을 받지 않는다.
    columns = ', '.join(values)
    output = f' OUTPUT INSERTED.{identity}' if identity else ''
    cursor.execute(f"INSERT INTO dbo.{table} ({columns}){output} VALUES ({', '.join('%s' for _ in values)})",
                   tuple(values.values()))
    if identity:
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError('저장 ID가 반환되지 않았습니다')
        return int(row[0])


class EvaluationRepository:
    def __init__(self, connection):
        self.connection = connection

    def save(self, evaluated):
        from .pipeline import evaluate_bundle
        if canonical(evaluate_bundle(evaluated['input_manifest'])) != canonical(evaluated):
            raise ValueError('EVALUATION_REPLAY_MISMATCH')
        run_id, now = str(uuid4()), datetime.now(timezone.utc).isoformat()
        cursor = self.connection.cursor()
        identities = {}
        try:
            _insert(cursor, 'naver_keyword_evaluation_run', dict(
                evaluation_run_id=run_id, as_of_at=evaluated['as_of_at'], calculation_version=evaluated['calculation_version'],
                input_manifest_json=canonical(evaluated['input_manifest']), rules_json=canonical(evaluated['rules']),
                input_hash=evaluated['input_hash'], created_at=now))
            for result in evaluated['results']:
                values = {k: result[k] for k in ('candidate_id', 'target_place_id', 'normalized_keyword',
                                                'volume_snapshot_id', 'rank_snapshot_id', 'final_class')}
                values.update(evaluation_run_id=run_id, created_at=now)
                for key in ('raw_scores', 'normalized_scores', 'gate_results', 'reason_codes', 'quality'):
                    values[key+'_json'] = canonical(result[key])
                result_id = _insert(cursor, 'naver_keyword_evaluation_result', values, 'evaluation_result_id')
                identities[result['candidate_id']] = result_id
                for i, evidence in enumerate(result['evidence'], 1):
                    _insert(cursor, 'naver_keyword_evaluation_evidence', dict(
                        evaluation_result_id=result_id, evidence_no=i, evidence_type=evidence['evidence_type'],
                        source_refs_json=canonical(evidence['source_refs']),
                        observed_values_json=canonical({'value': evidence['observed_values']}),
                        decision_json=canonical(evidence['decision'])))
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise RuntimeError('평가 저장 실패: 실행 전체를 rollback했습니다') from None
        finally:
            cursor.close()
        return {'evaluation_run_id': run_id, 'result_count': len(identities), 'result_ids': identities}

    def save_reviews(self, reviews):
        allowed = {'dining_intent': {'DINING','MIXED','NON_DINING','UNKNOWN'}, 'store_fit': {'PASS','FAIL','UNKNOWN'},
                   'competition_type': {'DIRECT','INDIRECT','MIXED','NONE','UNKNOWN'},
                   'market_type': {'VACANT','COMPETITIVE','EXCLUDED','REVIEW_REQUIRED'},
                   'recommendation': {'YES','NO','HOLD'}, 'confidence': {'HIGH','MEDIUM','LOW'}}
        for r in reviews:
            if any(r.get(k) not in choices for k, choices in allowed.items()) or not r.get('reason', '').strip() or not r.get('reviewer', '').strip():
                raise ValueError('INVALID_HUMAN_REVIEW')
            aware_time(r['reviewed_at'])
        cursor = self.connection.cursor()
        try:
            ids = [_insert(cursor, 'naver_keyword_evaluation_review',
                           {k: r[k] for k in ('evaluation_result_id','reviewer','reviewed_at',*allowed,'reason')}, 'review_id')
                   for r in reviews]
            self.connection.commit()
            return ids
        except Exception:
            self.connection.rollback()
            raise RuntimeError('사람 판정 저장 실패') from None
        finally:
            cursor.close()


class VolumeRepository:
    def __init__(self, connection):
        self.connection = connection

    def save(self, observations):
        from .volume import parse_volume, validate_period
        seen = set()
        for row in observations:
            validate_period({k:row[k] for k in ('period_type','period_definition','period_start','period_end') if k in row})
            key = (row['provider'], row['searchad_lookup_key'])
            if key in seen:
                raise ValueError('DUPLICATE_VOLUME_KEY')
            seen.add(key)
            if row['observation_status'] in ('EXACT','CENSORED','NOT_PROVIDED'):
                parsed = parse_volume(row['request_keyword'], row['response_json'])
                if any(parsed[k] != row[k] for k in ('observation_status','pc_count','mobile_count','total_count','raw_pc','raw_mobile')):
                    raise ValueError('VOLUME_RESPONSE_MISMATCH')
        run_id = str(uuid4())
        cursor = self.connection.cursor()
        ids = []
        try:
            for row in observations:
                aware_time(row['fetched_at'])
                values = {k: row.get(k) for k in ('request_keyword','response_keyword','searchad_lookup_key','provider',
                          'fetched_at','period_type','period_start','period_end','period_definition',
                          'pc_count','mobile_count','total_count','observation_status','response_hash','failure_code','parser_version')}
                values.update(collection_run_id=run_id, raw_pc=None if row['raw_pc'] is None else str(row['raw_pc']),
                              raw_mobile=None if row['raw_mobile'] is None else str(row['raw_mobile']),
                              response_json=canonical(row['response_json']) if row['response_json'] is not None else None)
                ids.append(_insert(cursor, 'naver_keyword_search_volume_snapshot', values, 'volume_snapshot_id'))
            self.connection.commit()
            return {'collection_run_id': run_id, 'volume_snapshot_ids': ids}
        except Exception:
            self.connection.rollback()
            raise RuntimeError('검색량 저장 실패: 실행 전체를 rollback했습니다') from None
        finally:
            cursor.close()


class ReadOnlySource:
    """읽기 API에는 동적 SQL이나 DDL 실행 경로가 없다."""
    def __init__(self, connection):
        self.connection = connection

    def query(self, sql, params=()):
        if not sql.lstrip().upper().startswith('SELECT'):
            raise ValueError('SELECT_ONLY')
        cursor = self.connection.cursor(as_dict=True)
        try:
            cursor.execute(sql, params)
            return list(cursor.fetchall())
        finally:
            cursor.close()

    def candidates(self, run_id, place):
        return self.query('SELECT * FROM dbo.naver_keyword_discovery_candidate WHERE run_id=%s AND place_id=%s AND candidate_scope=%s',
                          (str(UUID(run_id)), place, 'STORE'))

    def reviews(self, run_id, place):
        return self.query("""SELECT r.*, COALESCE(b.collect_status,v.collect_status) source_collect_status,
            COALESCE(b.context,v.context) source_context
            FROM dbo.naver_keyword_discovery_review_term r
            LEFT JOIN dbo.naver_review_blog b ON r.source_type='BLOG' AND b.review_blog_id=r.source_review_id
            LEFT JOIN dbo.naver_review_visitor v ON r.source_type='VISITOR' AND v.review_visitor_id=r.source_review_id
            WHERE r.run_id=%s AND r.place_id=%s""", (str(UUID(run_id)), place))

    def ranks(self, run_id):
        # 좌표는 검색 위치 확인에만 사용한다. 결과 카드의 거리는 조회하지 않는다.
        snapshots = self.query("""SELECT snapshot_id,run_id,task_key,normalized_query,target_store_id,
            device_type,collect_status,collected_at,result_end_reached,requested_result_limit,observed_result_count,
            location_name,latitude,longitude
            FROM dbo.naver_keyword_discovery_snapshot WHERE run_id=%s""", (str(UUID(run_id)),))
        for row in snapshots:
            row['results'] = self.query('''SELECT raw_position,organic_rank,place_id,place_name,category,is_ad
                FROM dbo.naver_keyword_discovery_result WHERE snapshot_id=%s ORDER BY raw_position''', (row['snapshot_id'],))
        return snapshots

    def keywords(self, place):
        snapshots = self.query('''SELECT snapshot_id,run_id,effective_snapshot_id,place_id,collect_status,keyword_count,checked_at
            FROM dbo.naver_place_keyword_snapshot WHERE place_id=%s''', (place,))
        for row in snapshots:
            row['keywords'] = self.query('''SELECT keyword_order,raw_keyword,normalized_keyword
                FROM dbo.naver_place_keyword_result WHERE snapshot_id=%s ORDER BY keyword_order''', (row['snapshot_id'],))
        return snapshots

    def volumes(self, key):
        return self.query('''SELECT * FROM dbo.naver_keyword_search_volume_snapshot
            WHERE provider=%s AND searchad_lookup_key=%s ORDER BY fetched_at DESC,volume_snapshot_id DESC''', ('NAVER_SEARCHAD', key))
