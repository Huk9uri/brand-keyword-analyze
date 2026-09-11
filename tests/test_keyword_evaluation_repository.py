import json
from pathlib import Path

import pytest

from scripts.keyword_evaluation.repository import EvaluationRepository, VolumeRepository, ReadOnlySource
from scripts.keyword_evaluation.pipeline import evaluate_bundle
from test_keyword_evaluation_engine import bundle


class Cursor:
    def __init__(self, fail=False):
        self.executions = []
        self.fail = fail
        self.identity = 0

    def execute(self, sql, params=()):
        self.executions.append((sql, params))
        if self.fail and 'INSERT INTO dbo.naver_keyword_evaluation_evidence' in sql:
            raise RuntimeError('synthetic error')

    def fetchone(self):
        self.identity += 1
        return (self.identity,)

    def fetchall(self):
        return []

    def close(self):
        pass


class Connection:
    def __init__(self, fail=False):
        self.c = Cursor(fail)
        self.commits = self.rollbacks = 0

    def cursor(self, **kwargs):
        return self.c

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_evaluation_saved_atomically_and_inputs_preserved():
    conn = Connection()
    evaluated = evaluate_bundle(bundle())
    result = EvaluationRepository(conn).save(evaluated)
    assert result['result_count'] == 5
    assert conn.commits == 1 and conn.rollbacks == 0
    assert any(evaluated['input_hash'] in params for _, params in conn.c.executions)
    assert all('CREATE ' not in sql for sql, _ in conn.c.executions)


def test_evidence_failure_rolls_back_entire_run():
    conn = Connection(fail=True)
    with pytest.raises(RuntimeError, match='평가 저장'):
        EvaluationRepository(conn).save(evaluate_bundle(bundle()))
    assert conn.commits == 0 and conn.rollbacks == 1


def test_source_only_selects_requested_run_with_parameters():
    conn = Connection()
    rows = ReadOnlySource(conn).candidates('00000000-0000-0000-0000-000000000001', '100')
    assert rows == []
    sql, params = conn.c.executions[0]
    assert sql.lstrip().startswith('SELECT') and '%s' in sql
    assert '100' in params
    assert conn.commits == 0


def test_volume_storage_uses_snapshot_table_and_preserves_raw_type():
    conn = Connection()
    rows = bundle()['volumes']
    VolumeRepository(conn).save(rows)
    assert conn.commits == 1
    assert all('naver_keyword_search_volume_snapshot' in sql for sql, _ in conn.c.executions)
    assert any('monthlyPcQcCnt' in str(p) for _, params in conn.c.executions for p in params)


def test_schema_separates_volume_and_evaluation_and_has_integrity():
    sql = Path('sql/keyword_evaluation/01_create_tables.sql').read_text(encoding='utf-8')
    for table in ('naver_keyword_search_volume_snapshot', 'naver_keyword_evaluation_run',
                  'naver_keyword_evaluation_result', 'naver_keyword_evaluation_evidence', 'naver_keyword_evaluation_review'):
        assert f'CREATE TABLE dbo.{table}' in sql
    assert 'FOREIGN KEY (volume_snapshot_id)' in sql
    assert 'ISJSON' in sql
    assert 'ALTER TABLE dbo.naver_keyword_discovery_candidate' not in sql
