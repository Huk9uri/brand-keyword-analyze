from datetime import datetime

import pytest

from scripts.keyword_evaluation.source_export import source_time, export_bundle
from test_keyword_evaluation_engine import bundle


def test_source_timezone_requires_explicit_offset():
    assert source_time(datetime(2026, 9, 9, 10), '+09:00') == '2026-09-09T01:00:00+00:00'
    with pytest.raises(ValueError, match='TIMEZONE'):
        source_time(datetime(2026, 9, 9, 10), None)


def test_export_uses_fixed_candidate_run_and_does_not_adopt_stale_rank(monkeypatch):
    data = bundle()
    class Source:
        def __init__(self, conn): pass
        def candidates(self, run, place): return data['candidates']
        def reviews(self, run, place): return []
        def volumes(self, key): return []
        def ranks(self, run): return []
        def keywords(self, place): return []
        def query(self, sql, params): return []
    monkeypatch.setattr('scripts.keyword_evaluation.source_export.ReadOnlySource', Source)
    config = dict(bundle=data, candidate_time_offset='+09:00', keyword_time_offset='+09:00',
                  rank_runs=[], verified_volume_periods=[])
    result = export_bundle(None, config)
    assert result['ranks'] == []
    assert result['targets'][0]['operation_status'] == 'CONFLICT'
    assert result['volumes'] == []


def test_explicit_operation_conflict_survives_consistent_identity(monkeypatch):
    data = bundle()
    data['targets'][0]['operation_status'] = 'CONFLICT'
    class Source:
        def __init__(self, conn): pass
        def candidates(self, run, place): return data['candidates']
        def reviews(self, run, place): return []
        def volumes(self, key): return []
        def ranks(self, run): return []
        def keywords(self, place): return []
        def query(self, sql, params): return [{'BRAND_CODE':'001','PLACE_ID_STATUS':'CONSISTENT'}]
    monkeypatch.setattr('scripts.keyword_evaluation.source_export.ReadOnlySource', Source)
    result = export_bundle(None, dict(bundle=data, rank_runs=[], verified_volume_periods=[]))
    assert result['targets'][0]['operation_status'] == 'CONFLICT'


def test_keyword_timezones_are_selected_per_collection_run(monkeypatch):
    data = bundle()
    class Source:
        def __init__(self, conn): pass
        def candidates(self, run, place): return data['candidates']
        def reviews(self, run, place): return []
        def volumes(self, key): return []
        def ranks(self, run): return data['ranks']
        def keywords(self, place):
            return [dict(run_id='new',snapshot_id=int(place),place_id=place,checked_at=datetime(2026,9,9,1))]
        def query(self, sql, params): return []
    monkeypatch.setattr('scripts.keyword_evaluation.source_export.ReadOnlySource', Source)
    config=dict(bundle=data,rank_runs=[dict(run_id='r',profile='MOBILE_NO_LOCATION_ORGANIC20_V2',time_offset='+00:00')],
                keyword_time_offset='+09:00',keyword_run_time_offsets={'new':'+00:00'})
    result=export_bundle(None,config)
    assert result['keyword_snapshots'][0]['checked_at'] == '2026-09-09T01:00:00+00:00'
