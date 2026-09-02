from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID, uuid4

import pymssql

from .browser import BrowserFactory, BrowserSessionError
from .collector import KeywordDiscoveryCollector, RunSummary
from .config import CollectorConfig, ConfigError
from .matching import OwnStore, OwnStoreMatcher
from .models import CollectStatus, DeviceType, SearchTask
from .parser import DomResultParser
from .repository import RepositoryError, SnapshotRepository
from .task_source import (
    DatabaseTaskSource,
    ExcelTaskSource,
    InputValidationError,
    build_task_key,
)
from .validation import ResultValidator


REPO_ROOT = Path(__file__).resolve().parents[2]


class CliError(ValueError):
    """A safe, user-actionable command-line failure."""


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
    parser.add_argument("--source", choices=("excel", "database"), default="excel")
    parser.add_argument("--device-override", type=_device_type)
    parser.add_argument("--limit", type=_positive_int)
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

        if args.dry_run:
            if args.source == "database":
                raise CliError("database source cannot be validated in dry-run mode without a DB client")
            tasks = _prepare_tasks(_load_tasks(args), args.device_override)
            _require_tasks(tasks)
            run_id = str(uuid_factory())
            stdout.write(f"run_id={run_id} total={len(tasks)} dry_run=true\n")
            return 0

        if args.source == "excel":
            tasks = _prepare_tasks(_load_tasks(args), args.device_override)
            _require_tasks(tasks)
        else:
            _require_input_file(args.input, "SQL query file")
            tasks = None

        collector_config = CollectorConfig.from_env(repo_root)
        if args.limit is not None:
            collector_config = replace(collector_config, result_limit=args.limit)

        connection = _connect_database(collector_config)
        repository_connection = RollbackConnection(connection) if args.rollback_test else connection
        repository = SnapshotRepository(repository_connection)
        if repository.ping() is not True:
            raise CliError("database preflight did not return a successful probe")

        if tasks is None:
            tasks = _prepare_tasks(_load_tasks(args, connection=connection), args.device_override)
            _require_tasks(tasks)

        browser_factory = _make_browser_factory(collector_config)
        preflight_session = browser_factory.create(
            tasks[0].device_type,
            tasks[0].latitude,
            tasks[0].longitude,
        )
        _close_browser_session(preflight_session)

        matcher = OwnStoreMatcher(_own_stores(tasks))
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
        )
        run_id = str(uuid_factory())
        summary = collector.run(tasks, run_id)
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
        return ExcelTaskSource(args.input).load()

    _require_input_file(args.input, "SQL query file")
    if connection is None:
        raise CliError("database source requires a database connection")
    query = args.input.read_text(encoding="utf-8")
    if not query.strip():
        raise CliError("SQL query file must not be empty")
    cursor = connection.cursor()
    try:
        return DatabaseTaskSource(cursor, query).load()
    finally:
        cursor.close()


_load_tasks = load_tasks


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
        raise RepositoryError("database connection failed") from exc


def _make_browser_factory(config: CollectorConfig) -> BrowserFactory:
    return BrowserFactory(
        headless=config.headless,
        timeout_seconds=config.timeout_seconds,
        result_limit=config.result_limit,
    )


def _own_stores(tasks: Iterable[SearchTask]) -> tuple[OwnStore, ...]:
    stores: dict[str, OwnStore] = {}
    for task in tasks:
        stores.setdefault(task.target_store_id, OwnStore(task.target_store_id, task.target_store_name))
    return tuple(stores.values())


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


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("limit must be a positive integer")
    return parsed
