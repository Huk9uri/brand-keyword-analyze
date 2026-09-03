from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID, uuid4

import pymssql

from .browser import BrowserFactory, BrowserSessionError
from .collector import KeywordDiscoveryCollector, RunSummary
from .config import CollectorConfig, ConfigError
from .matching import OwnStore, OwnStoreMatcher
from .models import CollectStatus, DeviceType, SearchSnapshot, SearchTask
from .parser import DomResultParser
from .place_location import PlaceLocationError, PlaceLocationResolver, PlacePageClient
from .repository import (
    FatalRepositoryError,
    PlaceLocationRepository,
    RepositoryError,
    SnapshotRepository,
    TaskPersistenceError,
)
from .task_source import (
    DatabaseTaskSource,
    ExcelTaskSource,
    InputValidationError,
    build_task_key,
    normalize_query,
)
from .validation import ResultValidator


REPO_ROOT = Path(__file__).resolve().parents[2]


class CliError(ValueError):
    """A safe, user-actionable command-line failure."""


@dataclass(frozen=True)
class LoadedInput:
    tasks: tuple[SearchTask, ...]
    own_stores: tuple[OwnStore, ...]
    manual_place_id_mappings: Mapping[str, str]


class RollbackConnection:
    """Connection adapter that turns each repository commit into a rollback."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def commit(self) -> None:
        self._connection.rollback()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="네이버 키워드 발견 순위 수집")
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Excel input file, or an explicit SQL query file for --source database",
    )
    parser.add_argument(
        "--source",
        choices=("excel", "database"),
        default="excel",
        help="input adapter (database is reserved and disabled in this release)",
    )
    parser.add_argument("--device-override", type=_device_type)
    parser.add_argument("--limit", type=_result_limit)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rollback-test", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    repo_root: str | Path = REPO_ROOT,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    uuid_factory: Callable[[], UUID] = uuid4,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    repository: Any | None = None
    connection: Any | None = None

    try:
        args = parse_args(argv)
        repo_root = Path(repo_root)

        if args.source == "database":
            raise CliError("database source is disabled in this release; use --source excel")

        loaded_input = _load_input(args)
        tasks = _prepare_tasks(loaded_input.tasks, args.device_override)
        _require_tasks(tasks)

        if args.dry_run:
            run_id = str(uuid_factory())
            stdout.write(f"run_id={run_id} total={len(tasks)} dry_run=true\n")
            return 0

        collector_config = CollectorConfig.from_env(repo_root)
        if args.limit is not None:
            collector_config = replace(collector_config, result_limit=args.limit)

        connection = _connect_database(collector_config)
        repository_connection = RollbackConnection(connection) if args.rollback_test else connection
        repository = SnapshotRepository(repository_connection)
        repository.preflight(expected_database="naverDB")

        browser_factory = _make_browser_factory(collector_config)
        run_id = str(uuid_factory())
        stdout.write(f"run_id={run_id}\n")
        stdout.flush()

        location_failures = 0
        location_persistence_failures = 0
        if any(task.latitude is None for task in tasks):
            location_repository = PlaceLocationRepository(repository_connection)
            location_repository.preflight(expected_database="naverDB")
            resolver = PlaceLocationResolver(location_repository, PlacePageClient())
            tasks, location_failures, location_persistence_failures = _resolve_task_locations(
                tasks,
                loaded_input.own_stores,
                resolver,
                repository,
                run_id,
                collector_config.result_limit,
            )

        if tasks:
            assert tasks[0].latitude is not None and tasks[0].longitude is not None
            preflight_session = browser_factory.create(
                tasks[0].device_type,
                tasks[0].latitude,
                tasks[0].longitude,
            )
            _close_browser_session(preflight_session)

        matcher = OwnStoreMatcher(
            loaded_input.own_stores,
            manual_place_id_mappings=loaded_input.manual_place_id_mappings,
        )
        redact = _make_redactor((collector_config.db_password,))
        collector = KeywordDiscoveryCollector(
            browser_factory,
            DomResultParser(),
            ResultValidator(),
            matcher,
            repository,
            artifact_root=collector_config.artifact_root,
            result_limit=collector_config.result_limit,
            max_retries=collector_config.max_retries,
            failure_limit=collector_config.failure_limit,
            review_export=args.rollback_test,
            redact=redact,
            retry_logger=_make_retry_logger(stderr),
        )
        if tasks:
            summary = collector.run(tasks, run_id)
        else:
            summary = RunSummary(run_id, 0, 0, {})
        summary = _merge_location_failures(
            summary,
            location_failures,
            location_persistence_failures,
        )
        _print_summary(summary, stdout)
        return 1 if summary.aborted or summary.persistence_failures else 0
    except (CliError, ConfigError, InputValidationError, RepositoryError, BrowserSessionError, OSError) as exc:
        stderr.write(f"error={_safe_error(exc)}\n")
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


def load_tasks(args: argparse.Namespace, *, connection: Any | None = None) -> list[SearchTask]:
    if args.source == "excel":
        _require_input_file(args.input, "Excel input file")
        try:
            return ExcelTaskSource(args.input).load()
        except InputValidationError:
            raise
        except Exception as exc:
            raise CliError("Excel input could not be loaded") from exc

    _require_input_file(args.input, "SQL query file")
    if connection is None:
        raise CliError("database source requires a database connection")
    query = args.input.read_text(encoding="utf-8")
    if not query.strip():
        raise CliError("SQL query file must not be empty")
    try:
        cursor = connection.cursor()
        try:
            return DatabaseTaskSource(cursor, query).load()
        finally:
            cursor.close()
    except InputValidationError:
        raise
    except Exception as exc:
        raise RepositoryError("database task query failed") from exc


_load_tasks = load_tasks


def load_input(args: argparse.Namespace) -> LoadedInput:
    if args.source != "excel":
        raise CliError("database source is disabled in this release; use --source excel")
    _require_input_file(args.input, "Excel input file")
    try:
        loaded = ExcelTaskSource(args.input).load_bundle()
    except InputValidationError:
        raise
    except Exception as exc:
        raise CliError("Excel input could not be loaded") from exc
    return LoadedInput(loaded.tasks, loaded.own_stores, loaded.manual_place_id_mappings)


_load_input = load_input


def _prepare_tasks(
    tasks: Iterable[SearchTask],
    device_override: DeviceType | None,
) -> list[SearchTask]:
    unique: list[SearchTask] = []
    seen: set[str] = set()
    for task in tasks:
        prepared = replace(task, device_type=device_override) if device_override is not None else task
        task_key = build_task_key(prepared)
        if task_key not in seen:
            seen.add(task_key)
            unique.append(prepared)
    return unique


def _require_tasks(tasks: Sequence[SearchTask]) -> None:
    if not tasks:
        raise CliError("input did not produce any search tasks")


def _resolve_task_locations(
    tasks: Iterable[SearchTask],
    own_stores: Iterable[OwnStore],
    resolver: Any,
    repository: Any,
    run_id: str,
    result_limit: int,
) -> tuple[list[SearchTask], int, int]:
    place_ids = {store.store_id: store.place_id for store in own_stores}
    ready: list[SearchTask] = []
    failures = 0
    persistence_failures = 0
    for task in tasks:
        if task.latitude is not None and task.longitude is not None:
            ready.append(task)
            continue
        place_id = place_ids.get(task.target_store_id)
        try:
            if not place_id:
                raise PlaceLocationError("target store has no Naver Place ID")
            location = resolver.resolve(place_id)
            ready.append(
                replace(task, latitude=location.latitude, longitude=location.longitude)
            )
        except PlaceLocationError as exc:
            failures += 1
            snapshot = SearchSnapshot(
                run_id=run_id,
                task_key=build_task_key(task),
                task=task,
                normalized_query=normalize_query(task.query),
                requested_result_limit=result_limit,
                observed_result_count=0,
                result_end_reached=False,
                collect_status=CollectStatus.LOCATION_RESOLVE_ERROR,
                collect_msg=str(exc)[:1000],
                parser_version="place-location-v1",
                final_url=f"https://m.place.naver.com/restaurant/{place_id or ''}/home",
                collected_at=datetime.now(),
            )
            try:
                repository.save(snapshot, ())
            except TaskPersistenceError:
                persistence_failures += 1
    return ready, failures, persistence_failures


def _merge_location_failures(
    summary: RunSummary,
    location_failures: int,
    persistence_failures: int,
) -> RunSummary:
    counts = Counter(summary.status_counts)
    if location_failures:
        counts[CollectStatus.LOCATION_RESOLVE_ERROR] += location_failures
    return RunSummary(
        run_id=summary.run_id,
        total_tasks=summary.total_tasks + location_failures,
        processed_tasks=summary.processed_tasks + location_failures,
        status_counts=counts,
        persistence_failures=summary.persistence_failures + persistence_failures,
        aborted=summary.aborted,
        abort_reason=summary.abort_reason,
    )


def _require_input_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise CliError(f"{label} does not exist")


def _connect_database(config: CollectorConfig) -> Any:
    try:
        return pymssql.connect(
            server=config.db_server,
            port=str(config.db_port),
            database=config.db_database,
            user=config.db_user,
            password=config.db_password,
            encryption="require" if config.db_encrypt else None,
            autocommit=False,
            use_datetime2=True,
        )
    except Exception as exc:
        raise FatalRepositoryError("database connection failed") from exc


def _make_browser_factory(config: CollectorConfig) -> BrowserFactory:
    return BrowserFactory(
        headless=config.headless,
        timeout_seconds=config.timeout_seconds,
        result_limit=config.result_limit,
    )


def _make_redactor(secret_values: Iterable[str]) -> Callable[[str], str]:
    secrets = tuple(sorted({value for value in secret_values if value}, key=len, reverse=True))

    def redact(value: str) -> str:
        rendered = value
        for secret in secrets:
            rendered = rendered.replace(secret, "[REDACTED]")
        return rendered

    return redact


def _make_retry_logger(stderr: TextIO) -> Callable[[str], None]:
    def log(message: str) -> None:
        stderr.write(message + "\n")
        stderr.flush()

    return log


def _close_browser_session(session: Any) -> None:
    close = getattr(session, "close", None)
    if callable(close):
        close()
        return
    driver = getattr(session, "driver", None)
    quit_driver = getattr(driver, "quit", None)
    if callable(quit_driver):
        quit_driver()


def _print_summary(summary: RunSummary, stdout: TextIO) -> None:
    counts = " ".join(
        f"{status.value}={count}"
        for status, count in sorted(summary.status_counts.items(), key=lambda item: item[0].value)
    )
    fields = [
        f"run_id={summary.run_id}",
        f"total={summary.total_tasks}",
        f"processed={summary.processed_tasks}",
    ]
    if counts:
        fields.append(counts)
    fields.extend(
        (
            f"persistence_failures={summary.persistence_failures}",
            f"aborted={str(summary.aborted).lower()}",
        )
    )
    stdout.write(" ".join(fields) + "\n")


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, (CliError, ConfigError, InputValidationError)):
        return str(exc).replace("\r", " ").replace("\n", "; ")
    if isinstance(exc, RepositoryError):
        return "database preflight or persistence failed"
    if isinstance(exc, BrowserSessionError):
        return "Chrome preflight failed"
    return "local input or artifact operation failed"


def _device_type(value: str) -> DeviceType:
    try:
        return DeviceType(value.upper())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("device override must be MOBILE or PC") from exc


def _result_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be an integer between 1 and 20") from exc
    if not 1 <= parsed <= 20:
        raise argparse.ArgumentTypeError("limit must be between 1 and 20")
    return parsed
