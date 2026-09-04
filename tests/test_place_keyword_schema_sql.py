import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CREATE_SQL = ROOT / "sql" / "place_keyword_collector" / "01_create_tables.sql"
VERIFY_SQL = ROOT / "sql" / "place_keyword_collector" / "02_verify_tables.sql"


SNAPSHOT_COLUMNS = {
    "snapshot_id": "bigint",
    "run_id": "uniqueidentifier",
    "rank_run_id": "uniqueidentifier",
    "place_id": "varchar(50)",
    "place_name": "nvarchar(300)",
    "source_url": "nvarchar(2000)",
    "collect_status": "varchar(30)",
    "collect_method": "varchar(20)",
    "content_hash": "char(64)",
    "is_changed": "bit",
    "effective_snapshot_id": "bigint",
    "keyword_count": "smallint",
    "parser_version": "varchar(30)",
    "collect_msg": "nvarchar(1000)",
    "checked_at": "datetime2(3)",
}

RESULT_COLUMNS = {
    "snapshot_id": "bigint",
    "keyword_order": "smallint",
    "raw_keyword": "nvarchar(255)",
    "normalized_keyword": "nvarchar(255)",
}


def _normalized(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower()).strip()


def _table_body(sql: str, table: str) -> str:
    match = re.search(
        rf"create\s+table\s+{re.escape(table)}\s*\((.*?)^\s*\)\s*;",
        sql,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing CREATE TABLE for {table}"
    return match.group(1)


def _declared_columns(body: str) -> dict[str, str]:
    columns = {}
    for line in body.splitlines():
        declaration = line.strip().rstrip(",").lower()
        if not declaration or declaration.startswith(("constraint ", "foreign ", "references ", "check ", "unique ")):
            continue
        name, sql_type, *_ = declaration.split()
        columns[name.strip("[]")] = sql_type
    return columns


def test_create_sql_defines_exactly_the_snapshot_and_result_tables():
    sql = CREATE_SQL.read_text(encoding="utf-8")
    created_tables = re.findall(r"create\s+table\s+([\w.]+)", sql, flags=re.IGNORECASE)

    assert [table.lower() for table in created_tables] == [
        "dbo.naver_place_keyword_snapshot",
        "dbo.naver_place_keyword_result",
    ]
    assert _declared_columns(_table_body(sql, created_tables[0])) == SNAPSHOT_COLUMNS
    assert _declared_columns(_table_body(sql, created_tables[1])) == RESULT_COLUMNS
    assert "snapshot_id bigint identity(1,1)" in _normalized(CREATE_SQL)


def test_create_sql_enforces_snapshot_versions_and_keyword_rows():
    sql = _normalized(CREATE_SQL)

    assert "primary key (snapshot_id)" in sql
    assert "unique (run_id, place_id)" in sql
    assert "unique (snapshot_id, keyword_order)" in sql
    assert (
        "foreign key (effective_snapshot_id) references "
        "dbo.naver_place_keyword_snapshot(snapshot_id)"
    ) in sql
    assert (
        "foreign key (snapshot_id) references "
        "dbo.naver_place_keyword_snapshot(snapshot_id)"
    ) in sql
    assert (
        "check (collect_status in "
        "('success','empty','blocked','load_timeout','place_mismatch','parse_error'))"
    ) in sql
    assert "check (keyword_count >= 0)" in sql
    assert "check (keyword_order >= 1)" in sql


def test_create_sql_is_idempotent_and_indexes_required_lookup_paths():
    sql = _normalized(CREATE_SQL)

    for table in (
        "dbo.naver_place_keyword_snapshot",
        "dbo.naver_place_keyword_result",
    ):
        assert f"object_id(n'{table}', n'u') is null" in sql

    for index_name, table, columns in (
        (
            "ix_naver_place_keyword_snapshot_place_checked_at",
            "dbo.naver_place_keyword_snapshot",
            "place_id, checked_at desc",
        ),
        (
            "ix_naver_place_keyword_snapshot_rank_run_id",
            "dbo.naver_place_keyword_snapshot",
            "rank_run_id",
        ),
        (
            "ix_naver_place_keyword_snapshot_effective_snapshot_id",
            "dbo.naver_place_keyword_snapshot",
            "effective_snapshot_id",
        ),
        (
            "ix_naver_place_keyword_result_snapshot_keyword_order",
            "dbo.naver_place_keyword_result",
            "snapshot_id, keyword_order",
        ),
    ):
        assert f"create index {index_name} on {table}({columns})" in sql
        assert f"name = n'{index_name}'" in sql


def test_verify_sql_rejects_any_schema_contract_mismatch_read_only():
    sql = _normalized(VERIFY_SQL)

    for table in (
        "dbo.naver_place_keyword_snapshot",
        "dbo.naver_place_keyword_result",
    ):
        assert f"object_id(n'{table}', n'u') is null" in sql
    for catalog in (
        "sys.columns",
        "sys.key_constraints",
        "sys.foreign_keys",
        "sys.check_constraints",
        "sys.indexes",
    ):
        assert catalog in sql
    assert "index_columns.is_descending_key" in sql
    assert sql.count("throw") >= 5
    for banned in ("create table", "create index", "alter table", "drop ", "delete ", "update "):
        assert banned not in sql


def test_verify_sql_uses_sql_server_datetime2_metadata_precision():
    sql = _normalized(VERIFY_SQL)

    assert (
        "(n'naver_place_keyword_snapshot', n'checked_at', "
        "n'datetime2', 7, 23, 3, 0, 0)"
    ) in sql


def test_verify_sql_compares_allowed_status_values_without_predicate_order():
    sql = _normalized(VERIFY_SQL)

    assert "declare @expected_status_values table" in sql
    assert "actual_status_literal_count" in sql
    assert "expected_status_values" in sql
    assert "len(replace" in sql
    for status in (
        "success",
        "empty",
        "blocked",
        "load_timeout",
        "place_mismatch",
        "parse_error",
    ):
        assert f"n'{status}'" in sql


def test_verify_sql_requires_constraints_and_indexes_to_be_enabled_and_trusted():
    sql = _normalized(VERIFY_SQL)

    for catalog_expression in (
        "foreign_keys.is_disabled",
        "foreign_keys.is_not_trusted",
        "check_constraints.is_disabled",
        "check_constraints.is_not_trusted",
        "indexes.is_disabled",
    ):
        assert catalog_expression in sql
