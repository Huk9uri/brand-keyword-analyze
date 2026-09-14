from __future__ import annotations

import json
import hashlib
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from scripts.keyword_discovery_rank.browser import (
    BrowserSessionError,
    QueryMismatch,
    SearchPageError,
    SearchStateTimeout,
)
from scripts.keyword_discovery_rank.collector import (
    KeywordDiscoveryCollector,
    _mark_target_store,
    _result_progress,
)
from scripts.keyword_discovery_rank.matching import OwnStore, OwnStoreMatcher
from scripts.keyword_discovery_rank.models import (
    CollectStatus,
    DeviceType,
    MatchMethod,
    ParsedResult,
    SearchPage,
    SearchTask,
    SourceType,
)
from scripts.keyword_discovery_rank.parser import DomResultParser
from scripts.keyword_discovery_rank.repository import FatalRepositoryError, TaskPersistenceError
from scripts.keyword_discovery_rank.task_source import build_task_key
from scripts.keyword_discovery_rank.validation import ResultValidator


SUCCESS_HTML = """
<ul>
  <li data-naver-place-card data-place-id="1001">
    <a data-place-name href="https://m.place.naver.com/restaurant/1001">육수당 선릉점</a>
  </li>
</ul>
<div data-naver-search-end>검색 결과의 끝</div>
"""
PARTIAL_HTML = """
<ul>
  <li data-naver-place-card data-place-id="1001">
    <a data-place-name href="https://m.place.naver.com/restaurant/1001">육수당 선릉점</a>
  </li>
  <li data-naver-place-card><span data-place-name>식별자 없는 매장</span></li>
</ul>
<div data-naver-search-end>검색 결과의 끝</div>
"""


def test_profile_cleanup_failure_stops_instead_of_leaking_next_session(tmp_path):
    class LockedSession(FakeSession):
        def close(self):
            raise PermissionError('profile cleanup exhausted')
    instance, _, _ = collector(tmp_path, [LockedSession([success_page()])])
    with pytest.raises(PermissionError, match='profile cleanup exhausted'):
        instance.run([task()], 'cleanup-failure')


def test_collector_progress_uses_semantic_place_cards_without_nmb_identifiers():
    html = (
        Path(__file__).parent
        / "fixtures"
        / "keyword_discovery_rank"
        / "semantic_place_cards.html"
    ).read_text(encoding="utf-8")

    assert _result_progress(html) == (2, False)


def test_request_pacing_and_retry_backoff(tmp_path):
    sleeps = []
    error = SearchPageError('temporary', last_url=SEARCH_URL, html='')
    session = FakeSession([error, error, success_page(), success_page()])
    instance, _, _ = collector(tmp_path, [session])
    instance.request_interval_seconds = 30
    instance.retry_backoff_seconds = 60
    instance._sleep = sleeps.append
    instance.run([task(), task(2, query='another query')], 'paced')
    assert sleeps == [30, 60, 120, 30]
SEARCH_URL = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"


def task(
    index: int = 1,
    *,
    latitude: float = 37.5048,
    query: str = "선릉역 국밥",
    device_type: DeviceType = DeviceType.MOBILE,
) -> SearchTask:
    return SearchTask(
        task_id=f"row-{index}",
        query=query,
        target_store_id="S1",
        target_store_name="육수당 선릉점",
        location_name="선릉점",
        latitude=latitude,
        longitude=127.0489,
        source_type=SourceType.EXCEL,
        source_id=str(index),
        device_type=device_type,
    )


def success_page(*, html: str = SUCCESS_HTML, observed: int = 1) -> SearchPage:
    return SearchPage(SEARCH_URL, html, "RESULTS", observed, True)


@dataclass
class FakeDriver:
    quit_calls: int = 0

    def quit(self) -> None:
        self.quit_calls += 1


class FakeSession:
    def __init__(self, outcomes) -> None:
        self.outcomes = deque(outcomes)
        self.search_calls = 0
        self.evidence_directories: list[Path] = []
        self.driver = FakeDriver()

    def search(self, search_task: SearchTask) -> SearchPage:
        self.search_calls += 1
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def save_evidence(self, directory: Path, *, html: str | None = None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        html_path = directory / "page.html"
        screenshot_path = directory / "screenshot.png"
        html_path.write_text(html or "", encoding="utf-8")
        screenshot_path.write_bytes(b"png")
        self.evidence_directories.append(directory)
        return html_path, screenshot_path


class EvidenceDamagedSession(FakeSession):
    def save_evidence(self, directory: Path, *, html: str | None = None):
        raise BrowserSessionError(
            "screenshot session disconnected",
            last_url=SEARCH_URL,
            html=html or "",
        )


class PathReportingEvidenceSession(FakeSession):
    def save_evidence(self, directory: Path, *, html: str | None = None):
        raise OSError(f"cannot capture {directory}")


class CloseFailSession(FakeSession):
    def close(self):
        raise RuntimeError("close failed")


class FakeBrowserFactory:
    def __init__(self, sessions) -> None:
        self.sessions = deque(sessions)
        self.create_calls = []

    def create(self, device_type, latitude, longitude):
        self.create_calls.append((device_type, latitude, longitude))
        outcome = self.sessions.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeRepository:
    def __init__(self) -> None:
        self.saved = []

    def save(self, snapshot, results):
        self.saved.append((snapshot, tuple(results)))
        return len(self.saved)


class RaisingParser:
    def parse(self, page):
        raise ValueError("required result-card structure changed")


def browser_error(error_type, message="temporary failure", *, html=SUCCESS_HTML):
    return error_type(message, last_url=SEARCH_URL, html=html)


def artifact_root(tmp_path: Path) -> Path:
    suffix = hashlib.sha256(str(tmp_path).encode("utf-8")).hexdigest()[:8]
    return tmp_path.parent / "a" / suffix


def collector(
    tmp_path: Path,
    sessions,
    *,
    parser=None,
    failure_limit: int = 5,
    review_export: bool = False,
    redact=lambda value: value,
    retry_logger=lambda value: None,
    repository=None,
):
    repository = repository or FakeRepository()
    factory = FakeBrowserFactory(sessions)
    instance = KeywordDiscoveryCollector(
        factory,
        parser or DomResultParser(),
        ResultValidator(),
        OwnStoreMatcher((OwnStore("S1", "육수당 선릉점", "1001"),)),
        repository,
        artifact_root=artifact_root(tmp_path),
        result_limit=20,
        max_retries=2,
        failure_limit=failure_limit,
        clock=lambda: datetime(2026, 9, 2, 12, 0, 0),
        review_export=review_export,
        redact=redact,
        retry_logger=retry_logger,
    )
    return instance, factory, repository


def test_immediate_success_persists_matched_final_result_and_closes_browser(tmp_path: Path):
    session = FakeSession([success_page()])
    instance, factory, repository = collector(tmp_path, [session])

    summary = instance.run([task()], "11111111-1111-1111-1111-111111111111")

    assert summary.total_tasks == 1
    assert summary.processed_tasks == 1
    assert summary.status_counts == {CollectStatus.SUCCESS: 1}
    assert summary.aborted is False
    assert len(repository.saved) == 1
    snapshot, results = repository.saved[0]
    assert snapshot.collect_status is CollectStatus.SUCCESS
    assert snapshot.observed_result_count == 1
    assert snapshot.result_end_reached is True
    assert snapshot.final_url == SEARCH_URL
    assert snapshot.parser_version == "dom-v5"
    assert results[0].is_own_store is True
    assert results[0].matched_store_id == "S1"
    assert results[0].is_target_store is True
    assert len(factory.create_calls) == 1
    assert factory.create_calls == [(DeviceType.MOBILE, 37.5048, 127.0489)]
    assert session.driver.quit_calls == 1


def test_target_store_requires_matched_store_id_to_equal_task_target():
    brand_store = ParsedResult(
        1,
        1,
        "2002",
        "육수당 다른 지점",
        "한식",
        False,
        "https://m.place.naver.com/restaurant/2002",
        None,
        True,
        "S2",
        MatchMethod.PLACE_ID,
    )

    assert _mark_target_store(brand_store, "S1").is_target_store is False
    assert _mark_target_store(brand_store, "S2").is_target_store is True


def test_final_html_is_authoritative_for_persisted_count_and_end_state(tmp_path: Path):
    stale_metadata_page = SearchPage(SEARCH_URL, SUCCESS_HTML, "RESULTS", 19, False)
    session = FakeSession([stale_metadata_page])
    instance, _, repository = collector(tmp_path, [session])

    instance.run([task()], "run-html-authoritative")

    snapshot, _ = repository.saved[0]
    assert snapshot.collect_status is CollectStatus.SUCCESS
    assert snapshot.observed_result_count == 1
    assert snapshot.result_end_reached is True


def test_browser_confirmed_expansion_end_survives_final_html_recount(tmp_path: Path):
    html_without_end_marker = SUCCESS_HTML.replace(
        '<div data-naver-search-end>검색 결과의 끝</div>',
        "",
    )
    page = SearchPage(SEARCH_URL, html_without_end_marker, "RESULTS", 1, True)
    session = FakeSession([page])
    instance, _, repository = collector(tmp_path, [session])

    instance.run([task()], "run-browser-confirmed-end")

    snapshot, _ = repository.saved[0]
    assert snapshot.collect_status is CollectStatus.SUCCESS
    assert snapshot.result_end_reached is True


def test_transient_failure_then_success_retries_without_persisting_or_evidence_for_first_attempt(
    tmp_path: Path,
):
    session = FakeSession([browser_error(QueryMismatch), success_page()])
    instance, _, repository = collector(tmp_path, [session])

    summary = instance.run([task()], "run-retry-success")

    assert summary.status_counts == {CollectStatus.SUCCESS: 1}
    assert session.search_calls == 2
    assert len(repository.saved) == 1
    assert session.evidence_directories == []
    assert not artifact_root(tmp_path).exists()


@pytest.mark.parametrize(
    ("error_type", "expected_status"),
    [
        (SearchStateTimeout, CollectStatus.LOAD_TIMEOUT),
        (QueryMismatch, CollectStatus.QUERY_MISMATCH),
        (SearchPageError, CollectStatus.SEARCH_ERROR),
    ],
)
def test_three_exhausted_attempts_persist_only_final_attempt_and_evidence(
    tmp_path: Path,
    error_type,
    expected_status: CollectStatus,
):
    errors = [browser_error(error_type, f"failure-{number}") for number in range(1, 4)]
    session = FakeSession(errors)
    instance, _, repository = collector(tmp_path, [session])
    search_task = task()

    summary = instance.run([search_task], "run-exhausted")

    assert session.search_calls == 3
    assert len(repository.saved) == 1
    snapshot, results = repository.saved[0]
    assert snapshot.collect_status is expected_status
    assert snapshot.collect_msg == "failure-3"
    assert snapshot.observed_result_count == 1
    assert snapshot.result_end_reached is True
    assert results == ()
    evidence = artifact_root(tmp_path) / "run-exhausted" / build_task_key(search_task)
    assert (evidence / "page.html").read_text(encoding="utf-8") == SUCCESS_HTML
    assert (evidence / "screenshot.png").read_bytes() == b"png"
    assert summary.status_counts == {expected_status: 1}


def test_no_result_is_not_retried_and_has_no_evidence(tmp_path: Path):
    page = SearchPage(SEARCH_URL, "<p>검색 결과가 없습니다.</p>", "NO_RESULT", 0, True)
    session = FakeSession([page, success_page()])
    instance, _, repository = collector(tmp_path, [session])

    summary = instance.run([task()], "run-no-result")

    assert session.search_calls == 1
    assert repository.saved[0][0].collect_status is CollectStatus.NO_RESULT
    assert repository.saved[0][1] == ()
    assert summary.status_counts == {CollectStatus.NO_RESULT: 1}
    assert not artifact_root(tmp_path).exists()


def test_no_result_state_ignores_stale_result_cards_and_persists_zero_rows(tmp_path: Path):
    html = SUCCESS_HTML + "<p>검색 결과가 없습니다.</p>"
    page = SearchPage(SEARCH_URL, html, "NO_RESULT", 0, True)
    session = FakeSession([page])
    instance, _, repository = collector(tmp_path, [session])

    summary = instance.run([task()], "run-stale-no-result")

    snapshot, results = repository.saved[0]
    assert snapshot.collect_status is CollectStatus.NO_RESULT
    assert snapshot.observed_result_count == 0
    assert snapshot.result_end_reached is True
    assert results == ()
    assert summary.status_counts == {CollectStatus.NO_RESULT: 1}
    assert not artifact_root(tmp_path).exists()


def test_parser_structure_failure_is_not_retried_but_saves_evidence(tmp_path: Path):
    session = FakeSession([success_page(), success_page()])
    instance, _, repository = collector(tmp_path, [session], parser=RaisingParser())
    search_task = task()

    instance.run([search_task], "run-parser-error")

    assert session.search_calls == 1
    snapshot, results = repository.saved[0]
    assert snapshot.collect_status is CollectStatus.PARSER_ERROR
    assert "required result-card structure changed" in snapshot.collect_msg
    assert results == ()
    evidence = artifact_root(tmp_path) / "run-parser-error" / build_task_key(search_task)
    assert (evidence / "page.html").exists()
    assert (evidence / "screenshot.png").exists()


def test_browser_session_damage_closes_and_recreates_session_before_retry(tmp_path: Path):
    damaged = FakeSession([browser_error(BrowserSessionError, "session disconnected")])
    replacement = FakeSession([success_page()])
    instance, factory, repository = collector(tmp_path, [damaged, replacement])

    instance.run([task()], "run-recreated")

    assert len(factory.create_calls) == 2
    assert damaged.driver.quit_calls == 1
    assert replacement.driver.quit_calls == 1
    assert repository.saved[0][0].collect_status is CollectStatus.SUCCESS


def test_session_close_failure_falls_back_to_driver_quit(tmp_path: Path):
    session = CloseFailSession([success_page()])
    instance, _, _ = collector(tmp_path, [session])

    instance.run([task()], "run-close-fallback")

    assert session.driver.quit_calls == 1


def test_evidence_session_damage_closes_and_recreates_before_next_same_profile_task(
    tmp_path: Path,
):
    damaged = EvidenceDamagedSession(
        [success_page(html=PARTIAL_HTML, observed=2), success_page()]
    )
    replacement = FakeSession([success_page()])
    instance, factory, repository = collector(tmp_path, [damaged, replacement])

    summary = instance.run(
        [task(1), task(2, query="강남역 국밥")],
        "run-evidence-session-damage",
    )

    assert summary.status_counts == {
        CollectStatus.PARTIAL: 1,
        CollectStatus.SUCCESS: 1,
    }
    assert len(factory.create_calls) == 2
    assert damaged.search_calls == 1
    assert damaged.driver.quit_calls == 1
    assert replacement.search_calls == 1
    assert replacement.driver.quit_calls == 1
    assert [snapshot.collect_status for snapshot, _ in repository.saved] == [
        CollectStatus.PARTIAL,
        CollectStatus.SUCCESS,
    ]


def test_final_failure_does_not_prevent_next_distinct_task(tmp_path: Path):
    session = FakeSession(
        [
            browser_error(SearchStateTimeout),
            browser_error(SearchStateTimeout),
            browser_error(SearchStateTimeout),
        ]
    )
    next_session = FakeSession([success_page()])
    instance, _, repository = collector(tmp_path, [session, next_session])

    summary = instance.run([task(1), task(2, device_type=DeviceType.PC)], "run-continue")

    assert summary.processed_tasks == 2
    assert summary.status_counts == {
        CollectStatus.LOAD_TIMEOUT: 1,
        CollectStatus.SUCCESS: 1,
    }
    assert [saved[0].collect_status for saved in repository.saved] == [
        CollectStatus.LOAD_TIMEOUT,
        CollectStatus.SUCCESS,
    ]
    assert session.driver.quit_calls == 1
    assert next_session.driver.quit_calls == 1


def test_aborts_after_five_identical_consecutive_final_failures(tmp_path: Path):
    repeated_failures = [browser_error(SearchStateTimeout, "same timeout") for _ in range(15)]
    session = FakeSession(repeated_failures)
    instance, _, repository = collector(tmp_path, [session], failure_limit=5)
    tasks = [task(index, query=f"선릉역 국밥 {index}") for index in range(1, 8)]

    summary = instance.run(tasks, "run-abort")

    assert summary.total_tasks == 7
    assert summary.processed_tasks == 5
    assert summary.status_counts == {CollectStatus.LOAD_TIMEOUT: 5}
    assert summary.aborted is True
    assert "5 identical consecutive failures" in summary.abort_reason
    assert len(repository.saved) == 5
    assert session.search_calls == 15


def test_evidence_diagnostics_do_not_change_identical_failure_abort_identity(tmp_path: Path):
    repeated_failures = [browser_error(SearchStateTimeout, "same timeout") for _ in range(6)]
    session = PathReportingEvidenceSession(repeated_failures)
    instance, _, repository = collector(tmp_path, [session], failure_limit=2)

    summary = instance.run(
        [task(1), task(2, query="강남역 국밥"), task(3, query="역삼역 국밥")],
        "run-evidence-identity",
    )

    assert summary.aborted is True
    assert summary.processed_tasks == 2
    assert len(repository.saved) == 2


def test_validation_error_and_success_do_not_write_evidence(tmp_path: Path):
    validation_error_html = """
    <li data-naver-place-card data-place-id="1001">
      <a data-place-name href="https://m.place.naver.com/restaurant/9999">잘못된 URL</a>
    </li>
    <div data-naver-search-end>검색 결과의 끝</div>
    """
    sessions = [FakeSession([success_page(html=validation_error_html)])]
    instance, _, repository = collector(tmp_path, sessions)

    instance.run([task()], "run-validation-error")

    assert repository.saved[0][0].collect_status is CollectStatus.VALIDATION_ERROR
    assert not artifact_root(tmp_path).exists()


def test_partial_writes_evidence_and_caps_collection_message_at_1000_characters(tmp_path: Path):
    class LongMessageValidator:
        def validate(self, parsed, requested_limit):
            from scripts.keyword_discovery_rank.validation import ValidationOutcome

            return ValidationOutcome(CollectStatus.PARTIAL, parsed.results[:1], "x" * 1200, 2)

    search_task = task()
    session = FakeSession([success_page(html=PARTIAL_HTML, observed=2)])
    repository = FakeRepository()
    instance = KeywordDiscoveryCollector(
        FakeBrowserFactory([session]),
        DomResultParser(),
        LongMessageValidator(),
        OwnStoreMatcher((OwnStore("S1", "육수당 선릉점", "1001"),)),
        repository,
        artifact_root=artifact_root(tmp_path),
        result_limit=20,
        clock=lambda: datetime(2026, 9, 2, 12, 0, 0),
    )

    instance.run([search_task], "run-partial")

    snapshot, _ = repository.saved[0]
    assert snapshot.collect_status is CollectStatus.PARTIAL
    assert len(snapshot.collect_msg) == 1000
    evidence = artifact_root(tmp_path) / "run-partial" / build_task_key(search_task)
    assert (evidence / "page.html").exists()
    assert (evidence / "screenshot.png").exists()


@pytest.mark.parametrize("result_limit", [0, 21])
def test_collector_rejects_result_limit_outside_naver_boundary(tmp_path: Path, result_limit: int):
    with pytest.raises(ValueError, match="between 1 and 20"):
        KeywordDiscoveryCollector(
            FakeBrowserFactory([]),
            DomResultParser(),
            ResultValidator(),
            OwnStoreMatcher(()),
            FakeRepository(),
            artifact_root=tmp_path,
            result_limit=result_limit,
        )


def test_review_export_writes_success_html_screenshot_and_structured_final_result(tmp_path: Path):
    search_task = task()
    session = FakeSession([success_page()])
    instance, _, _ = collector(tmp_path, [session], review_export=True)

    instance.run([search_task], "run-review")

    directory = artifact_root(tmp_path) / "run-review" / build_task_key(search_task)
    assert (directory / "page.html").read_text(encoding="utf-8") == SUCCESS_HTML
    assert (directory / "screenshot.png").read_bytes() == b"png"
    export = json.loads((directory / "snapshot-results.json").read_text(encoding="utf-8"))
    assert export == {
        "format_version": 1,
        "results": [
            {
                "category": None,
                "detail_url": "https://m.place.naver.com/restaurant/1001",
                "distance_text": None,
                "is_ad": False,
                "is_own_store": True,
                "is_target_store": True,
                "match_method": "PLACE_ID",
                "matched_store_id": "S1",
                "organic_rank": 1,
                "place_id": "1001",
                "place_name": "육수당 선릉점",
                "raw_position": 1,
            }
        ],
        "retry_history": [],
        "snapshot": {
            "collect_msg": None,
            "collect_status": "SUCCESS",
            "collected_at": "2026-09-02T12:00:00",
            "device_type": "MOBILE",
            "final_url": SEARCH_URL,
            "latitude": 37.5048,
            "location_name": "선릉점",
            "longitude": 127.0489,
            "normalized_query": "선릉역 국밥",
            "observed_result_count": 1,
            "parser_version": "dom-v5",
            "query": "선릉역 국밥",
            "requested_result_limit": 20,
            "result_end_reached": True,
            "run_id": "run-review",
            "source_id": "1",
            "source_type": "EXCEL",
            "target_store_id": "S1",
            "target_store_name": "육수당 선릉점",
            "task_key": build_task_key(search_task),
        },
    }


def test_retry_history_redacts_secrets_in_log_and_export(tmp_path: Path):
    search_task = task()
    secret = "database-password"
    session = FakeSession([browser_error(QueryMismatch, f"temporary {secret}"), success_page()])
    retry_messages = []
    instance, _, _ = collector(
        tmp_path,
        [session],
        review_export=True,
        redact=lambda value: value.replace(secret, "[REDACTED]"),
        retry_logger=retry_messages.append,
    )

    instance.run([search_task], "rr")

    export_path = (
        artifact_root(tmp_path)
        / "rr"
        / build_task_key(search_task)
        / "snapshot-results.json"
    )
    rendered = export_path.read_text(encoding="utf-8")
    assert secret not in rendered
    assert secret not in " ".join(retry_messages)
    assert "[REDACTED]" in rendered
    assert json.loads(rendered)["retry_history"] == [
        {
            "attempt": 1,
            "message": "temporary [REDACTED]",
            "status": "QUERY_MISMATCH",
        }
    ]


def test_task_local_repository_failure_continues_to_next_task(tmp_path: Path):
    class LocalThenSuccessfulRepository(FakeRepository):
        def save(self, snapshot, results):
            if not self.saved:
                self.saved.append((snapshot, tuple(results)))
                raise TaskPersistenceError("bad card data")
            return super().save(snapshot, results)

    repository = LocalThenSuccessfulRepository()
    session = FakeSession([success_page(), success_page()])
    instance, _, _ = collector(tmp_path, [session], repository=repository)

    summary = instance.run([task(1), task(2, query="강남역 국밥")], "run-local-save")

    assert summary.processed_tasks == 2
    assert summary.persistence_failures == 1
    assert session.search_calls == 2


def test_fatal_repository_failure_aborts_before_next_search_and_closes_browser(tmp_path: Path):
    class FatalRepository:
        def save(self, snapshot, results):
            raise FatalRepositoryError("connection lost")

    session = FakeSession([success_page(), success_page()])
    instance, _, _ = collector(tmp_path, [session], repository=FatalRepository())

    with pytest.raises(FatalRepositoryError, match="connection lost"):
        instance.run([task(1), task(2, query="강남역 국밥")], "run-fatal-save")

    assert session.search_calls == 1
    assert session.driver.quit_calls == 1
