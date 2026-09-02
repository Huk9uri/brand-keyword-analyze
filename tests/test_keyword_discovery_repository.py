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
