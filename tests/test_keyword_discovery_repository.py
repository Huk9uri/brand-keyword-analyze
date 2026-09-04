from datetime import datetime
from importlib import import_module

import pytest

from scripts.keyword_discovery_rank.models import (
    CollectStatus,
    DeviceType,
    MatchMethod,
    ParsedResult,
    SearchSnapshot,
    SearchTask,
    SourceType,
)
from scripts.keyword_discovery_rank.place_location import PlaceLocation


class FakeDuplicateKeyError(Exception):
    pass


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.next_row = None
        self.closed = False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("insert into dbo.naver_keyword_discovery_snapshot"):
            self.connection.events.append(("snapshot", normalized, params))
            if self.connection.fail_duplicate:
                raise FakeDuplicateKeyError(2627, "duplicate unique key")
            self.next_row = (self.connection.snapshot_id,)
        elif normalized.startswith("select count(*) from dbo.naver_keyword_discovery_result"):
            self.connection.events.append(("count_results", params))
            count = self.connection.reported_result_count
            self.next_row = (
                self.connection.inserted_result_count if count is None else count,
            )
        elif normalized == "select 1":
            self.connection.events.append(("ping",))
            self.next_row = (1,)
        else:
            raise AssertionError(f"unexpected SQL: {normalized}")
        return self

    def executemany(self, sql, rows):
        normalized = " ".join(sql.lower().split())
        materialized = tuple(rows)
        self.connection.events.append(("results", normalized, materialized))
        if self.connection.fail_results:
            raise RuntimeError("synthetic result insert failure")
        self.connection.inserted_result_count = len(materialized)
        return self

    def fetchone(self):
        row = self.next_row
        self.next_row = None
        return row

    def close(self):
        self.closed = True
        self.connection.events.append(("cursor_close",))


class FakeConnection:
    def __init__(
        self,
        *,
        fail_results=False,
        fail_duplicate=False,
        snapshot_id=41,
        reported_result_count=None,
    ):
        self.fail_results = fail_results
        self.fail_duplicate = fail_duplicate
        self.snapshot_id = snapshot_id
        self.inserted_result_count = 0
        self.reported_result_count = reported_result_count
        self.events = []
        self.closed = False

    def cursor(self):
        self.events.append(("cursor",))
        return FakeCursor(self)

    def commit(self):
        self.events.append(("commit",))

    def rollback(self):
        self.events.append(("rollback",))

    def close(self):
        self.closed = True
        self.events.append(("connection_close",))


def _repository_api():
    module = import_module("scripts.keyword_discovery_rank.repository")
    return module.SnapshotRepository, module.RepositoryError


def _snapshot(status=CollectStatus.SUCCESS):
    task = SearchTask(
        task_id="row-2",
        query="선릉역 국밥",
        target_store_id="S1",
        target_store_name="육수당 선릉점",
        location_name="선릉점",
        latitude=37.5048,
        longitude=127.0489,
        source_type=SourceType.EXCEL,
        source_id="2",
        device_type=DeviceType.MOBILE,
    )
    return SearchSnapshot(
        run_id="11111111-1111-1111-1111-111111111111",
        task_key="a" * 64,
        task=task,
        normalized_query="선릉역 국밥",
        requested_result_limit=20,
        observed_result_count=2 if status is CollectStatus.SUCCESS else 0,
        result_end_reached=True,
        collect_status=status,
        collect_msg=None,
        parser_version="dom-v1",
        final_url="https://m.search.naver.com/search.naver?query=test",
        collected_at=datetime(2026, 9, 2, 12, 0, 0),
    )


def _results():
    return (
        ParsedResult(
            raw_position=1,
            organic_rank=1,
            place_id="1001",
            place_name="육수당 선릉점",
            category="국밥",
            is_ad=False,
            detail_url="https://m.place.naver.com/restaurant/1001",
            distance_text="120m",
            is_own_store=True,
            matched_store_id="S1",
            match_method=MatchMethod.PLACE_ID,
        ),
        ParsedResult(
            raw_position=2,
            organic_rank=None,
            place_id="9001",
            place_name="서울국밥 광고점",
            category=None,
            is_ad=True,
            detail_url="https://m.place.naver.com/restaurant/9001",
            distance_text=None,
        ),
    )


def test_save_inserts_snapshot_then_results_with_reused_identity_and_one_commit():
    SnapshotRepository, _ = _repository_api()
    connection = FakeConnection(snapshot_id=41)

    snapshot_id = SnapshotRepository(connection).save(_snapshot(), _results())

    assert snapshot_id == 41
    operation_names = [event[0] for event in connection.events]
    assert operation_names == [
        "cursor",
        "snapshot",
        "results",
        "count_results",
        "commit",
        "cursor_close",
    ]
    snapshot_event = connection.events[1]
    result_event = connection.events[2]
    assert "output inserted.snapshot_id" in snapshot_event[1]
    assert snapshot_event[2] == (
        "11111111-1111-1111-1111-111111111111",
        "a" * 64,
        "선릉역 국밥",
        "선릉역 국밥",
        "S1",
        "육수당 선릉점",
        "선릉점",
        37.5048,
        127.0489,
        "MOBILE",
        "EXCEL",
        "2",
        20,
        2,
        True,
        "SUCCESS",
        None,
        "dom-v1",
        "https://m.search.naver.com/search.naver?query=test",
        datetime(2026, 9, 2, 12, 0, 0),
    )
    assert result_event[2] == (
        (
            41,
            1,
            1,
            "1001",
            "육수당 선릉점",
            "국밥",
            False,
            "https://m.place.naver.com/restaurant/1001",
            "120m",
            True,
            "S1",
            "PLACE_ID",
            False,
        ),
        (
            41,
            2,
            None,
            "9001",
            "서울국밥 광고점",
            None,
            True,
            "https://m.place.naver.com/restaurant/9001",
            None,
            False,
            None,
            "NONE",
            False,
        ),
    )
    assert connection.events.count(("commit",)) == 1
    assert ("rollback",) not in connection.events


def test_save_rolls_back_without_commit_when_result_insert_fails():
    SnapshotRepository, RepositoryError = _repository_api()
    connection = FakeConnection(fail_results=True)

    with pytest.raises(RepositoryError, match="save keyword discovery snapshot"):
        SnapshotRepository(connection).save(_snapshot(), _results())

    assert ("rollback",) in connection.events
    assert ("commit",) not in connection.events
    assert connection.events[-1] == ("cursor_close",)


def test_save_rolls_back_when_verified_result_count_does_not_match():
    SnapshotRepository, RepositoryError = _repository_api()
    connection = FakeConnection(reported_result_count=1)

    with pytest.raises(RepositoryError, match="result row count mismatch"):
        SnapshotRepository(connection).save(_snapshot(), _results())

    assert ("rollback",) in connection.events
    assert ("commit",) not in connection.events


def test_save_persists_no_result_snapshot_without_result_rows():
    SnapshotRepository, _ = _repository_api()
    connection = FakeConnection(snapshot_id=77)

    snapshot_id = SnapshotRepository(connection).save(
        _snapshot(CollectStatus.NO_RESULT),
        _results(),
    )

    assert snapshot_id == 77
    assert not any(event[0] == "results" for event in connection.events)
    assert ("count_results", (77,)) in connection.events
    assert connection.events.count(("commit",)) == 1


def test_save_converts_duplicate_run_task_key_to_repository_error_and_rolls_back():
    SnapshotRepository, RepositoryError = _repository_api()
    connection = FakeConnection(fail_duplicate=True)

    with pytest.raises(RepositoryError, match="run_id and task_key"):
        SnapshotRepository(connection).save(_snapshot(), ())

    assert ("rollback",) in connection.events
    assert ("commit",) not in connection.events


def test_result_unique_violation_is_not_misreported_as_snapshot_duplicate():
    module = import_module("scripts.keyword_discovery_rank.repository")

    class DuplicateResultCursor(FakeCursor):
        def executemany(self, sql, rows):
            raise FakeDuplicateKeyError(2627, "duplicate result rank")

    class DuplicateResultConnection(FakeConnection):
        def cursor(self):
            self.events.append(("cursor",))
            return DuplicateResultCursor(self)

    with pytest.raises(module.TaskPersistenceError) as caught:
        module.SnapshotRepository(DuplicateResultConnection()).save(_snapshot(), _results())

    assert "run_id and task_key" not in str(caught.value)
    assert "task-local" in str(caught.value)


def test_ping_executes_connection_probe_and_close_releases_connection():
    SnapshotRepository, _ = _repository_api()
    connection = FakeConnection()
    repository = SnapshotRepository(connection)

    assert repository.ping() is True
    repository.close()

    assert ("ping",) in connection.events
    assert connection.events.count(("cursor_close",)) == 1
    assert connection.closed is True
    assert connection.events[-1] == ("connection_close",)


class FakePreflightCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def execute(self, sql, params=None):
        normalized = " ".join(sql.lower().split())
        self.connection.statements.append(normalized)
        if normalized == "select db_name()":
            self.rows = [(self.connection.database,)]
        elif "information_schema.columns" in normalized:
            self.rows = list(self.connection.columns)
        else:
            raise AssertionError(f"unexpected preflight SQL: {normalized}")

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)

    def close(self):
        pass


class FakePreflightConnection:
    def __init__(self, database, columns):
        self.database = database
        self.columns = columns
        self.statements = []

    def cursor(self):
        return FakePreflightCursor(self)


def test_preflight_accepts_sql_server_null_numeric_metadata_for_bit_columns():
    module = import_module("scripts.keyword_discovery_rank.repository")
    columns = [
        (
            table,
            column,
            data_type,
            max_length,
            None if data_type == "bit" else precision,
            None if data_type == "bit" else scale,
            nullable,
            is_identity,
        )
        for (table, column), (data_type, max_length, precision, scale, nullable, is_identity) in
        module.EXPECTED_SCHEMA_COLUMNS.items()
    ]
    connection = FakePreflightConnection("naverDB", columns)

    module.SnapshotRepository(connection).preflight(expected_database="naverDB")

    assert len(module.EXPECTED_SCHEMA_COLUMNS) == 34
    assert module.EXPECTED_SCHEMA_COLUMNS[("naver_keyword_discovery_snapshot", "run_id")][0] == (
        "uniqueidentifier"
    )
    assert module.EXPECTED_SCHEMA_COLUMNS[("naver_keyword_discovery_result", "place_id")][:2] == (
        "varchar",
        50,
    )
    assert module.EXPECTED_SCHEMA_COLUMNS[("naver_keyword_discovery_snapshot", "snapshot_id")][-1] == 1
    assert all(statement.startswith("select") for statement in connection.statements)


@pytest.mark.parametrize(
    ("database", "drop_last_column", "message"),
    [
        ("SEIERP_HD", False, "expected naverDB"),
        ("naverDB", True, "schema mismatch"),
    ],
)
def test_preflight_rejects_wrong_target_or_incomplete_schema(
    database: str,
    drop_last_column: bool,
    message: str,
):
    module = import_module("scripts.keyword_discovery_rank.repository")
    columns = [
        (table, column, data_type, max_length, precision, scale, nullable, is_identity)
        for (table, column), (data_type, max_length, precision, scale, nullable, is_identity) in
        module.EXPECTED_SCHEMA_COLUMNS.items()
    ]
    if drop_last_column:
        columns.pop()

    with pytest.raises(module.FatalRepositoryError, match=message):
        module.SnapshotRepository(FakePreflightConnection(database, columns)).preflight(
            expected_database="naverDB"
        )


class FakeSqlError(Exception):
    pass


class FailingSaveCursor(FakeCursor):
    def execute(self, sql, params=None):
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("insert into dbo.naver_keyword_discovery_snapshot"):
            raise self.connection.save_error
        return super().execute(sql, params)


class FailingSaveConnection(FakeConnection):
    def __init__(self, save_error):
        super().__init__()
        self.save_error = save_error

    def cursor(self):
        self.events.append(("cursor",))
        return FailingSaveCursor(self)


@pytest.mark.parametrize("error", [FakeSqlError(208, "invalid object"), FakeSqlError(20003, "connection lost")])
def test_save_classifies_target_schema_and_connection_failures_as_fatal(error):
    module = import_module("scripts.keyword_discovery_rank.repository")

    with pytest.raises(module.FatalRepositoryError):
        module.SnapshotRepository(FailingSaveConnection(error)).save(_snapshot(), ())


def test_save_classifies_task_data_failure_as_local():
    module = import_module("scripts.keyword_discovery_rank.repository")

    with pytest.raises(module.TaskPersistenceError):
        module.SnapshotRepository(
            FailingSaveConnection(FakeSqlError(2628, "string or binary data would be truncated"))
        ).save(_snapshot(), ())


def test_preflight_classifies_cursor_connection_failure_as_fatal():
    module = import_module("scripts.keyword_discovery_rank.repository")

    class BrokenConnection:
        def cursor(self):
            raise FakeSqlError(20003, "connection unavailable")

    with pytest.raises(module.FatalRepositoryError, match="preflight"):
        module.SnapshotRepository(BrokenConnection()).preflight(expected_database="naverDB")


def test_save_preserves_fatal_classification_when_rollback_also_fails():
    module = import_module("scripts.keyword_discovery_rank.repository")

    class BrokenRollbackConnection(FailingSaveConnection):
        def rollback(self):
            raise FakeSqlError(20003, "rollback connection unavailable")

    with pytest.raises(module.FatalRepositoryError):
        module.SnapshotRepository(
            BrokenRollbackConnection(FakeSqlError(208, "invalid object"))
        ).save(_snapshot(), ())


def test_save_classifies_failed_rollback_after_task_local_error_as_fatal():
    module = import_module("scripts.keyword_discovery_rank.repository")

    class BrokenRollbackConnection(FailingSaveConnection):
        def rollback(self):
            raise FakeSqlError(20003, "rollback connection unavailable")

    with pytest.raises(module.FatalRepositoryError, match="rollback"):
        module.SnapshotRepository(
            BrokenRollbackConnection(
                FakeSqlError(2628, "string or binary data would be truncated")
            )
        ).save(_snapshot(), ())


def test_place_location_repository_reads_and_upserts_cache_rows():
    module = import_module("scripts.keyword_discovery_rank.repository")

    class Cursor:
        def __init__(self):
            self.row = None
            self.executed = []

        def execute(self, sql, params=None):
            self.executed.append((" ".join(sql.lower().split()), params))
            if sql.lstrip().lower().startswith("select place_id"):
                self.row = ("31076466", 37.5042, 127.0531, datetime(2026, 9, 3), datetime(2026, 9, 3), "place-location-v1")
            return self

        def fetchone(self):
            return self.row

        def close(self):
            pass

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()
            self.commits = 0

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            self.commits += 1

        def rollback(self):
            raise AssertionError("rollback not expected")

    connection = Connection()
    repository = module.PlaceLocationRepository(connection)
    cached = repository.get("31076466")
    repository.upsert(PlaceLocation.create("31076466", 37.5042, 127.0531))

    assert cached.place_id == "31076466"
    assert cached.latitude == 37.5042
    assert "merge dbo.naver_place_location" in connection.cursor_instance.executed[1][0]
    assert connection.commits == 1


def test_place_location_repository_preflight_accepts_exact_contract():
    module = import_module("scripts.keyword_discovery_rank.repository")

    class Cursor:
        def __init__(self):
            self.mode = ""

        def execute(self, sql, params=None):
            self.mode = "database" if "DB_NAME" in sql else "schema"
            return self

        def fetchone(self):
            return ("naverDB",)

        def fetchall(self):
            return [
                (name, *signature)
                for name, signature in module.EXPECTED_LOCATION_SCHEMA_COLUMNS.items()
            ]

        def close(self):
            pass

    class Connection:
        def cursor(self):
            return Cursor()

    module.PlaceLocationRepository(Connection()).preflight(expected_database="naverDB")
