from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from scripts.keyword_discovery_rank.collector import KeywordDiscoveryCollector
from scripts.keyword_discovery_rank.matching import OwnStore, OwnStoreMatcher
from scripts.keyword_discovery_rank.models import CollectStatus, DeviceType, MatchMethod, SearchPage
from scripts.keyword_discovery_rank.parser import DomResultParser
from scripts.keyword_discovery_rank.task_source import ExcelTaskSource
from scripts.keyword_discovery_rank.validation import ResultValidator


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "keyword_discovery_rank" / "mixed_results.html"
SEARCH_URL = "https://m.search.naver.com/search.naver?where=m&query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
HEADERS = ["검색어", "기준매장ID", "기준매장명", "조회위치명", "위도", "경도", "기기", "소스ID"]


class FakeBrowserSession:
    def __init__(self, page: SearchPage) -> None:
        self.page = page
        self.search_tasks = []
        self.closed = False

    def search(self, task):
        self.search_tasks.append(task)
        return self.page

    def close(self) -> None:
        self.closed = True


class FakeBrowserFactory:
    def __init__(self, session: FakeBrowserSession) -> None:
        self.session = session
        self.create_calls = []

    def create(self, device_type, latitude, longitude):
        self.create_calls.append((device_type, latitude, longitude))
        return self.session


class FakeRepository:
    def __init__(self) -> None:
        self.saved = []

    def save(self, snapshot, results):
        self.saved.append((snapshot, tuple(results)))
        return len(self.saved)


def _write_duplicate_workbook(path: Path) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "검색작업"
    worksheet.append(HEADERS)
    worksheet.append(
        [
            "선릉역 국밥",
            "S1",
            "육수당 선릉점",
            "선릉점",
            37.5048,
            127.0489,
            "MOBILE",
            "first-row",
        ]
    )
    worksheet.append(
        [
            "  선릉역   국밥 ",
            "S1",
            "중복 행은 수집하지 않음",
            "다른 조회위치명",
            37.5048,
            127.0489,
            "MOBILE",
            "duplicate-row",
        ]
    )
    workbook.save(path)
    workbook.close()


def test_fixture_workbook_flows_through_collection_pipeline_once_and_persists_ordered_matches(
    tmp_path: Path,
):
    workbook_path = tmp_path / "keyword_discovery_queries.xlsx"
    _write_duplicate_workbook(workbook_path)
    tasks = ExcelTaskSource(workbook_path).load()
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    session = FakeBrowserSession(
        SearchPage(
            final_url=SEARCH_URL,
            html=html,
            state="RESULTS",
            observed_result_count=999,
            result_end_reached=False,
        )
    )
    factory = FakeBrowserFactory(session)
    repository = FakeRepository()
    collector = KeywordDiscoveryCollector(
        factory,
        DomResultParser(),
        ResultValidator(),
        OwnStoreMatcher((OwnStore("S1", "육수당 선릉점", "1001"),)),
        repository,
        artifact_root=tmp_path / "artifacts",
        result_limit=20,
        clock=lambda: datetime(2026, 9, 2, 12, 0, 0),
    )

    summary = collector.run(tasks, "e2e-fixture-run")

    assert len(tasks) == 1
    assert tasks[0].source_id == "first-row"
    assert summary.total_tasks == 1
    assert summary.processed_tasks == 1
    assert summary.status_counts == {CollectStatus.SUCCESS: 1}
    assert len(factory.create_calls) == 1
    assert factory.create_calls == [(DeviceType.MOBILE, 37.5048, 127.0489)]
    assert len(session.search_tasks) == 1
    assert session.closed is True
    assert len(repository.saved) == 1

    snapshot, results = repository.saved[0]
    assert snapshot.collect_status is CollectStatus.SUCCESS
    assert snapshot.observed_result_count == 4
    assert snapshot.result_end_reached is True
    assert [row.raw_position for row in results] == [1, 2, 3, 4]
    assert [row.organic_rank for row in results] == [1, None, 2, 3]
    assert [row.place_id for row in results] == ["1001", "9001", "1002", "1003"]
    assert [row.is_own_store for row in results] == [True, False, False, False]
    assert [row.is_target_store for row in results] == [True, False, False, False]
    assert [row.matched_store_id for row in results] == ["S1", None, None, None]
    assert [row.match_method for row in results] == [
        MatchMethod.PLACE_ID,
        MatchMethod.NONE,
        MatchMethod.NONE,
        MatchMethod.NONE,
    ]
