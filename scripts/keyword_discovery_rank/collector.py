from __future__ import annotations

import json
import time
import math
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
    SearchPageError,
    SecurityCheckRequired,
    SearchStateTimeout,
    _result_progress as browser_result_progress,
)
from .models import CollectStatus, ParsedResult, SearchPage, SearchSnapshot, SearchTask
from .parser import PARSER_VERSION
from .repository import FatalRepositoryError, TaskPersistenceError
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
    retry_history: tuple["RetryRecord", ...] = ()


@dataclass(frozen=True)
class RetryRecord:
    attempt: int
    status: CollectStatus
    message: str


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
        review_export: bool = False,
        redact: Callable[[str], str] = lambda value: value,
        retry_logger: Callable[[str], None] = lambda value: None,
        request_interval_seconds: float = 0,
        retry_backoff_seconds: float = 0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if (
            isinstance(result_limit, bool)
            or not isinstance(result_limit, int)
            or not 1 <= result_limit <= 20
        ):
            raise ValueError("result_limit must be between 1 and 20")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if isinstance(failure_limit, bool) or not isinstance(failure_limit, int) or failure_limit <= 0:
            raise ValueError("failure_limit must be a positive integer")

        self.browser_factory = browser_factory
        for delay in (request_interval_seconds, retry_backoff_seconds):
            if not math.isfinite(delay) or delay < 0:
                raise ValueError('request delays must be finite and non-negative')
        self.request_interval_seconds = request_interval_seconds
        self.retry_backoff_seconds = retry_backoff_seconds
        self._sleep = sleep
        self.parser = parser
        self.validator = validator
        self.matcher = matcher
        self.repository = repository
        self.artifact_root = Path(artifact_root)
        self.result_limit = result_limit
        self.max_retries = max_retries
        self.failure_limit = failure_limit
        self.clock = clock
        self.review_export = review_export
        self.redact = redact
        self.retry_logger = retry_logger
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
                failure = _failure_identity(final_attempt.snapshot)
                if self.review_export or final_attempt.snapshot.collect_status in EVIDENCE_STATUSES:
                    final_attempt = self._save_evidence(final_attempt)
                if self.review_export:
                    self._save_structured_export(final_attempt)

                try:
                    self.repository.save(final_attempt.snapshot, final_attempt.results)
                except TaskPersistenceError:
                    persistence_failures += 1
                except FatalRepositoryError:
                    raise
                except Exception as exc:
                    raise FatalRepositoryError("unclassified repository failure") from exc

                processed_tasks += 1
                status = final_attempt.snapshot.collect_status
                status_counts[status] += 1

                if (final_attempt.snapshot.collect_msg or '').startswith('SECURITY_CHECK_REQUIRED'):
                    aborted = True
                    abort_reason = 'SECURITY_CHECK_REQUIRED'
                    break

                if final_attempt.session_damaged:
                    self._discard_session()

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
        retry_history: list[RetryRecord] = []

        for attempt_number in range(1, total_attempts + 1):
            delay = self.request_interval_seconds
            if attempt_number > 1:
                delay = max(delay, self.retry_backoff_seconds * 2 ** (attempt_number - 2))
            if delay:
                self._sleep(delay)
            try:
                session = self._ensure_session(task)
                page = session.search(task)
            except (SearchStateTimeout, QueryMismatch, SearchPageError, BrowserSessionError) as exc:
                final_attempt = self._browser_failure(task, task_key, run_id, exc)
                if final_attempt.session_damaged and attempt_number < total_attempts:
                    self._discard_session()
                if final_attempt.retryable and attempt_number < total_attempts:
                    record = RetryRecord(
                        attempt=attempt_number,
                        status=final_attempt.snapshot.collect_status,
                        message=final_attempt.snapshot.collect_msg or "",
                    )
                    retry_history.append(record)
                    self.retry_logger(
                        "retry "
                        f"task_key={task_key} attempt={attempt_number}/{total_attempts} "
                        f"status={record.status.value} message={record.message}"
                    )
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
                result_end_reached=page.result_end_reached or end_reached,
            )
            try:
                parsed = self.parser.parse(page)
                validation = self.validator.validate(parsed, self.result_limit)
                matched_results = tuple(
                    _mark_target_store(
                        self.matcher.match(result).apply_to(result),
                        task.target_store_id,
                    )
                    for result in validation.results
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
        return replace(final_attempt, retry_history=tuple(retry_history))

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
                message=self.redact(str(error)),
                final_url=getattr(error, "last_url", "") or "",
                observed_result_count=observed_count,
                result_end_reached=end_reached,
            ),
            results=(),
            html=html,
            retryable=not isinstance(error, SecurityCheckRequired),
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
                message=self.redact(str(error)),
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
            if self.review_export:
                raise BrowserSessionError(
                    "review evidence capture failed",
                    last_url=snapshot.final_url,
                    html=final_attempt.html,
                ) from exc
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

    def _save_structured_export(self, final_attempt: _FinalAttempt) -> Path:
        snapshot = final_attempt.snapshot
        directory = self.artifact_root / snapshot.run_id / snapshot.task_key
        directory.mkdir(parents=True, exist_ok=True)
        export_path = directory / "snapshot-results.json"
        payload = {
            "format_version": 1,
            "snapshot": _snapshot_export(snapshot),
            "results": [_result_export(result) for result in final_attempt.results],
            "retry_history": [
                {
                    "attempt": record.attempt,
                    "status": record.status.value,
                    "message": record.message,
                }
                for record in final_attempt.retry_history
            ],
        }
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        export_path.write_text(self.redact(rendered) + "\n", encoding="utf-8")
        return export_path

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
            except OSError:
                # 프로필 삭제 재시도가 소진되면 다음 프로필을 만들지 않는다.
                raise
            except Exception:
                pass
            else:
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


def _mark_target_store(result: ParsedResult, target_store_id: str) -> ParsedResult:
    return replace(
        result,
        is_target_store=(
            result.is_own_store
            and result.matched_store_id == target_store_id
        ),
    )


def _result_progress(html: str) -> tuple[int, bool]:
    return browser_result_progress(html)


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


def _snapshot_export(snapshot: SearchSnapshot) -> dict[str, object]:
    task = snapshot.task
    return {
        "run_id": snapshot.run_id,
        "task_key": snapshot.task_key,
        "query": task.query,
        "normalized_query": snapshot.normalized_query,
        "target_store_id": task.target_store_id,
        "target_store_name": task.target_store_name,
        "location_name": task.location_name,
        "latitude": task.latitude,
        "longitude": task.longitude,
        "device_type": task.device_type.value,
        "source_type": task.source_type.value,
        "source_id": task.source_id,
        "requested_result_limit": snapshot.requested_result_limit,
        "observed_result_count": snapshot.observed_result_count,
        "result_end_reached": snapshot.result_end_reached,
        "collect_status": snapshot.collect_status.value,
        "collect_msg": snapshot.collect_msg,
        "parser_version": snapshot.parser_version,
        "final_url": snapshot.final_url,
        "collected_at": snapshot.collected_at.isoformat(),
    }


def _result_export(result: ParsedResult) -> dict[str, object]:
    return {
        "raw_position": result.raw_position,
        "organic_rank": result.organic_rank,
        "place_id": result.place_id,
        "place_name": result.place_name,
        "category": result.category,
        "is_ad": result.is_ad,
        "detail_url": result.detail_url,
        "distance_text": result.distance_text,
        "is_own_store": result.is_own_store,
        "is_target_store": result.is_target_store,
        "matched_store_id": result.matched_store_id,
        "match_method": result.match_method.value,
    }
