from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CREATE_SQL = ROOT / "sql" / "keyword_candidate_discovery" / "01_create_tables.sql"
VERIFY_SQL = ROOT / "sql" / "keyword_candidate_discovery" / "02_verify_tables.sql"


def test_create_sql_defines_candidate_evidence_contract():
    sql = CREATE_SQL.read_text(encoding="utf-8")

    assert "CREATE TABLE dbo.naver_keyword_discovery_review_term" in sql
    assert "CREATE TABLE dbo.naver_keyword_discovery_candidate" in sql
    for column in (
        "run_id",
        "source_type",
        "source_review_id",
        "brand_code",
        "place_id",
        "normalized_keyword",
        "candidate_scope",
        "candidate_status",
        "weighted_mention_score",
    ):
        assert column in sql
    assert "FK_naver_keyword_discovery_review_term_candidate" in sql
    assert "READY" in sql
    assert "INSUFFICIENT_EVIDENCE" in sql
    assert "REVIEW_REQUIRED" in sql
    assert "EXCLUDED" in sql


def test_create_sql_is_idempotent_and_indexes_lookup_paths():
    sql = CREATE_SQL.read_text(encoding="utf-8")

    assert sql.count("IF OBJECT_ID") >= 2
    assert "UQ_naver_keyword_discovery_candidate_run_scope_keyword" in sql
    assert "UQ_naver_keyword_discovery_review_term_run_source_keyword" in sql
    assert "IX_naver_keyword_discovery_candidate_place_status" in sql
    assert "IX_naver_keyword_discovery_review_term_place_keyword" in sql


def test_verify_sql_checks_tables_columns_constraints_and_indexes():
    sql = VERIFY_SQL.read_text(encoding="utf-8")

    assert "verified_table_count" in sql
    assert "verified_column_count" in sql
    assert "verified_constraint_count" in sql
    assert "verified_index_count" in sql
    assert "THROW" in sql
