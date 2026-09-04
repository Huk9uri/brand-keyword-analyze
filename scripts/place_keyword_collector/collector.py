from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable
from urllib.parse import quote

from .browser import (
    MOBILE_PLACE_HOME,
    BlockedPageError,
    PlaceLoadTimeout,
    PlacePage,
)
from .change import decide_change
from .models import (
    CollectedKeyword,
    CollectionSummary,
    KeywordCollectStatus,
    KeywordSnapshot,
    PreviousVersion,
    RankPlaceTarget,
    RefreshPolicy,
)
from .parser import KeywordListParseError, PlaceMismatchError
from .rank_source import is_refresh_due


PARSER_VERSION = "v1"
_VALID_STATUSES = frozenset(
    {KeywordCollectStatus.SUCCESS, KeywordCollectStatus.EMPTY}
)
_EMPTY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf"
    b"\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


@dataclass(frozen=True)
class CollectorSummary(CollectionSummary):
    """Run details added without changing the committed summary contract."""

    reused: int = 0
    processed_count: int = 0
    status_counts: Mapping[KeywordCollectStatus, int] = field(default_factory=dict)
    aborted: bool = False
    abort_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status_counts",
            MappingProxyType(dict(self.status_counts)),
        )


@dataclass(frozen=True)
class _FinalAttempt:
    snapshot: KeywordSnapshot
    keywords: tuple[CollectedKeyword, ...]
    html: str


class PlaceKeywordCollector:
    """Coordinate refresh lookup, Place collection, parsing, and persistence."""

    def __init__(
        self,
        browser_factory: Any,
        parser: Any,
        repository: Any,
        *,
        artifact_root: str | Path,
        max_retries: int = 2,
        failure_limit: int = 5,
        parser_version: str = PARSER_VERSION,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or max_retries < 0
        ):
            raise ValueError("max_retries must be a non-negative integer")
        if (
            isinstance(failure_limit, bool)
            or not isinstance(failure_limit, int)
            or failure_limit <= 0
        ):
            raise ValueError("failure_limit must be a positive integer")
        if not parser_version:
            raise ValueError("parser_version must not be empty")

        self.browser_factory = browser_factory
        self.parser = parser
        self.repository = repository
        self.artifact_root = Path(artifact_root)
        self.max_retries = max_retries
        self.failure_limit = failure_limit
        self.parser_version = parser_version
        self.clock = clock
        self._browser: Any | None = None

    def run(
        self,
        targets: Iterable[RankPlaceTarget],
        run_id: str,
        rank_run_id: str,
        policy: RefreshPolicy,
        force_refresh: bool = False,
    ) -> CollectionSummary:
        target_list = tuple(targets)
        now = self.clock()
        refreshes = tuple(
            (
                target,
                previous,
                is_refresh_due(previous, policy, now, force_refresh),
            )
            for target in target_list
            for previous in (self.repository.get_previous(target.place_id),)
        )

        reused = sum(not due for _, _, due in refreshes)
        status_counts: Counter[KeywordCollectStatus] = Counter()
        processed_count = 0
        previous_failure: tuple[KeywordCollectStatus, str | None] | None = None
        consecutive_failures = 0
        aborted = False
        abort_reason = None

        try:
            for target, previous, due in refreshes:
                if not due:
                    continue

                final_attempt = self._collect_target(
                    target,
                    previous,
                    run_id,
                    rank_run_id,
                )
                failure = _failure_identity(final_attempt.snapshot)
                if failure is not None:
                    self._save_evidence(
                        run_id,
                        target.place_id,
                        final_attempt.html,
                    )

                self.repository.save(final_attempt.snapshot, final_attempt.keywords)
                processed_count += 1
                status = final_attempt.snapshot.status
                status_counts[status] += 1

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
                    abort_reason = (
                        f"aborted after {self.failure_limit} identical "
                        "consecutive failures"
                    )
                    break
        finally:
            self._close_browser()

        return CollectorSummary(
            run_id=run_id,
            rank_run_id=rank_run_id,
            target_count=len(target_list),
            success_count=status_counts[KeywordCollectStatus.SUCCESS],
            empty_count=status_counts[KeywordCollectStatus.EMPTY],
            failed_count=sum(
                count
                for status, count in status_counts.items()
                if status not in _VALID_STATUSES
            ),
            reused=reused,
            processed_count=processed_count,
            status_counts=status_counts,
            aborted=aborted,
            abort_reason=abort_reason,
        )

    def _collect_target(
        self,
        target: RankPlaceTarget,
        previous: PreviousVersion | None,
        run_id: str,
        rank_run_id: str,
    ) -> _FinalAttempt:
        total_attempts = self.max_retries + 1
        for attempt_number in range(1, total_attempts + 1):
            browser = self._ensure_browser()
            try:
                page = browser.fetch(target)
            except (BlockedPageError, PlaceLoadTimeout) as exc:
                final_attempt = self._browser_failure(
                    target,
                    previous,
                    run_id,
                    rank_run_id,
                    exc,
                )
                if attempt_number < total_attempts:
                    continue
                return final_attempt

            return self._parse_page(
                target,
                previous,
                run_id,
                rank_run_id,
                page,
            )

        raise AssertionError("collection attempt loop did not produce a result")

    def _parse_page(
        self,
        target: RankPlaceTarget,
        previous: PreviousVersion | None,
        run_id: str,
        rank_run_id: str,
        page: PlacePage,
    ) -> _FinalAttempt:
        try:
            parsed = self.parser.parse(page.html, target.place_id)
        except PlaceMismatchError as exc:
            return self._page_failure(
                target,
                previous,
                run_id,
                rank_run_id,
                page,
                KeywordCollectStatus.PLACE_MISMATCH,
                exc,
            )
        except KeywordListParseError as exc:
            return self._page_failure(
                target,
                previous,
                run_id,
                rank_run_id,
                page,
                KeywordCollectStatus.PARSE_ERROR,
                exc,
            )

        decision = decide_change(previous, parsed)
        snapshot = self._snapshot(
            target,
            run_id,
            rank_run_id,
            source_url=page.final_url,
            status=decision.status,
            content_hash=decision.content_hash,
            is_changed=decision.is_changed,
            effective_snapshot_id=decision.effective_snapshot_id,
            keyword_count=len(parsed.keywords),
            message=None,
        )
        return _FinalAttempt(
            snapshot=snapshot,
            keywords=(parsed.keywords if decision.is_changed else ()),
            html=page.html,
        )

    def _browser_failure(
        self,
        target: RankPlaceTarget,
        previous: PreviousVersion | None,
        run_id: str,
        rank_run_id: str,
        error: BlockedPageError | PlaceLoadTimeout,
    ) -> _FinalAttempt:
        status = (
            KeywordCollectStatus.BLOCKED
            if isinstance(error, BlockedPageError)
            else KeywordCollectStatus.LOAD_TIMEOUT
        )
        source_url = error.last_url or _source_url(target)
        return _FinalAttempt(
            snapshot=self._snapshot(
                target,
                run_id,
                rank_run_id,
                source_url=source_url,
                status=status,
                content_hash=None,
                is_changed=False,
                effective_snapshot_id=(
                    previous.effective_snapshot_id if previous is not None else None
                ),
                keyword_count=0,
                message=str(error),
            ),
            keywords=(),
            html=error.html,
        )

    def _page_failure(
        self,
        target: RankPlaceTarget,
        previous: PreviousVersion | None,
        run_id: str,
        rank_run_id: str,
        page: PlacePage,
        status: KeywordCollectStatus,
        error: Exception,
    ) -> _FinalAttempt:
        return _FinalAttempt(
            snapshot=self._snapshot(
                target,
                run_id,
                rank_run_id,
                source_url=page.final_url or _source_url(target),
                status=status,
                content_hash=None,
                is_changed=False,
                effective_snapshot_id=(
                    previous.effective_snapshot_id if previous is not None else None
                ),
                keyword_count=0,
                message=str(error),
            ),
            keywords=(),
            html=page.html,
        )

    def _snapshot(
        self,
        target: RankPlaceTarget,
        run_id: str,
        rank_run_id: str,
        *,
        source_url: str,
        status: KeywordCollectStatus,
        content_hash: str | None,
        is_changed: bool,
        effective_snapshot_id: int | None,
        keyword_count: int,
        message: str | None,
    ) -> KeywordSnapshot:
        return KeywordSnapshot(
            snapshot_id=0,
            run_id=run_id,
            rank_run_id=rank_run_id,
            target=target,
            source_url=source_url,
            status=status,
            content_hash=content_hash,
            is_changed=is_changed,
            effective_snapshot_id=effective_snapshot_id,
            keyword_count=keyword_count,
            parser_version=self.parser_version,
            collect_msg=_capped(message),
            checked_at=self.clock(),
        )

    def _ensure_browser(self) -> Any:
        if self._browser is None:
            self._browser = self.browser_factory.create()
        return self._browser

    def _save_evidence(self, run_id: str, place_id: str, html: str) -> None:
        directory = self.artifact_root / run_id / place_id
        try:
            if self._browser is not None:
                self._browser.save_evidence(directory, html)
            else:
                _write_fallback_evidence(directory, html)
        except Exception:
            try:
                _write_fallback_evidence(directory, html)
            except OSError:
                pass

    def _close_browser(self) -> None:
        browser = self._browser
        self._browser = None
        if browser is None:
            return
        try:
            browser.close()
        except Exception:
            pass


def _failure_identity(
    snapshot: KeywordSnapshot,
) -> tuple[KeywordCollectStatus, str | None] | None:
    if snapshot.status in _VALID_STATUSES:
        return None
    return snapshot.status, snapshot.collect_msg


def _source_url(target: RankPlaceTarget) -> str:
    place_id = quote(str(target.place_id).strip(), safe="")
    return MOBILE_PLACE_HOME.format(place_id=place_id)


def _capped(message: str | None) -> str | None:
    return message[:1000] if message else None


def _write_fallback_evidence(directory: Path, html: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "page.html").write_text(html, encoding="utf-8")
    (directory / "screenshot.png").write_bytes(_EMPTY_PNG)


__all__ = ["CollectorSummary", "PlaceKeywordCollector"]
