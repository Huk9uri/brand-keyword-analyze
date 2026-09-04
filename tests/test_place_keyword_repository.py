from datetime import datetime, timezone
import traceback

import pytest

from scripts.place_keyword_collector.models import (
    CollectedKeyword,
    KeywordCollectStatus,
    KeywordSnapshot,
    PreviousVersion,
    RankPlaceTarget,
)
from scripts.place_keyword_collector.repository import (
    EXPECTED_SCHEMA_COLUMNS,
    FatalRepositoryError,
    PlaceKeywordRepository,
    TaskPersistenceError,
)


CHECKED_AT = datetime(2026, 9, 4, 10, 30, tzinfo=timezone.utc)


EXPECTED_COLUMNS = {
    ("naver_place_keyword_result", "keyword_order"): (
        "smallint", None, 5, 0, None, "NO", 0,
    ),
    ("naver_place_keyword_result", "normalized_keyword"): (
        "nvarchar", 255, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_result", "raw_keyword"): (
        "nvarchar", 255, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_result", "snapshot_id"): (
        "bigint", None, 19, 0, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "checked_at"): (
        "datetime2", None, None, None, 3, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "collect_method"): (
        "varchar", 20, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "collect_msg"): (
        "nvarchar", 1000, None, None, None, "YES", 0,
    ),
    ("naver_place_keyword_snapshot", "collect_status"): (
        "varchar", 30, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "content_hash"): (
        "char", 64, None, None, None, "YES", 0,
    ),
    ("naver_place_keyword_snapshot", "effective_snapshot_id"): (
        "bigint", None, 19, 0, None, "YES", 0,
    ),
    ("naver_place_keyword_snapshot", "is_changed"): (
        "bit", None, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "keyword_count"): (
        "smallint", None, 5, 0, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "parser_version"): (
        "varchar", 30, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "place_id"): (
        "varchar", 50, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "place_name"): (
        "nvarchar", 300, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "rank_run_id"): (
        "uniqueidentifier", None, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "run_id"): (
        "uniqueidentifier", None, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "snapshot_id"): (
        "bigint", None, 19, 0, None, "NO", 1,
    ),
    ("naver_place_keyword_snapshot", "source_url"): (
        "nvarchar", 2000, None, None, None, "NO", 0,
    ),
}


class FakeSqlError(Exception):
    pass


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.row = None
        self.rows = []

    def execute(self, sql, params=None):
        self.connection.events.append(("execute", sql, params))
        normalized = " ".join(sql.lower().split())
        if normalized == "select db_name()":
            self.row = (self.connection.database,)
        elif "information_schema.columns" in normalized:
            self.rows = list(self.connection.schema_rows)
        elif normalized.startswith("select top (1)"):
            self.row = self.connection.previous_row
        elif normalized.startswith("insert into dbo.naver_place_keyword_snapshot"):
            if self.connection.snapshot_error is not None:
                raise self.connection.snapshot_error
            self.row = None if self.connection.missing_identity else (self.connection.snapshot_id,)
            self.connection.inserted_snapshot_params = params
        elif normalized.startswith("update dbo.naver_place_keyword_snapshot"):
            if self.connection.update_error is not None:
                raise self.connection.update_error
            self.connection.updated_effective_id = params[0]
        elif normalized.startswith("select count(*)"):
            count = (
                len(self.connection.result_rows)
                if self.connection.reported_result_count is None
                else self.connection.reported_result_count
            )
            self.row = (count,)
        else:
            raise AssertionError(f"unexpected SQL: {normalized}")
        return self

    def executemany(self, sql, rows):
        materialized = tuple(rows)
        self.connection.executemany_calls.append((sql, materialized))
        if self.connection.result_error is not None:
            raise self.connection.result_error
        self.connection.result_rows.extend(materialized)

    def fetchone(self):
        return self.row

    def fetchall(self):
        return list(self.rows)

    def close(self):
        self.connection.events.append(("cursor_close",))


class FakeConnection:
    def __init__(
        self,
        *,
        database="naverDB",
        schema_rows=None,
        previous_row=None,
        snapshot_id=101,
        snapshot_error=None,
        result_error=None,
        update_error=None,
        reported_result_count=None,
        missing_identity=False,
        rollback_error=None,
    ):
        self.database = database
        self.schema_rows = schema_rows if schema_rows is not None else _schema_rows()
        self.previous_row = previous_row
        self.snapshot_id = snapshot_id
        self.snapshot_error = snapshot_error
        self.result_error = result_error
        self.update_error = update_error
        self.reported_result_count = reported_result_count
        self.missing_identity = missing_identity
        self.rollback_error = rollback_error
        self.events = []
        self.executemany_calls = []
        self.result_rows = []
        self.inserted_snapshot_params = None
        self.updated_effective_id = None
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        self.events.append(("cursor",))
        return FakeCursor(self)

    def commit(self):
        self.commits += 1
        self.events.append(("commit",))

    def rollback(self):
        self.rollbacks += 1
        self.events.append(("rollback",))
        if self.rollback_error is not None:
            raise self.rollback_error


def _schema_rows():
    return [
        (
            table,
            column,
            data_type,
            length,
            precision,
            scale,
            datetime_precision,
            nullable,
            identity,
        )
        for (table, column), (
            data_type,
            length,
            precision,
            scale,
            datetime_precision,
            nullable,
            identity,
        ) in EXPECTED_COLUMNS.items()
    ]


def _snapshot(
    status=KeywordCollectStatus.SUCCESS,
    *,
    changed=True,
    effective_snapshot_id=None,
    keyword_count=2,
    content_hash="a" * 64,
):
    return KeywordSnapshot(
        snapshot_id=0,
        run_id="11111111-1111-1111-1111-111111111111",
        rank_run_id="22222222-2222-2222-2222-222222222222",
        target=RankPlaceTarget("13149768", "농민백암순대 본점"),
        source_url="https://m.place.naver.com/restaurant/13149768/home",
        status=status,
        content_hash=content_hash,
        is_changed=changed,
        effective_snapshot_id=effective_snapshot_id,
        keyword_count=keyword_count,
        parser_version="place-keyword-v1",
        collect_msg=None,
        checked_at=CHECKED_AT,
    )


def _keywords():
    return (
        CollectedKeyword(1, "순대", "순대"),
        CollectedKeyword(2, " 순댓국 ", "순댓국"),
    )


def test_expected_schema_matches_task_2_column_contract_exactly():
    assert EXPECTED_SCHEMA_COLUMNS == EXPECTED_COLUMNS


def test_preflight_uses_read_only_queries_and_accepts_exact_schema():
    connection = FakeConnection()

    PlaceKeywordRepository(connection).preflight()

    executed = [event for event in connection.events if event[0] == "execute"]
    assert executed[0][1:] == ("SELECT DB_NAME()", None)
    assert "IN ('naver_place_keyword_snapshot', 'naver_place_keyword_result')" in executed[1][1]
    assert executed[1][2] is None
    assert connection.commits == 0
    assert connection.rollbacks == 0
    assert connection.events[-1] == ("cursor_close",)


def test_preflight_accepts_case_insensitive_expected_database():
    PlaceKeywordRepository(FakeConnection(database="NAVERdb")).preflight("naverDB")


def test_preflight_rejects_wrong_datetime2_precision():
    rows = _schema_rows()
    checked_at = next(index for index, row in enumerate(rows) if row[1] == "checked_at")
    rows[checked_at] = (*rows[checked_at][:6], 7, *rows[checked_at][7:])

    with pytest.raises(FatalRepositoryError, match="schema mismatch"):
        PlaceKeywordRepository(FakeConnection(schema_rows=rows)).preflight()


@pytest.mark.parametrize(
    ("connection", "message"),
    [
        (FakeConnection(database="SEIERP_HD"), "expected naverDB"),
        (FakeConnection(schema_rows=_schema_rows()[:-1]), "schema mismatch"),
    ],
)
def test_preflight_rejects_wrong_database_or_inexact_schema(connection, message):
    with pytest.raises(FatalRepositoryError, match=message):
        PlaceKeywordRepository(connection).preflight(expected_database="naverDB")

    assert connection.events[-1] == ("cursor_close",)


def test_get_previous_returns_latest_check_and_its_effective_version():
    row = (73, "b" * 64, CHECKED_AT, "BLOCKED")
    connection = FakeConnection(previous_row=row)

    previous = PlaceKeywordRepository(connection).get_previous("13149768")

    assert previous == PreviousVersion(
        effective_snapshot_id=73,
        content_hash="b" * 64,
        checked_at=CHECKED_AT,
        status=KeywordCollectStatus.BLOCKED,
    )
    select_event = next(
        event for event in connection.events
        if event[0] == "execute" and event[1].lstrip().lower().startswith("select top (1)")
    )
    assert "effective.content_hash" in select_event[1]
    assert "ORDER BY latest.checked_at DESC, latest.snapshot_id DESC" in select_event[1]
    assert select_event[2] == ("13149768",)
    assert connection.events[-1] == ("cursor_close",)


def test_get_previous_returns_none_without_an_effective_version():
    assert PlaceKeywordRepository(FakeConnection()).get_previous("new-place") is None


def test_get_previous_rejects_effective_snapshot_without_a_valid_hash():
    connection = FakeConnection(previous_row=(73, None, CHECKED_AT, "BLOCKED"))

    with pytest.raises(FatalRepositoryError, match="previous version"):
        PlaceKeywordRepository(connection).get_previous("13149768")


def test_changed_success_inserts_snapshot_results_sets_self_effective_id_and_commits_once():
    connection = FakeConnection(snapshot_id=101)

    snapshot_id = PlaceKeywordRepository(connection).save(_snapshot(), _keywords())

    assert snapshot_id == 101
    assert connection.inserted_snapshot_params == (
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "13149768",
        "농민백암순대 본점",
        "https://m.place.naver.com/restaurant/13149768/home",
        "SUCCESS",
        "BROWSER",
        "a" * 64,
        True,
        None,
        2,
        "place-keyword-v1",
        None,
        CHECKED_AT,
    )
    assert connection.result_rows == [
        (101, 1, "순대", "순대"),
        (101, 2, " 순댓국 ", "순댓국"),
    ]
    assert connection.updated_effective_id == 101
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.events[-2:] == [("commit",), ("cursor_close",)]


def test_changed_empty_becomes_self_effective_without_result_rows():
    connection = FakeConnection(snapshot_id=102)
    snapshot = _snapshot(
        KeywordCollectStatus.EMPTY,
        keyword_count=0,
        content_hash="e" * 64,
    )

    assert PlaceKeywordRepository(connection).save(snapshot, ()) == 102

    assert connection.executemany_calls == []
    assert connection.updated_effective_id == 102
    assert connection.commits == 1


def test_unchanged_check_inserts_no_keyword_rows_and_retains_previous_effective_id():
    connection = FakeConnection()
    snapshot = _snapshot(changed=False, effective_snapshot_id=73)

    PlaceKeywordRepository(connection).save(snapshot, _keywords())

    assert connection.executemany_calls == []
    assert connection.inserted_snapshot_params[9] == 73
    assert connection.updated_effective_id is None
    assert connection.commits == 1


def test_failure_inserts_no_keyword_rows_and_keeps_previous_effective_snapshot():
    connection = FakeConnection()
    snapshot = _snapshot(
        KeywordCollectStatus.BLOCKED,
        changed=False,
        effective_snapshot_id=73,
        keyword_count=0,
        content_hash=None,
    )

    PlaceKeywordRepository(connection).save(snapshot, ())

    assert connection.executemany_calls == []
    assert connection.inserted_snapshot_params[9] == 73
    assert connection.updated_effective_id is None
    assert connection.commits == 1


def test_result_count_mismatch_rolls_back_without_commit():
    connection = FakeConnection(reported_result_count=1)

    with pytest.raises(TaskPersistenceError, match="result row count mismatch"):
        PlaceKeywordRepository(connection).save(_snapshot(), _keywords())

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert connection.events[-1] == ("cursor_close",)


def test_changed_success_rejects_keyword_count_mismatch_before_commit():
    connection = FakeConnection()

    with pytest.raises(TaskPersistenceError, match="keyword_count mismatch"):
        PlaceKeywordRepository(connection).save(
            _snapshot(keyword_count=1),
            _keywords(),
        )

    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_changed_valid_version_requires_a_content_hash():
    connection = FakeConnection()

    with pytest.raises(TaskPersistenceError, match="content_hash"):
        PlaceKeywordRepository(connection).save(
            _snapshot(content_hash=None),
            _keywords(),
        )

    assert connection.rollbacks == 1
    assert connection.commits == 0


@pytest.mark.parametrize(
    ("snapshot", "keywords"),
    [
        (_snapshot(KeywordCollectStatus.SUCCESS, keyword_count=0), ()),
        (_snapshot(KeywordCollectStatus.EMPTY, keyword_count=1), _keywords()[:1]),
    ],
)
def test_changed_valid_version_rejects_status_keyword_inconsistency(snapshot, keywords):
    connection = FakeConnection()

    with pytest.raises(TaskPersistenceError, match="keyword_count mismatch"):
        PlaceKeywordRepository(connection).save(snapshot, keywords)

    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_result_insert_failure_rolls_back_the_snapshot_and_results():
    connection = FakeConnection(result_error=FakeSqlError(2628, "truncated payload"))

    with pytest.raises(TaskPersistenceError, match="task-local"):
        PlaceKeywordRepository(connection).save(_snapshot(), _keywords())

    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_duplicate_run_place_is_a_task_local_persistence_error():
    connection = FakeConnection(
        snapshot_error=FakeSqlError(2627, "duplicate run and place")
    )

    with pytest.raises(TaskPersistenceError, match="run_id and place_id"):
        PlaceKeywordRepository(connection).save(_snapshot(), _keywords())

    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_duplicate_result_is_not_misreported_as_run_place_duplicate():
    connection = FakeConnection(
        result_error=FakeSqlError(2627, "duplicate keyword order")
    )

    with pytest.raises(TaskPersistenceError) as caught:
        PlaceKeywordRepository(connection).save(_snapshot(), _keywords())

    assert "run_id and place_id" not in str(caught.value)
    assert "task-local" in str(caught.value)


@pytest.mark.parametrize(
    "error",
    [FakeSqlError(208, "invalid object"), FakeSqlError(20003, "connection lost")],
)
def test_connection_and_schema_save_failures_are_fatal(error):
    with pytest.raises(FatalRepositoryError):
        PlaceKeywordRepository(FakeConnection(snapshot_error=error)).save(
            _snapshot(), _keywords()
        )


def test_failed_rollback_makes_transaction_state_a_fatal_error():
    connection = FakeConnection(
        snapshot_error=FakeSqlError(2628, "bad task data"),
        rollback_error=FakeSqlError(20003, "connection lost"),
    )

    with pytest.raises(FatalRepositoryError, match="rollback"):
        PlaceKeywordRepository(connection).save(_snapshot(), _keywords())


def test_lookup_connection_failure_is_fatal_and_does_not_echo_driver_message():
    class BrokenConnection:
        def cursor(self):
            raise FakeSqlError(20003, "password=secret")

    with pytest.raises(FatalRepositoryError, match="previous version") as caught:
        PlaceKeywordRepository(BrokenConnection()).get_previous("13149768")

    assert "secret" not in str(caught.value)
    assert "secret" not in "".join(
        traceback.format_exception(caught.type, caught.value, caught.tb)
    )
