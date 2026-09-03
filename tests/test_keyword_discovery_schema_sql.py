import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
CREATE_SQL = ROOT / "sql" / "keyword_discovery_rank" / "01_create_tables.sql"
VERIFY_SQL = ROOT / "sql" / "keyword_discovery_rank" / "02_verify_tables.sql"
LOCATION_CREATE_SQL = ROOT / "sql" / "keyword_discovery_rank" / "03_create_place_location.sql"
LOCATION_VERIFY_SQL = ROOT / "sql" / "keyword_discovery_rank" / "04_verify_place_location.sql"


SNAPSHOT_COLUMNS = {
    "snapshot_id": "bigint",
    "run_id": "uniqueidentifier",
    "task_key": "char(64)",
    "query": "nvarchar(255)",
    "normalized_query": "nvarchar(255)",
    "target_store_id": "nvarchar(100)",
    "target_store_name": "nvarchar(200)",
    "location_name": "nvarchar(200)",
    "latitude": "decimal(10,7)",
    "longitude": "decimal(10,7)",
    "device_type": "varchar(10)",
    "source_type": "varchar(20)",
    "source_id": "nvarchar(100)",
    "requested_result_limit": "smallint",
    "observed_result_count": "smallint",
    "result_end_reached": "bit",
    "collect_status": "varchar(30)",
    "collect_msg": "nvarchar(1000)",
    "parser_version": "varchar(30)",
    "final_url": "nvarchar(2000)",
    "collected_at": "datetime2(0)",
}

RESULT_COLUMNS = {
    "snapshot_id": "bigint",
    "raw_position": "smallint",
    "organic_rank": "smallint",
    "place_id": "varchar(50)",
    "place_name": "nvarchar(300)",
    "category": "nvarchar(300)",
    "is_ad": "bit",
    "detail_url": "nvarchar(2000)",
    "distance_text": "nvarchar(100)",
    "is_own_store": "bit",
    "matched_store_id": "nvarchar(100)",
    "match_method": "varchar(30)",
}

LOOKUP_INDEXES = {
    "ix_naver_keyword_discovery_snapshot_query_collected_at": (
        "dbo.naver_keyword_discovery_snapshot",
        "query, collected_at",
    ),
    "ix_naver_keyword_discovery_snapshot_target_store_id_collected_at": (
        "dbo.naver_keyword_discovery_snapshot",
        "target_store_id, collected_at",
    ),
    "ix_naver_keyword_discovery_snapshot_collect_status_collected_at": (
        "dbo.naver_keyword_discovery_snapshot",
        "collect_status, collected_at",
    ),
    "ix_naver_keyword_discovery_snapshot_run_id": (
        "dbo.naver_keyword_discovery_snapshot",
        "run_id",
    ),
    "ix_naver_keyword_discovery_result_place_id_snapshot_id": (
        "dbo.naver_keyword_discovery_result",
        "place_id, snapshot_id",
    ),
    "ix_naver_keyword_discovery_result_snapshot_id_is_ad_organic_rank": (
        "dbo.naver_keyword_discovery_result",
        "snapshot_id, is_ad, organic_rank",
    ),
    "ix_naver_keyword_discovery_result_is_own_store_matched_store_id": (
        "dbo.naver_keyword_discovery_result",
        "is_own_store, matched_store_id",
    ),
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
        if not declaration or declaration.startswith("constraint "):
            continue
        name, sql_type, *_ = declaration.split()
        columns[name.strip("[]")] = sql_type
    return columns


def test_create_script_defines_exactly_the_two_approved_tables_and_columns():
    sql = CREATE_SQL.read_text(encoding="utf-8")
    created_tables = re.findall(r"create\s+table\s+([\w.]+)", sql, flags=re.IGNORECASE)

    assert [table.lower() for table in created_tables] == [
        "dbo.naver_keyword_discovery_snapshot",
        "dbo.naver_keyword_discovery_result",
    ]
    assert _declared_columns(_table_body(sql, created_tables[0])) == SNAPSHOT_COLUMNS
    assert _declared_columns(_table_body(sql, created_tables[1])) == RESULT_COLUMNS
    assert "snapshot_id bigint identity(1,1)" in _normalized(CREATE_SQL)


def test_create_script_defines_approved_keys_checks_and_filtered_rank_uniqueness():
    sql = _normalized(CREATE_SQL)

    assert "primary key (snapshot_id)" in sql
    assert "unique (run_id, task_key)" in sql
    assert "primary key (snapshot_id, raw_position)" in sql
    assert (
        "foreign key (snapshot_id) references dbo.naver_keyword_discovery_snapshot(snapshot_id)"
        in sql
    )
    for check in (
        "check (device_type in ('mobile', 'pc'))",
        "check (source_type in ('excel', 'database'))",
        "check (latitude between -90 and 90)",
        "check (longitude between -180 and 180)",
        "check (observed_result_count >= 0)",
        "check (raw_position >= 1)",
        "check (organic_rank is null or organic_rank >= 1)",
    ):
        assert check in sql

    assert (
        "create unique index ux_naver_keyword_discovery_result_snapshot_organic_rank "
        "on dbo.naver_keyword_discovery_result(snapshot_id, organic_rank) "
        "where organic_rank is not null"
    ) in sql


def test_create_script_defines_exactly_seven_approved_lookup_indexes():
    sql = _normalized(CREATE_SQL)
    created_lookup_indexes = re.findall(r"create index ([a-z0-9_]+)", sql)

    assert set(created_lookup_indexes) == set(LOOKUP_INDEXES)
    assert len(created_lookup_indexes) == 7
    for index_name, (table, columns) in LOOKUP_INDEXES.items():
        assert f"create index {index_name} on {table}({columns})" in sql


def test_schema_creation_is_idempotently_guarded_and_verification_is_read_only():
    create_sql = _normalized(CREATE_SQL)
    verify_sql = _normalized(VERIFY_SQL)

    for table in (
        "dbo.naver_keyword_discovery_snapshot",
        "dbo.naver_keyword_discovery_result",
    ):
        assert f"object_id(n'{table}', n'u') is null" in create_sql
    assert create_sql.count("from sys.indexes") == 8
    assert "create table" not in verify_sql
    assert "create index" not in verify_sql
    assert "drop " not in verify_sql
    assert "delete " not in verify_sql


def test_verify_script_uses_sql_server_datetime2_metadata_precision():
    verify_sql = _normalized(VERIFY_SQL)

    assert (
        "(n'naver_keyword_discovery_snapshot', n'collected_at', "
        "n'datetime2', 6, 19, 0, 0, 0)"
    ) in verify_sql


def test_verify_script_checks_exact_constraint_and_index_definitions():
    verify_sql = _normalized(VERIFY_SQL)

    assert "from sys.index_columns as index_columns" in verify_sql
    assert "index_columns.key_ordinal > 0" in verify_sql
    assert "order by index_columns.key_ordinal" in verify_sql
    for table, index, columns in (
        (
            "naver_keyword_discovery_snapshot",
            "pk_naver_keyword_discovery_snapshot",
            "snapshot_id",
        ),
        (
            "naver_keyword_discovery_snapshot",
            "uq_naver_keyword_discovery_snapshot_run_task",
            "run_id,task_key",
        ),
        (
            "naver_keyword_discovery_result",
            "pk_naver_keyword_discovery_result",
            "snapshot_id,raw_position",
        ),
        *(
            (table.removeprefix("dbo."), index, columns.replace(" ", ""))
            for index, (table, columns) in LOOKUP_INDEXES.items()
        ),
        (
            "naver_keyword_discovery_result",
            "ux_naver_keyword_discovery_result_snapshot_organic_rank",
            "snapshot_id,organic_rank",
        ),
    ):
        assert f"(n'{table}', n'{index}'," in verify_sql
        assert f"n'{columns}'" in verify_sql

    assert "from sys.foreign_key_columns as foreign_key_columns" in verify_sql
    assert "order by foreign_key_columns.constraint_column_id" in verify_sql
    assert (
        "(n'naver_keyword_discovery_result', "
        "n'fk_naver_keyword_discovery_result_snapshot', "
        "n'naver_keyword_discovery_snapshot', n'snapshot_id', n'snapshot_id')"
    ) in verify_sql

    assert "from sys.check_constraints as check_constraints" in verify_sql
    for constraint, definition in (
        ("ck_naver_keyword_discovery_snapshot_device_type", "device_typein('mobile','pc')"),
        ("ck_naver_keyword_discovery_snapshot_source_type", "source_typein('excel','database')"),
        ("ck_naver_keyword_discovery_snapshot_latitude", "latitudebetween-90and90"),
        ("ck_naver_keyword_discovery_snapshot_longitude", "longitudebetween-180and180"),
        ("ck_naver_keyword_discovery_snapshot_observed_count", "observed_result_count>=0"),
        ("ck_naver_keyword_discovery_result_raw_position", "raw_position>=1"),
        (
            "ck_naver_keyword_discovery_result_organic_rank",
            "organic_rankisnullororganic_rank>=1",
        ),
    ):
        assert f"n'{constraint}'" in verify_sql
        sql_definition = definition.replace("'", "''")
        assert f"n'{sql_definition}'" in verify_sql


def test_verify_script_normalizes_catalog_collations_to_database_default():
    verify_sql = _normalized(VERIFY_SQL)

    for catalog_expression in (
        "tables.name",
        "columns.name",
        "types.name",
        "key_constraints.name",
        "key_constraints.type",
        "foreign_keys.name",
        "referenced_tables.name",
        "actual_parent.parent_columns",
        "actual_referenced.referenced_columns",
        "check_constraints.name",
        "actual_check.normalized_definition",
        "indexes.name",
        "actual_filter.normalized_filter",
        "actual_keys.key_columns",
    ):
        assert f"{catalog_expression} collate database_default" in verify_sql


def test_schema_files_do_not_reference_legacy_table_or_unapproved_columns():
    sql = f"{_normalized(CREATE_SQL)} {_normalized(VERIFY_SQL)}"

    assert "naver_place_rank" not in sql
    for banned_column in (
        "attempt_count",
        "actual_result_count",
        "created_at",
        "raw_html_path",
        "screenshot_path",
    ):
        assert banned_column not in sql


def test_place_location_schema_is_idempotent_minimal_and_non_destructive():
    create_sql = _normalized(LOCATION_CREATE_SQL)
    verify_sql = _normalized(LOCATION_VERIFY_SQL)

    assert "object_id(n'dbo.naver_place_location', n'u') is null" in create_sql
    assert "if db_name() <> n'naverdb'" in create_sql
    body = _table_body(LOCATION_CREATE_SQL.read_text(encoding="utf-8"), "dbo.naver_place_location")
    assert _declared_columns(body) == {
        "place_id": "varchar(50)",
        "latitude": "decimal(10,7)",
        "longitude": "decimal(10,7)",
        "resolved_at": "datetime2(0)",
        "verified_at": "datetime2(0)",
        "resolver_version": "varchar(30)",
    }
    assert "alter column latitude decimal(10,7) null" in create_sql
    assert "alter column longitude decimal(10,7) null" in create_sql
    assert "primary key (place_id)" in create_sql
    assert "check (latitude between -90 and 90)" in create_sql
    assert "check (longitude between -180 and 180)" in create_sql
    for banned in ("drop table", "delete from", "truncate table"):
        assert banned not in create_sql
        assert banned not in verify_sql
    assert "throw" in verify_sql
