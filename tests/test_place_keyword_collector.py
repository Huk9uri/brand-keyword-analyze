from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.place_keyword_collector.collector as collector_module
from scripts.place_keyword_collector.browser import (
    BlockedPageError,
    PlaceBrowserError,
    PlaceLoadTimeout,
    PlacePage,
)
from scripts.place_keyword_collector.change import content_hash
from scripts.place_keyword_collector.collector import PlaceKeywordCollector
from scripts.place_keyword_collector.models import (
    CollectedKeyword,
    KeywordCollectStatus,
    PreviousVersion,
    RankPlaceTarget,
    RefreshPolicy,
)
from scripts.place_keyword_collector.parser import KeywordListParser


RUN_ID = "11111111-1111-1111-1111-111111111111"
RANK_RUN_ID = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
PLACE_URL = "https://m.place.naver.com/restaurant/{place_id}/home"


def target(place_id: str = "13149768") -> RankPlaceTarget:
    return RankPlaceTarget(place_id, f"매장 {place_id}")


def page(place_id: str = "13149768", *keywords: str) -> PlacePage:
    values = ",".join(f'"{keyword}"' for keyword in keywords)
    html = f'<script>{{"id":"{place_id}","keywordList":[{values}]}}</script>'
    return PlacePage(PLACE_URL.format(place_id=place_id), html)


def previous(
    *,
    checked_at: datetime,
    values: tuple[str, ...] = ("이전",),
    snapshot_id: int = 73,
) -> PreviousVersion:
    rows = tuple(
        CollectedKeyword(index, value, value.casefold())
        for index, value in enumerate(values, start=1)
    )
    return PreviousVersion(
        effective_snapshot_id=snapshot_id,
        content_hash=content_hash(rows),
        checked_at=checked_at,
        status=KeywordCollectStatus.SUCCESS,
    )


def blocked(message: str = "same blocked") -> BlockedPageError:
    return BlockedPageError(
        message,
        last_url="https://m.place.naver.com/blocked",
        html="<html>blocked</html>",
    )


def timeout(message: str = "same timeout") -> PlaceLoadTimeout:
    return PlaceLoadTimeout(
        message,
        last_url="https://m.place.naver.com/loading",
        html="<html>loading</html>",
    )


@dataclass(frozen=True)
class SavedCall:
    snapshot: object
    keywords: tuple[CollectedKeyword, ...]


class FakeRepository:
    def __init__(self, previous_by_place=None, events=None) -> None:
        self.previous_by_place = previous_by_place or {}
        self.events = events if events is not None else []
        self.saved: list[SavedCall] = []

    def get_previous(self, place_id: str):
        self.events.append(("previous", place_id))
        return self.previous_by_place.get(place_id)

    def save(self, snapshot, keywords):
        call = SavedCall(snapshot, tuple(keywords))
        self.saved.append(call)
        return len(self.saved)


class FakeBrowser:
    def __init__(self, outcomes, events=None, *, evidence_error=None) -> None:
        self.outcomes = deque(outcomes)
        self.events = events if events is not None else []
        self.fetch_calls: list[str] = []
        self.evidence_calls: list[tuple[Path, str]] = []
        self.close_calls = 0
        self.evidence_error = evidence_error

    def fetch(self, place_target: RankPlaceTarget) -> PlacePage:
        self.fetch_calls.append(place_target.place_id)
        self.events.append(("fetch", place_target.place_id))
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def save_evidence(self, directory: Path, html: str):
        if self.evidence_error is not None:
            raise self.evidence_error
        directory = Path(directory)
        self.evidence_calls.append((directory, html))
        directory.mkdir(parents=True, exist_ok=True)
        html_path = directory / "page.html"
        screenshot_path = directory / "screenshot.png"
        html_path.write_text(html, encoding="utf-8")
        screenshot_path.write_bytes(b"png")
        return html_path, screenshot_path

    def close(self) -> None:
        self.close_calls += 1


class FakeBrowserFactory:
    def __init__(self, browser: FakeBrowser, events=None) -> None:
        self.browser = browser
        self.events = events if events is not None else []
        self.create_calls = 0

    def create(self) -> FakeBrowser:
        self.create_calls += 1
        self.events.append(("create", None))
        return self.browser


def collector(
    tmp_path: Path,
    outcomes,
    *,
    previous_by_place=None,
    failure_limit: int = 5,
    events=None,
    repository=None,
    max_retries: int = 2,
    sleeper=None,
    evidence_error=None,
):
    events = events if events is not None else []
    browser = FakeBrowser(outcomes, events, evidence_error=evidence_error)
    factory = FakeBrowserFactory(browser, events)
    repository = repository or FakeRepository(previous_by_place, events)
    instance = PlaceKeywordCollector(
        factory,
        KeywordListParser(),
        repository,
        artifact_root=tmp_path / "artifacts",
        max_retries=max_retries,
        failure_limit=failure_limit,
        clock=lambda: NOW,
        sleeper=sleeper or (lambda _seconds: None),
    )
    return instance, factory, browser, repository


def test_all_previous_lookups_precede_browser_creation_and_recent_targets_are_reused(
    tmp_path: Path,
):
    events: list[tuple[str, str | None]] = []
    targets = [target("1"), target("2")]
    recent = previous(checked_at=NOW - timedelta(days=1))
    instance, factory, browser, repository = collector(
        tmp_path,
        [],
        previous_by_place={"1": recent, "2": recent},
        events=events,
    )

    summary = instance.run(targets, RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    assert events == [("previous", "1"), ("previous", "2")]
    assert factory.create_calls == 0
    assert browser.fetch_calls == []
    assert repository.saved == []
    assert summary.reused == 2
    assert summary.status_counts == {}


def test_changed_success_persists_keywords_once_and_reuses_browser_for_targets(tmp_path: Path):
    targets = [target("1"), target("2")]
    instance, factory, browser, repository = collector(
        tmp_path,
        [page("1", "순대", "순댓국", "국밥", "수육"), page("2", "설렁탕")],
    )

    summary = instance.run(targets, RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    assert factory.create_calls == 1
    assert browser.fetch_calls == ["1", "2"]
    assert browser.close_calls == 1
    assert len(repository.saved) == 2
    first = repository.saved[0]
    assert first.snapshot.is_changed is True
    assert first.snapshot.source_url == PLACE_URL.format(place_id="1")
    assert [keyword.raw_keyword for keyword in first.keywords] == [
        "순대",
        "순댓국",
        "국밥",
        "수육",
    ]
    assert summary.status_counts == {KeywordCollectStatus.SUCCESS: 2}


@pytest.mark.parametrize(
    ("error_factory", "expected_status"),
    [
        (blocked, KeywordCollectStatus.BLOCKED),
        (timeout, KeywordCollectStatus.LOAD_TIMEOUT),
    ],
)
def test_retryable_failure_uses_three_total_attempts_and_persists_only_final_attempt(
    tmp_path: Path,
    error_factory,
    expected_status: KeywordCollectStatus,
):
    errors = [error_factory(f"failure-{number}") for number in range(1, 4)]
    instance, _, browser, repository = collector(tmp_path, errors)

    summary = instance.run([target()], RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    assert browser.fetch_calls == ["13149768"] * 3
    assert len(repository.saved) == 1
    assert repository.saved[0].snapshot.status is expected_status
    assert repository.saved[0].snapshot.collect_msg == "failure-3"
    assert repository.saved[0].keywords == ()
    evidence_dir = tmp_path / "artifacts" / RUN_ID / "13149768"
    assert browser.evidence_calls == [(evidence_dir, errors[-1].html)]
    assert (evidence_dir / "page.html").read_text(encoding="utf-8") == errors[-1].html
    assert summary.status_counts == {expected_status: 1}


@pytest.mark.parametrize("error_factory", [blocked, timeout])
def test_retryable_failure_waits_with_exact_bounded_backoff(
    tmp_path: Path,
    error_factory,
):
    sleeps: list[float] = []
    instance, _, _, _ = collector(
        tmp_path,
        [error_factory("first"), error_factory("second"), page("13149768", "순대")],
        sleeper=sleeps.append,
    )

    instance.run([target()], RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    assert sleeps == [1.0, 2.0]


def test_retry_backoff_is_capped_for_large_retry_counts(tmp_path: Path):
    sleeps: list[float] = []
    instance, _, _, _ = collector(
        tmp_path,
        [timeout(str(index)) for index in range(6)],
        max_retries=5,
        sleeper=sleeps.append,
    )

    instance.run([target()], RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    assert sleeps == [1.0, 2.0, 4.0, 8.0, 8.0]


def test_transient_retryable_failure_then_success_persists_only_success_without_evidence(
    tmp_path: Path,
):
    instance, _, browser, repository = collector(
        tmp_path,
        [blocked("temporary"), page("13149768", "순대")],
    )

    summary = instance.run([target()], RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    assert browser.fetch_calls == ["13149768", "13149768"]
    assert len(repository.saved) == 1
    assert repository.saved[0].snapshot.status is KeywordCollectStatus.SUCCESS
    assert browser.evidence_calls == []
    assert summary.status_counts == {KeywordCollectStatus.SUCCESS: 1}


@pytest.mark.parametrize(
    ("bad_page", "expected_status"),
    [
        (
            PlacePage(PLACE_URL.format(place_id="13149768"), "<script>{}</script>"),
            KeywordCollectStatus.PARSE_ERROR,
        ),
        (
            PlacePage(
                PLACE_URL.format(place_id="13149768"),
                '<script>{"id":"999","keywordList":["wrong"]}</script>',
            ),
            KeywordCollectStatus.PLACE_MISMATCH,
        ),
    ],
)
def test_parser_failures_are_not_retried_and_save_final_evidence(
    tmp_path: Path,
    bad_page: PlacePage,
    expected_status: KeywordCollectStatus,
):
    instance, _, browser, repository = collector(
        tmp_path,
        [bad_page, page("13149768", "must-not-fetch")],
    )

    instance.run([target()], RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    assert browser.fetch_calls == ["13149768"]
    assert repository.saved[0].snapshot.status is expected_status
    assert browser.evidence_calls == [
        (tmp_path / "artifacts" / RUN_ID / "13149768", bad_page.html)
    ]


def test_generic_browser_error_with_captured_html_saves_evidence_then_remains_fatal(
    tmp_path: Path,
):
    error = PlaceBrowserError(
        "Place browser state inspection failed",
        last_url=PLACE_URL.format(place_id="13149768"),
        html="<html>captured failure</html>",
    )
    instance, _, browser, repository = collector(tmp_path, [error])

    with pytest.raises(PlaceBrowserError) as raised:
        instance.run([target()], RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    evidence_dir = tmp_path / "artifacts" / RUN_ID / "13149768"
    assert browser.evidence_calls == [(evidence_dir, error.html)]
    assert repository.saved == []
    assert any("failure evidence saved" in note for note in raised.value.__notes__)


def test_evidence_screenshot_failure_keeps_html_without_fake_screenshot_and_warns(
    tmp_path: Path,
):
    bad_page = PlacePage(PLACE_URL.format(place_id="13149768"), "<script>{}</script>")
    instance, _, _, repository = collector(
        tmp_path,
        [bad_page],
        evidence_error=RuntimeError("screenshot secret detail"),
    )

    with pytest.warns(RuntimeWarning, match="screenshot was not saved") as warnings:
        instance.run([target()], RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    evidence_dir = tmp_path / "artifacts" / RUN_ID / "13149768"
    assert (evidence_dir / "page.html").read_text(encoding="utf-8") == bad_page.html
    assert not (evidence_dir / "screenshot.png").exists()
    assert "secret" not in str(warnings[0].message)
    assert repository.saved[0].snapshot.status is KeywordCollectStatus.PARSE_ERROR


@pytest.mark.parametrize(
    ("run_id", "rank_run_id"),
    [("../escape", RANK_RUN_ID), (RUN_ID, "not-a-uuid")],
)
def test_collector_rejects_non_uuid_run_identifiers_before_side_effects(
    tmp_path: Path,
    run_id: str,
    rank_run_id: str,
):
    events: list[tuple[str, str | None]] = []
    instance, factory, _, repository = collector(tmp_path, [], events=events)

    with pytest.raises(ValueError, match="UUID"):
        instance.run([target()], run_id, rank_run_id, RefreshPolicy.MONTHLY)

    assert events == []
    assert factory.create_calls == 0
    assert repository.saved == []


def test_evidence_directory_rejects_resolved_path_outside_artifact_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    artifact_root = tmp_path / "artifacts"
    resolved_root = artifact_root.absolute()
    outside = (tmp_path / "outside").absolute()

    def fake_resolve(path: Path, strict: bool = False) -> Path:
        if path == artifact_root:
            return resolved_root
        return outside

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    with pytest.raises(ValueError, match="outside artifact root"):
        collector_module._evidence_directory(artifact_root, RUN_ID, "13149768")


def test_evidence_path_rejection_warns_without_masking_generic_browser_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    error = PlaceBrowserError(
        "Place browser state inspection failed",
        last_url=PLACE_URL.format(place_id="13149768"),
        html="<html>captured failure</html>",
    )
    instance, _, _, _ = collector(tmp_path, [error])
    monkeypatch.setattr(
        collector_module,
        "_evidence_directory",
        lambda *_args: (_ for _ in ()).throw(ValueError("outside artifact root")),
    )

    with pytest.warns(RuntimeWarning, match="could not save failure evidence"):
        with pytest.raises(PlaceBrowserError) as raised:
            instance.run([target()], RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    assert raised.value is error
    assert any("could not be saved" in note for note in raised.value.__notes__)


def test_final_failure_keeps_previous_effective_version(tmp_path: Path):
    old = previous(checked_at=NOW - timedelta(days=40), snapshot_id=91)
    instance, _, _, repository = collector(
        tmp_path,
        [timeout(), timeout(), timeout()],
        previous_by_place={"13149768": old},
    )

    instance.run([target()], RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    saved = repository.saved[0].snapshot
    assert saved.effective_snapshot_id == 91
    assert saved.content_hash is None
    assert saved.is_changed is False


def test_force_refresh_collects_a_recent_target(tmp_path: Path):
    recent = previous(checked_at=NOW - timedelta(days=1))
    instance, factory, _, repository = collector(
        tmp_path,
        [page("13149768", "새 키워드")],
        previous_by_place={"13149768": recent},
    )

    summary = instance.run(
        [target()],
        RUN_ID,
        RANK_RUN_ID,
        RefreshPolicy.MONTHLY,
        force_refresh=True,
    )

    assert factory.create_calls == 1
    assert len(repository.saved) == 1
    assert summary.reused == 0


def test_aborts_after_five_identical_consecutive_final_failures(tmp_path: Path):
    targets = [target(str(index)) for index in range(1, 7)]
    instance, _, browser, repository = collector(
        tmp_path,
        [timeout() for _ in range(15)],
        failure_limit=5,
    )

    summary = instance.run(targets, RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    assert browser.fetch_calls == [str(index) for index in range(1, 6) for _ in range(3)]
    assert len(repository.saved) == 5
    assert summary.aborted is True
    assert summary.processed_count == 5
    assert summary.failed_count == 5
    assert "5 identical consecutive failures" in summary.abort_reason


def test_a_different_failure_identity_restarts_the_abort_counter(tmp_path: Path):
    targets = [target(str(index)) for index in range(1, 8)]
    outcomes = []
    for number in range(1, 8):
        message = "first" if number <= 4 else "different"
        outcomes.extend(timeout(message) for _ in range(3))
    instance, _, browser, repository = collector(tmp_path, outcomes, failure_limit=5)

    summary = instance.run(targets, RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    assert len(browser.fetch_calls) == 21
    assert len(repository.saved) == 7
    assert summary.aborted is False


@pytest.mark.parametrize("reset_page", [page("5", "정상"), page("5")])
def test_success_or_empty_resets_the_identical_failure_counter(
    tmp_path: Path,
    reset_page: PlacePage,
):
    targets = [target(str(index)) for index in range(1, 10)]
    outcomes = []
    for _ in range(4):
        outcomes.extend(timeout() for _ in range(3))
    outcomes.append(reset_page)
    for _ in range(4):
        outcomes.extend(timeout() for _ in range(3))
    instance, _, browser, repository = collector(tmp_path, outcomes, failure_limit=5)

    summary = instance.run(targets, RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    assert len(browser.fetch_calls) == 25
    assert len(repository.saved) == 9
    assert summary.aborted is False


def test_browser_closes_in_finally_when_repository_save_raises(tmp_path: Path):
    class RaisingRepository(FakeRepository):
        def save(self, snapshot, keywords):
            raise RuntimeError("save failed")

    repository = RaisingRepository()
    instance, _, browser, _ = collector(
        tmp_path,
        [page("13149768", "순대")],
        repository=repository,
    )

    with pytest.raises(RuntimeError, match="save failed"):
        instance.run([target()], RUN_ID, RANK_RUN_ID, RefreshPolicy.MONTHLY)

    assert browser.close_calls == 1
