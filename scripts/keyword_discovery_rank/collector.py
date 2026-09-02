from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable

from bs4 import BeautifulSoup

from .browser import (
    BrowserSessionError,
    NO_RESULT_TEXTS,
    QueryMismatch,
    RESULT_CARD_SELECTOR,
    RESULT_END_SELECTOR,
    RESULT_END_TEXTS,
    SearchPageError,
    SearchStateTimeout,
)
from .models import CollectStatus, ParsedResult, SearchPage, SearchSnapshot, SearchTask
from .parser import PARSER_VERSION
from .task_source import build_task_key, normalize_query


EVIDENCE_STATUSES = frozenset(
    {
        CollectStatus.PARTIAL,
        CollectStatus.LOAD_TIMEOUT,
        CollectStatus.QUERY_MISMATCH,
        CollectStatus.PARSER_ERROR,
        CollectStatus.SEARCH_ERROR,
    }
)
_NON_FAILURE_STATUSES = frozenset({CollectStatus.SUCCESS, CollectStatus.NO_RESULT})
_EMPTY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf"
    b"\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    total_tasks: int
    processed_tasks: int
    status_counts: Mapping[CollectStatus, int]
    persistence_failures: int = 0
    aborted: bool = False
    abort_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status_counts", MappingProxyType(dict(self.status_counts)))


@dataclass(frozen=True)
class _FinalAttempt:
    snapshot: SearchSnapshot
    results: tuple[ParsedResult, ...]
    html: str
    retryable: bool = False
    session_damaged: bool = False


class KeywordDiscoveryCollector:
    """Orchestrate search, parsing, validation, matching, and persistence."""

    def __init__(
        self,
        browser_factory: Any,
        parser: Any,
        validator: Any,
        matcher: Any,
        repository: Any,
        *,
        artifact_root: str | Path,
        result_limit: int = 20,
        max_retries: int = 2,
        failure_limit: int = 5,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        if isinstance(result_limit, bool) or not isinstance(result_limit, int) or result_limit <= 0:
            raise ValueError("result_limit must be a positive integer")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if isinstance(failure_limit, bool) or not isinstance(failure_limit, int) or failure_limit <= 0:
            raise ValueError("failure_limit must be a positive integer")

        self.browser_factory = browser_factory
        self.parser = parser
        self.validator = validator
        self.matcher = matcher
        self.repository = repository
        self.artifact_root = Path(artifact_root)
        self.result_limit = result_limit
        self.max_retries = max_retries
        self.failure_limit = failure_limit
        self.clock = clock
        self._session: Any | None = None
        self._session_profile: tuple[object, ...] | None = None

    def run(self, tasks: Iterable[SearchTask], run_id: str) -> RunSummary:
        unique_tasks = _deduplicate_tasks(tasks)
        status_counts: Counter[CollectStatus] = Counter()
        persistence_failures = 0
        processed_tasks = 0
        aborted = False
        abort_reason = None
        previous_failure: tuple[CollectStatus, str | None] | None = None
        consecutive_failures = 0

        try:
            for task in unique_tasks:
                task_key = build_task_key(task)
                final_attempt = self._run_task(task, task_key, run_id)
                if final_attempt.snapshot.collect_status in EVIDENCE_STATUSES:
                    final_attempt = self._save_evidence(final_attempt)

                try:
                    self.repository.save(final_attempt.snapshot, final_attempt.results)
                except Exception:
                    persistence_failures += 1

                processed_tasks += 1
                status = final_attempt.snapshot.collect_status
                status_counts[status] += 1

                if final_attempt.session_damaged:
                    self._discard_session()

                failure = _failure_identity(final_attempt.snapshot)
                if failure is None:
                    previous_failure = None
                    consecutive_failures = 0
                elif failure == previous_failure:
                    consecutive_failures += 1
                else:
                    previous_failure = failure
                    consecutive_failures = 1

                if consecutive_failures >= self.failure_limit:
                    aborted = True
                    abort_reason = f"aborted after {self.failure_limit} identical consecutive failures"
                    break
        finally:
            self._discard_session()

        return RunSummary(
            run_id=run_id,
            total_tasks=len(unique_tasks),
            processed_tasks=processed_tasks,
            status_counts=status_counts,
            persistence_failures=persistence_failures,
            aborted=aborted,
            abort_reason=abort_reason,
        )

    def _run_task(self, task: SearchTask, task_key: str, run_id: str) -> _FinalAttempt:
        final_attempt: _FinalAttempt | None = None
        total_attempts = self.max_retries + 1

        for attempt_number in range(1, total_attempts + 1):
            try:
                session = self._ensure_session(task)
                page = session.search(task)
            except (SearchStateTimeout, QueryMismatch, SearchPageError, BrowserSessionError) as exc:
                final_attempt = self._browser_failure(task, task_key, run_id, exc)
                if final_attempt.session_damaged and attempt_number < total_attempts:
                    self._discard_session()
                if attempt_number < total_attempts:
                    continue
                break

            if page.state == "NO_RESULT" or _has_no_result_marker(page.html):
                final_attempt = _FinalAttempt(
                    snapshot=self._snapshot(
                        task,
                        task_key,
                        run_id,
                        status=CollectStatus.NO_RESULT,
                        message=None,
                        final_url=page.final_url,
                        observed_result_count=0,
                        result_end_reached=True,
                    ),
                    results=(),
                    html=page.html,
                )
                break

            observed_count, end_reached = _result_progress(page.html)
            page = replace(
                page,
                observed_result_count=observed_count,
                result_end_reached=end_reached,
            )
            try:
                parsed = self.parser.parse(page)
                validation = self.validator.validate(parsed, self.result_limit)
                matched_results = tuple(
                    self.matcher.match(result).apply_to(result) for result in validation.results
                )
            except Exception as exc:
                final_attempt = self._page_failure(
                    task,
                    task_key,
                    run_id,
                    page,
                    CollectStatus.PARSER_ERROR,
                    exc,
                )
                break

            final_attempt = _FinalAttempt(
                snapshot=self._snapshot(
                    task,
                    task_key,
                    run_id,
                    status=validation.status,
                    message=validation.message,
                    final_url=page.final_url,
                    observed_result_count=validation.observed_result_count,
                    result_end_reached=page.result_end_reached,
                ),
                results=matched_results,
                html=page.html,
            )
            break

        assert final_attempt is not None
        return final_attempt

    def _ensure_session(self, task: SearchTask) -> Any:
        profile = (task.device_type, task.latitude, task.longitude)
        if self._session is not None and self._session_profile != profile:
            self._discard_session()
        if self._session is None:
            self._session = self.browser_factory.create(
                task.device_type,
                task.latitude,
                task.longitude,
            )
            self._session_profile = profile
        return self._session

    def _browser_failure(
        self,
        task: SearchTask,
        task_key: str,
        run_id: str,
        error: Exception,
    ) -> _FinalAttempt:
        status = _browser_failure_status(error)
        html = getattr(error, "html", "") or ""
        observed_count, end_reached = _result_progress(html)
        return _FinalAttempt(
            snapshot=self._snapshot(
                task,
                task_key,
                run_id,
                status=status,
                message=str(error),
                final_url=getattr(error, "last_url", "") or "",
                observed_result_count=observed_count,
                result_end_reached=end_reached,
            ),
            results=(),
            html=html,
            retryable=True,
            session_damaged=isinstance(error, BrowserSessionError),
        )

    def _page_failure(
        self,
        task: SearchTask,
        task_key: str,
        run_id: str,
        page: SearchPage,
        status: CollectStatus,
        error: Exception,
    ) -> _FinalAttempt:
        observed_count, end_reached = _result_progress(page.html)
        return _FinalAttempt(
            snapshot=self._snapshot(
                task,
                task_key,
                run_id,
                status=status,
                message=str(error),
                final_url=page.final_url,
                observed_result_count=observed_count,
                result_end_reached=end_reached,
            ),
            results=(),
            html=page.html,
        )

    def _snapshot(
        self,
        task: SearchTask,
        task_key: str,
        run_id: str,
        *,
        status: CollectStatus,
        message: str | None,
        final_url: str,
        observed_result_count: int,
        result_end_reached: bool,
    ) -> SearchSnapshot:
        return SearchSnapshot(
            run_id=run_id,
            task_key=task_key,
            task=task,
            normalized_query=normalize_query(task.query),
            requested_result_limit=self.result_limit,
            observed_result_count=observed_result_count,
            result_end_reached=result_end_reached,
            collect_status=status,
            collect_msg=_capped(message),
            parser_version=PARSER_VERSION,
            final_url=final_url,
            collected_at=self.clock(),
        )

    def _save_evidence(self, final_attempt: _FinalAttempt) -> _FinalAttempt:
        snapshot = final_attempt.snapshot
        directory = self.artifact_root / snapshot.run_id / snapshot.task_key
        try:
            if self._session is not None:
                self._session.save_evidence(directory, html=final_attempt.html)
            else:
                _write_fallback_evidence(directory, final_attempt.html)
        except Exception as exc:
            try:
                _write_fallback_evidence(directory, final_attempt.html)
            except OSError:
                pass
            evidence_message = f"evidence capture failed: {exc}"
            message = "; ".join(filter(None, (snapshot.collect_msg, evidence_message)))
            return replace(
                final_attempt,
                snapshot=replace(snapshot, collect_msg=_capped(message)),
                session_damaged=(
                    final_attempt.session_damaged or isinstance(exc, BrowserSessionError)
                ),
            )
        return final_attempt

    def _discard_session(self) -> None:
        session = self._session
        self._session = None
        self._session_profile = None
        if session is None:
            return
        close = getattr(session, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                return
            return
        driver = getattr(session, "driver", None)
        quit_driver = getattr(driver, "quit", None)
        if callable(quit_driver):
            try:
                quit_driver()
            except Exception:
                return


def _deduplicate_tasks(tasks: Iterable[SearchTask]) -> tuple[SearchTask, ...]:
    unique: list[SearchTask] = []
    seen: set[str] = set()
    for task in tasks:
        task_key = build_task_key(task)
        if task_key not in seen:
            seen.add(task_key)
            unique.append(task)
    return tuple(unique)


def _browser_failure_status(error: Exception) -> CollectStatus:
    if isinstance(error, SearchStateTimeout):
        return CollectStatus.LOAD_TIMEOUT
    if isinstance(error, QueryMismatch):
        return CollectStatus.QUERY_MISMATCH
    return CollectStatus.SEARCH_ERROR


def _result_progress(html: str) -> tuple[int, bool]:
    soup = BeautifulSoup(html or "", "html.parser")
    observed_count = len(soup.select(RESULT_CARD_SELECTOR))
    visible_text = " ".join(soup.stripped_strings)
    result_end_reached = soup.select_one(RESULT_END_SELECTOR) is not None or any(
        marker in visible_text for marker in RESULT_END_TEXTS
    )
    if not result_end_reached:
        result_end_reached = any(marker in visible_text for marker in NO_RESULT_TEXTS)
    return observed_count, result_end_reached


def _has_no_result_marker(html: str) -> bool:
    visible_text = " ".join(BeautifulSoup(html or "", "html.parser").stripped_strings)
    return any(marker in visible_text for marker in NO_RESULT_TEXTS)


def _failure_identity(snapshot: SearchSnapshot) -> tuple[CollectStatus, str | None] | None:
    if snapshot.collect_status in _NON_FAILURE_STATUSES:
        return None
    return snapshot.collect_status, snapshot.collect_msg


def _capped(message: str | None) -> str | None:
    return message[:1000] if message else None


def _write_fallback_evidence(directory: Path, html: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "page.html").write_text(html, encoding="utf-8")
    (directory / "screenshot.png").write_bytes(_EMPTY_PNG)
