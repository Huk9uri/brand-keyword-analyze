from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID, uuid4

import pymssql

from .browser import BrowserFactory, PlaceBrowserError
from .collector import CollectorSummary, PlaceKeywordCollector
from .config import ConfigError, PlaceKeywordConfig
from .models import PreviousVersion, RankPlaceTarget, RefreshPolicy
from .parser import KeywordListParser
from .rank_source import RankResultSource, is_refresh_due
from .repository import (
    FatalRepositoryError,
    PlaceKeywordRepository,
    RepositoryError,
    TaskPersistenceError,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


class CliError(ValueError):
    """A safe, user-actionable command-line failure."""


class RollbackConnection:
    """Turn every repository commit into a rollback for live-path testing."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def commit(self) -> None:
        self._connection.rollback()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class _PreparedRepository:
    """Reuse the previous-version reads made while calculating due targets."""

    def __init__(
        self,
        repository: Any,
        previous_by_place: dict[str, PreviousVersion | None],
    ) -> None:
        self._repository = repository
        self._previous_by_place = previous_by_place

    def get_previous(self, place_id: str) -> PreviousVersion | None:
        return self._previous_by_place[place_id]

    def save(self, snapshot: Any, keywords: Sequence[Any]) -> int:
        return self._repository.save(snapshot, keywords)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="네이버 플레이스 대표키워드 수집")
    parser.add_argument("--rank-run-id", required=True)
    parser.add_argument("--top-n", type=_top_n, default=10)
    parser.add_argument(
        "--refresh-policy",
        choices=("monthly", "weekly"),
        default="monthly",
    )
    parser.add_argument(
        "--include-place-id",
        action="append",
        default=[],
        type=_place_id,
    )
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rollback-test", action="store_true")
    return parser.parse_args(argv)


def select_included_targets(
    targets: Sequence[RankPlaceTarget],
    requested_place_ids: Sequence[str],
) -> tuple[RankPlaceTarget, ...]:
    requested = tuple(str(place_id) for place_id in requested_place_ids)
    if not requested:
        return tuple(targets)

    available = {str(target.place_id) for target in targets}
    for place_id in requested:
        if place_id not in available:
            raise CliError(
                f"requested Place ID is absent from the rank run: {place_id}"
            )
    requested_set = set(requested)
    return tuple(
        target for target in targets if str(target.place_id) in requested_set
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    repo_root: str | Path = REPO_ROOT,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    uuid_factory: Callable[[], UUID] = uuid4,
    clock: Callable[[], datetime] = datetime.now,
    config_loader: Callable[[Path], PlaceKeywordConfig] | None = None,
    connect_database: Callable[[PlaceKeywordConfig], Any] | None = None,
    rank_source_factory: Callable[[Any], Any] | None = None,
    repository_factory: Callable[[Any], Any] | None = None,
    browser_factory_builder: Callable[[PlaceKeywordConfig], Any] | None = None,
    collector_factory: Callable[..., Any] | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    connection: Any | None = None
    repository: Any | None = None

    try:
        args = parse_args(argv)
        repo_root = Path(repo_root)
        load_config = config_loader or PlaceKeywordConfig.from_env
        config = load_config(repo_root)
        connect = connect_database or _connect_database
        connection = connect(config)
        repository_connection = (
            RollbackConnection(connection) if args.rollback_test else connection
        )
        build_repository = repository_factory or PlaceKeywordRepository
        repository = build_repository(repository_connection)

        repository.preflight(expected_database="naverDB")
        targets = _load_rank_targets(
            repository_connection,
            args.rank_run_id,
            args.top_n,
            rank_source_factory or RankResultSource,
        )
        targets = _deduplicate_targets(targets)
        targets = select_included_targets(targets, args.include_place_id)

        policy = RefreshPolicy(args.refresh_policy.upper())
        now = clock()
        prepared_repository, due_count = _prepare_repository(
            repository,
            targets,
            policy,
            now,
            args.force_refresh,
        )
        run_id = str(uuid_factory())

        if args.dry_run:
            stdout.write(
                f"run_id={run_id} rank_run_id={args.rank_run_id} "
                f"targets={len(targets)} due={due_count} dry_run=true\n"
            )
            return 0

        build_browser_factory = browser_factory_builder or _make_browser_factory
        browser_factory = build_browser_factory(config)
        build_collector = collector_factory or PlaceKeywordCollector
        collector = build_collector(
            browser_factory,
            KeywordListParser(),
            prepared_repository,
            artifact_root=config.artifact_root,
            max_retries=config.max_retries,
            failure_limit=config.failure_limit,
            clock=lambda: now,
        )
        summary = collector.run(
            targets,
            run_id,
            args.rank_run_id,
            policy,
            force_refresh=args.force_refresh,
        )
        _print_summary(summary, due_count, stdout)
        return 1 if summary.aborted else 0
    except TaskPersistenceError:
        stderr.write("error=task persistence failed\n")
        return 1
    except (CliError, ConfigError) as exc:
        stderr.write(f"error={_single_line(exc)}\n")
        return 2
    except RepositoryError:
        stderr.write("error=database preflight or persistence failed\n")
        return 2
    except PlaceBrowserError:
        stderr.write("error=Place browser failed\n")
        return 2
    except OSError:
        stderr.write("error=local configuration or artifact operation failed\n")
        return 2
    finally:
        if repository is not None:
            try:
                repository.close()
            except Exception:
                pass
        elif connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _load_rank_targets(
    connection: Any,
    rank_run_id: str,
    top_n: int,
    rank_source_factory: Callable[[Any], Any],
) -> tuple[RankPlaceTarget, ...]:
    cursor: Any | None = None
    try:
        cursor = connection.cursor()
        return tuple(rank_source_factory(cursor).load(rank_run_id, top_n))
    except RepositoryError:
        raise
    except Exception:
        raise FatalRepositoryError("failed to load rank-run targets") from None
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass


def _deduplicate_targets(
    targets: Sequence[RankPlaceTarget],
) -> tuple[RankPlaceTarget, ...]:
    unique: list[RankPlaceTarget] = []
    seen: set[str] = set()
    for target in targets:
        place_id = str(target.place_id)
        if place_id in seen:
            continue
        seen.add(place_id)
        unique.append(target)
    return tuple(unique)


def _prepare_repository(
    repository: Any,
    targets: Sequence[RankPlaceTarget],
    policy: RefreshPolicy,
    now: datetime,
    force_refresh: bool,
) -> tuple[_PreparedRepository, int]:
    previous_by_place = {
        str(target.place_id): repository.get_previous(str(target.place_id))
        for target in targets
    }
    due_count = sum(
        is_refresh_due(
            previous_by_place[str(target.place_id)],
            policy,
            now,
            force_refresh,
        )
        for target in targets
    )
    return _PreparedRepository(repository, previous_by_place), due_count


def _connect_database(config: PlaceKeywordConfig) -> Any:
    try:
        return pymssql.connect(
            server=config.db_server,
            port=str(config.db_port),
            database=config.db_database,
            user=config.db_user,
            password=config.db_password,
            autocommit=False,
            use_datetime2=True,
        )
    except Exception:
        raise FatalRepositoryError("database connection failed") from None


def _make_browser_factory(config: PlaceKeywordConfig) -> BrowserFactory:
    return BrowserFactory(
        headless=config.headless,
        timeout_seconds=config.timeout_seconds,
    )


def _print_summary(
    summary: CollectorSummary,
    due_count: int,
    stdout: TextIO,
) -> None:
    counts = " ".join(
        f"{status.value}={count}"
        for status, count in sorted(
            summary.status_counts.items(),
            key=lambda item: item[0].value,
        )
    )
    fields = [
        f"run_id={summary.run_id}",
        f"rank_run_id={summary.rank_run_id}",
        f"targets={summary.target_count}",
        f"due={due_count}",
        f"processed={summary.processed_count}",
        f"reused={summary.reused}",
    ]
    if counts:
        fields.append(counts)
    fields.extend(
        (
            f"failed={summary.failed_count}",
            f"aborted={str(summary.aborted).lower()}",
        )
    )
    stdout.write(" ".join(fields) + "\n")


def _single_line(exc: Exception) -> str:
    return str(exc).replace("\r", " ").replace("\n", "; ")


def _top_n(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "top-n must be an integer between 1 and 20"
        ) from exc
    if not 1 <= parsed <= 20:
        raise argparse.ArgumentTypeError("top-n must be between 1 and 20")
    return parsed


def _place_id(value: str) -> str:
    parsed = value.strip()
    if not parsed:
        raise argparse.ArgumentTypeError("include Place ID must not be empty")
    return parsed


__all__ = [
    "CliError",
    "RollbackConnection",
    "main",
    "parse_args",
    "select_included_targets",
]
