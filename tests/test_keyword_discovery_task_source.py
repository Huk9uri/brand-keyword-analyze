from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.keyword_discovery_rank.models import DeviceType, SourceType
from scripts.keyword_discovery_rank.task_source import (
    DatabaseTaskSource,
    ExcelTaskSource,
    InputValidationError,
    build_task_key,
    normalize_query,
)


HEADERS = ["검색어", "기준매장ID", "기준매장명", "조회위치명", "위도", "경도", "기기", "소스ID"]


class _FakeWorksheet:
    def __init__(self, rows: list[list[object]]) -> None:
        self._rows = [tuple(row) for row in rows]

    def iter_rows(self, *, values_only: bool):
        assert values_only is True
        yield from self._rows


class _FakeWorkbook:
    def __init__(self, rows: list[list[object]]) -> None:
        self.sheetnames = ["검색작업"]
        self.active = _FakeWorksheet(rows)
        self.closed = False

    def __getitem__(self, sheet_name: str) -> _FakeWorksheet:
        assert sheet_name == "검색작업"
        return self.active

    def close(self) -> None:
        self.closed = True


def _mock_excel_workbook(monkeypatch: pytest.MonkeyPatch, rows: list[list[object]]) -> _FakeWorkbook:
    workbook = _FakeWorkbook([HEADERS, *rows])

    def fake_load_workbook(path, *, read_only: bool, data_only: bool):
        assert read_only is True
        assert data_only is True
        return workbook

    monkeypatch.setattr("scripts.keyword_discovery_rank.task_source.load_workbook", fake_load_workbook)
    return workbook


def test_excel_source_defaults_device_normalizes_query_and_builds_stable_task_key(monkeypatch):
    workbook = _mock_excel_workbook(
        monkeypatch,
        [["  선릉역\n  국밥  ", "S1", "육수당 선릉점", "선릉점", 37.5048, 127.0489, None, None]],
    )

    task = ExcelTaskSource("queries.xlsx").load()[0]

    assert task.query == "선릉역 국밥"
    assert task.device_type is DeviceType.MOBILE
    assert task.source_type is SourceType.EXCEL
    assert task.source_id == "excel-row-2"
    assert task.task_id == "excel-row-2"
    assert workbook.closed is True
    assert normalize_query("  선릉역\n  국밥  ") == "선릉역 국밥"
    assert build_task_key(task) == hashlib.sha256(
        "선릉역 국밥|S1|37.5048000|127.0489000|MOBILE".encode("utf-8")
    ).hexdigest()


def test_excel_source_reports_all_row_numbered_validation_errors(monkeypatch):
    _mock_excel_workbook(
        monkeypatch,
        [
            ["", "S1", "육수당 선릉점", "선릉점", 91, 127.0489, "tablet", None],
            ["국밥", "", "", "", "not-a-number", 181, "PC", "source-4"],
        ],
    )

    with pytest.raises(InputValidationError) as exc_info:
        ExcelTaskSource("invalid.xlsx").load()

    message = str(exc_info.value)
    assert "row 2" in message
    assert "row 3" in message
    assert "query is required" in message
    assert "latitude must be between -90 and 90" in message
    assert "longitude must be between -180 and 180" in message
    assert "device must be MOBILE or PC" in message
    assert "target_store_id is required" in message
    assert "latitude must be a number" in message


def test_excel_source_allows_both_coordinates_to_be_blank_for_auto_resolution(monkeypatch):
    _mock_excel_workbook(
        monkeypatch,
        [["설렁탕", "S1", "한촌설렁탕 선릉역점", "선릉역점", None, None, None, "auto"]],
    )

    task = ExcelTaskSource("auto.xlsx").load()[0]

    assert task.latitude is None
    assert task.longitude is None
    assert build_task_key(task) == hashlib.sha256(
        "설렁탕|S1|AUTO|AUTO|MOBILE".encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize("latitude,longitude", [(37.5048, None), (None, 127.0489)])
def test_excel_source_rejects_partial_coordinate_pair(monkeypatch, latitude, longitude):
    _mock_excel_workbook(
        monkeypatch,
        [["설렁탕", "S1", "한촌설렁탕 선릉역점", "선릉역점", latitude, longitude, None, "partial"]],
    )

    with pytest.raises(InputValidationError, match="latitude and longitude must both be provided or both be blank"):
        ExcelTaskSource("partial.xlsx").load()


def test_excel_source_keeps_first_row_for_duplicate_task_keys(monkeypatch):
    _mock_excel_workbook(
        monkeypatch,
        [
            ["선릉역 국밥", "S1", "육수당 선릉점", "선릉점", 37.5048, 127.0489, "MOBILE", "first"],
            ["  선릉역   국밥 ", "S1", "다른 표시명", "다른 위치", 37.5048, 127.0489, "MOBILE", "second"],
        ],
    )

    tasks = ExcelTaskSource("duplicates.xlsx").load()

    assert len(tasks) == 1
    assert tasks[0].source_id == "first"
    assert tasks[0].target_store_name == "육수당 선릉점"


def test_excel_source_requires_named_search_task_worksheet(tmp_path: Path):
    workbook = __import__("openpyxl").Workbook()
    worksheet = workbook.active
    worksheet.title = "다른시트"
    worksheet.append(HEADERS)
    worksheet.append(
        ["선릉역 국밥", "S1", "육수당 선릉점", "선릉점", 37.5048, 127.0489, "MOBILE", "1"]
    )
    path = tmp_path / "wrong-sheet.xlsx"
    workbook.save(path)
    workbook.close()

    with pytest.raises(InputValidationError, match="검색작업"):
        ExcelTaskSource(path).load()


def test_excel_bundle_loads_authoritative_store_and_manual_place_id_mapping(tmp_path: Path):
    workbook = __import__("openpyxl").Workbook()
    tasks = workbook.active
    tasks.title = "검색작업"
    tasks.append(HEADERS)
    tasks.append(
        ["선릉역 국밥", "S1", "표시용 매장명", "선릉점", 37.5048, 127.0489, "MOBILE", "1"]
    )
    stores = workbook.create_sheet("자사매장")
    stores.append(["매장ID", "매장명", "네이버플레이스ID", "수동매핑플레이스ID"])
    stores.append(["S1", "육수당 선릉점", "1001", "legacy-1001"])
    path = tmp_path / "with-identity.xlsx"
    workbook.save(path)
    workbook.close()

    loaded = ExcelTaskSource(path).load_bundle()

    assert [task.target_store_id for task in loaded.tasks] == ["S1"]
    assert [(store.store_id, store.store_name, store.place_id) for store in loaded.own_stores] == [
        ("S1", "육수당 선릉점", "1001")
    ]
    assert dict(loaded.manual_place_id_mappings) == {"legacy-1001": "S1"}


def test_excel_bundle_requires_identity_for_every_task_store(tmp_path: Path):
    workbook = __import__("openpyxl").Workbook()
    tasks = workbook.active
    tasks.title = "검색작업"
    tasks.append(HEADERS)
    tasks.append(
        ["선릉역 국밥", "S1", "육수당 선릉점", "선릉점", 37.5048, 127.0489, "MOBILE", "1"]
    )
    stores = workbook.create_sheet("자사매장")
    stores.append(["매장ID", "매장명", "네이버플레이스ID", "수동매핑플레이스ID"])
    stores.append(["S2", "육수당 강남점", "2002", None])
    path = tmp_path / "missing-task-store.xlsx"
    workbook.save(path)
    workbook.close()

    with pytest.raises(InputValidationError, match="S1"):
        ExcelTaskSource(path).load_bundle()


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def execute(self, statement):
        self.executed.append(statement)

    def fetchall(self):
        return self.rows


def test_database_source_adapts_database_columns_to_search_task_contract():
    cursor = _FakeCursor(
        [
            {
                "candidate_keyword": "  선릉역 국밥 ",
                "store_code": "S1",
                "store_display_name": "육수당 선릉점",
                "search_location": "선릉점",
                "search_latitude": 37.5048,
                "search_longitude": 127.0489,
                "device_code": "PC",
                "candidate_id": 42,
            }
        ]
    )

    task = DatabaseTaskSource(cursor, "SELECT candidates").load()[0]

    assert cursor.executed == ["SELECT candidates"]
    assert task == task.__class__(
        task_id="database-42",
        query="선릉역 국밥",
        target_store_id="S1",
        target_store_name="육수당 선릉점",
        location_name="선릉점",
        latitude=37.5048,
        longitude=127.0489,
        source_type=SourceType.DATABASE,
        source_id="42",
        device_type=DeviceType.PC,
    )


def test_committed_example_workbook_has_a_typed_labeled_search_task():
    workbook_path = Path(__file__).parents[1] / "inputs" / "keyword_discovery_queries.example.xlsx"
    workbook = __import__("openpyxl").load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        assert workbook.sheetnames == ["검색작업", "자사매장"]
        worksheet = workbook["검색작업"]
        assert [cell.value for cell in next(worksheet.iter_rows(max_row=1))] == HEADERS
        sample_row = next(worksheet.iter_rows(min_row=2, max_row=2, values_only=True))
        assert sample_row[0] == "예시: 선릉역 국밥"
        assert isinstance(sample_row[4], float)
        assert isinstance(sample_row[5], float)
        identity = workbook["자사매장"]
        assert [cell.value for cell in next(identity.iter_rows(max_row=1))] == [
            "매장ID",
            "매장명",
            "네이버플레이스ID",
            "수동매핑플레이스ID",
        ]
        identity_row = next(identity.iter_rows(min_row=2, max_row=2, values_only=True))
        assert identity_row == ("SAMPLE-S1", "예시 매장", "1001", "legacy-1001")
    finally:
        workbook.close()
