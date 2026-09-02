from __future__ import annotations

import subprocess
import os
from io import StringIO
from pathlib import Path
from uuid import UUID

import pytest
from openpyxl import Workbook

from scripts.keyword_discovery_rank import cli
from scripts.keyword_discovery_rank.collector import RunSummary
from scripts.keyword_discovery_rank.config import CollectorConfig
from scripts.keyword_discovery_rank.models import CollectStatus, DeviceType, SearchTask, SourceType
from scripts.keyword_discovery_rank.repository import RepositoryError


HEADERS = ["검색어", "기준매장ID", "기준매장명", "조회위치명", "위도", "경도", "기기", "소스ID"]
RUN_ID = UUID("11111111-1111-1111-1111-111111111111")


def write_input(path: Path, rows: list[list[object]]) -> Path:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "검색작업"
    worksheet.append(HEADERS)
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    workbook.close()
    return path


def sample_task() -> SearchTask:
    return SearchTask(
        task_id="row-2",
        query="선릉역 국밥",
        target_store_id="S1",
        target_store_name="육수당 선릉점",
        location_name="선릉점",
        latitude=37.5048,
        longitude=127.0489,
        source_type=SourceType.EXCEL,
        source_id="2",
        device_type=DeviceType.MOBILE,
    )


def config(repo_root: Path) -> CollectorConfig:
    return CollectorConfig(
        db_server="db.internal",
        db_port=1433,
        db_database="naverDB",
        db_user="collector-writer",
        db_password="top-secret-password",
        db_encrypt=True,
        db_trust_server_certificate=False,
        headless=True,
        timeout_seconds=30,
        artifact_root=repo_root / "artifacts" / "keyword_discovery_rank",
    )


def test_parse_args_accepts_task7_interface_and_requires_positive_limit(tmp_path: Path):
    args = cli.parse_args(
        [
            "--input",
            str(tmp_path / "queries.xlsx"),
            "--source",
            "excel",
            "--device-override",
            "PC",
            "--limit",
            "7",
            "--dry-run",
            "--rollback-test",
        ]
    )

    assert args.input == tmp_path / "queries.xlsx"
    assert args.source == "excel"
    assert args.device_override is DeviceType.PC
    assert args.limit == 7
    assert args.dry_run is True
    assert args.rollback_test is True

    with pytest.raises(SystemExit):
        cli.parse_args(["--input", str(tmp_path / "queries.xlsx"), "--limit", "0"])


def test_excel_dry_run_validates_and_deduplicates_without_config_browser_or_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    input_path = write_input(
        tmp_path / "queries.xlsx",
        [
            [" 선릉역  국밥 ", "S1", "육수당 선릉점", "선릉점", 37.5048, 127.0489, None, "first"],
            ["선릉역 국밥", "S1", "다른 표시명", "다른 위치", 37.5048, 127.0489, "MOBILE", "second"],
        ],
    )
    monkeypatch.setattr(
        cli.CollectorConfig,
        "from_env",
        classmethod(lambda cls, repo_root: (_ for _ in ()).throw(AssertionError("config constructed"))),
    )
    monkeypatch.setattr(
        cli,
        "_connect_database",
        lambda collector_config: (_ for _ in ()).throw(AssertionError("database constructed")),
    )
    monkeypatch.setattr(
        cli,
        "_make_browser_factory",
        lambda collector_config: (_ for _ in ()).throw(AssertionError("browser constructed")),
    )
    output = StringIO()
    uuid_calls = []

    exit_code = cli.main(
        ["--input", str(input_path), "--dry-run"],
        repo_root=tmp_path,
        stdout=output,
        uuid_factory=lambda: uuid_calls.append(True) or RUN_ID,
    )

    assert exit_code == 0
    assert output.getvalue() == f"run_id={RUN_ID} total=1 dry_run=true\n"
    assert uuid_calls == [True]


def test_database_dry_run_is_rejected_without_constructing_database_or_browser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    query_file = tmp_path / "candidates.sql"
    query_file.write_text("SELECT candidate_keyword FROM candidates", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "_connect_database",
        lambda collector_config: (_ for _ in ()).throw(AssertionError("database constructed")),
    )
    monkeypatch.setattr(
        cli,
        "_make_browser_factory",
        lambda collector_config: (_ for _ in ()).throw(AssertionError("browser constructed")),
    )
    errors = StringIO()

    exit_code = cli.main(
        ["--input", str(query_file), "--source", "database", "--dry-run"],
        repo_root=tmp_path,
        stderr=errors,
    )

    assert exit_code == 2
    assert "database source cannot be validated in dry-run mode" in errors.getvalue()


def test_live_mode_runs_input_db_and_chrome_preflight_before_collection_and_closes_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    events = []
    source_task = sample_task()
    fake_config = config(tmp_path)

    monkeypatch.setattr(
        cli,
        "_load_tasks",
        lambda args, connection=None: events.append("input") or [source_task],
    )
    monkeypatch.setattr(
        cli.CollectorConfig,
        "from_env",
        classmethod(lambda cls, repo_root: events.append("config") or fake_config),
    )

    class FakeConnection:
        def close(self):
            events.append("connection-close")

    connection = FakeConnection()
    monkeypatch.setattr(
        cli,
        "_connect_database",
        lambda collector_config: events.append("db-connect") or connection,
    )

    class FakeRepository:
        def __init__(self, received_connection):
            assert received_connection is connection
            events.append("repository")

        def ping(self):
            events.append("db-ping")
            return True

        def close(self):
            connection.close()

    monkeypatch.setattr(cli, "SnapshotRepository", FakeRepository)

    class FakeDriver:
        def quit(self):
            events.append("preflight-browser-close")

    class PreflightSession:
        driver = FakeDriver()

    class FakeBrowserFactory:
        def create(self, device_type, latitude, longitude):
            assert (device_type, latitude, longitude) == (DeviceType.PC, 37.5048, 127.0489)
            events.append("chrome-preflight")
            return PreflightSession()

    browser_factory = FakeBrowserFactory()

    def make_browser_factory(received_config):
        assert received_config.result_limit == 7
        events.append("browser-factory")
        return browser_factory

    monkeypatch.setattr(cli, "_make_browser_factory", make_browser_factory)

    class FakeCollector:
        def __init__(
            self,
            received_browser_factory,
            parser,
            validator,
            matcher,
            repository,
            **options,
        ):
            assert received_browser_factory is browser_factory
            assert options["result_limit"] == 7
            events.append("collector-construct")

        def run(self, tasks, run_id):
            tasks = list(tasks)
            assert tasks[0].device_type is DeviceType.PC
            assert run_id == str(RUN_ID)
            events.append("collector-run")
            return RunSummary(
                run_id,
                total_tasks=1,
                processed_tasks=1,
                status_counts={CollectStatus.SUCCESS: 1},
            )

    monkeypatch.setattr(cli, "KeywordDiscoveryCollector", FakeCollector)
    output = StringIO()
    uuid_calls = []

    exit_code = cli.main(
        [
            "--input",
            str(tmp_path / "queries.xlsx"),
            "--device-override",
            "PC",
            "--limit",
            "7",
        ],
        repo_root=tmp_path,
        stdout=output,
        uuid_factory=lambda: uuid_calls.append(True) or RUN_ID,
    )

    assert exit_code == 0
    assert events == [
        "input",
        "config",
        "db-connect",
        "repository",
        "db-ping",
        "browser-factory",
        "chrome-preflight",
        "preflight-browser-close",
        "collector-construct",
        "collector-run",
        "connection-close",
    ]
    assert uuid_calls == [True]
    assert output.getvalue() == (
        f"run_id={RUN_ID} total=1 processed=1 SUCCESS=1 persistence_failures=0 aborted=false\n"
    )
    assert fake_config.db_password not in output.getvalue()


class FakeDatabaseCursor:
    description = None

    def __init__(self):
        self.executed = []
        self.closed = False

    def execute(self, query):
        self.executed.append(query)

    def fetchall(self):
        return [
            {
                "candidate_keyword": "선릉역 국밥",
                "store_code": "S1",
                "store_display_name": "육수당 선릉점",
                "search_location": "선릉점",
                "search_latitude": 37.5048,
                "search_longitude": 127.0489,
                "device_code": "MOBILE",
                "candidate_id": 42,
            }
        ]

    def close(self):
        self.closed = True


class FakeDatabaseConnection:
    def __init__(self):
        self.created_cursor = FakeDatabaseCursor()
        self.events = []

    def cursor(self):
        self.events.append("cursor")
        return self.created_cursor

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")


def test_database_source_reads_explicit_query_file_and_closes_source_cursor(tmp_path: Path):
    query_file = tmp_path / "candidates.sql"
    query_file.write_text("SELECT *\nFROM dbo.candidates;\n", encoding="utf-8")
    args = cli.parse_args(["--input", str(query_file), "--source", "database"])
    connection = FakeDatabaseConnection()

    tasks = cli.load_tasks(args, connection=connection)

    assert len(tasks) == 1
    assert tasks[0].task_id == "database-42"
    assert connection.created_cursor.executed == ["SELECT *\nFROM dbo.candidates;\n"]
    assert connection.created_cursor.closed is True


def test_database_source_requires_an_existing_explicit_query_file(tmp_path: Path):
    args = cli.parse_args(
        ["--input", str(tmp_path / "missing.sql"), "--source", "database"]
    )

    with pytest.raises(cli.CliError, match="SQL query file"):
        cli.load_tasks(args, connection=FakeDatabaseConnection())


def test_rollback_connection_turns_repository_commit_into_rollback():
    connection = FakeDatabaseConnection()
    wrapped = cli.RollbackConnection(connection)

    wrapped.commit()

    assert connection.events == ["rollback"]


def test_database_connection_failure_is_wrapped_without_exposing_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    collector_config = config(tmp_path)
    monkeypatch.setattr(
        cli.pymssql,
        "connect",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError(collector_config.db_password)),
    )

    with pytest.raises(RepositoryError) as caught:
        cli._connect_database(collector_config)

    assert str(caught.value) == "database connection failed"
    assert collector_config.db_password not in str(caught.value)


def test_script_entrypoint_exposes_cli_help_without_external_clients():
    repo_root = Path(__file__).parents[1]
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [
            str(repo_root / ".venv" / "Scripts" / "python.exe"),
            str(repo_root / "scripts" / "run_keyword_discovery_rank.py"),
            "--help",
        ],
        cwd=repo_root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0
    for option in (
        "--input",
        "--source",
        "--device-override",
        "--limit",
        "--dry-run",
        "--rollback-test",
    ):
        assert option in completed.stdout
