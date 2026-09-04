from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from io import StringIO
import os
from pathlib import Path
import subprocess
from uuid import UUID

from scripts.place_keyword_collector.browser import PlacePage
from scripts.place_keyword_collector.config import PlaceKeywordConfig
from scripts.place_keyword_collector.repository import EXPECTED_SCHEMA_COLUMNS


RUN_ID = "11111111-1111-1111-1111-111111111111"
RANK_RUN_ID = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 9, 4, 12, 0)


class IntegrationCursor:
    def __init__(self, connection: "IntegrationConnection") -> None:
        self.connection = connection
        self.row = None
        self.rows = []

    def execute(self, sql, params=None):
        normalized = " ".join(sql.lower().split())
        self.connection.events.append(("execute", normalized, params))
        self.row = None
        self.rows = []
        if normalized == "select db_name()":
            self.row = ("naverDB",)
        elif "information_schema.columns" in normalized:
            self.rows = self.connection.schema_rows
        elif normalized.startswith("with ranked_places as"):
            self.rows = self.connection.rank_rows
        elif normalized.startswith("select top (1)"):
            self.row = self.connection.previous_by_place.get(str(params[0]))
        elif normalized.startswith("insert into dbo.naver_place_keyword_snapshot"):
            snapshot_id = self.connection.next_snapshot_id
            self.connection.next_snapshot_id += 1
            self.connection.snapshots.append((snapshot_id, params))
            self.row = (snapshot_id,)
        elif normalized.startswith("update dbo.naver_place_keyword_snapshot"):
            self.connection.effective_updates.append(tuple(params))
        elif normalized.startswith("select count(*)"):
            self.row = (len(self.connection.results[int(params[0])]),)
        else:
            raise AssertionError(f"unexpected SQL: {normalized}")
        return self

    def executemany(self, sql, rows) -> None:
        for row in rows:
            self.connection.results[int(row[0])].append(tuple(row))

    def fetchone(self):
        return self.row

    def fetchall(self):
        return list(self.rows)

    def close(self) -> None:
        self.connection.events.append("cursor-close")


class IntegrationConnection:
    def __init__(self, rank_rows) -> None:
        self.rank_rows = list(rank_rows)
        self.schema_rows = [
            (table, column, *metadata)
            for (table, column), metadata in EXPECTED_SCHEMA_COLUMNS.items()
        ]
        self.previous_by_place = {}
        self.events: list[object] = []
        self.snapshots: list[tuple[int, tuple[object, ...]]] = []
        self.results: dict[int, list[tuple[object, ...]]] = defaultdict(list)
        self.effective_updates: list[tuple[int, int]] = []
        self.next_snapshot_id = 101
        self.commits = 0
        self.rollbacks = 0
        self.close_calls = 0

    def cursor(self) -> IntegrationCursor:
        return IntegrationCursor(self)

    def commit(self) -> None:
        self.commits += 1
        self.events.append("commit")

    def rollback(self) -> None:
        self.rollbacks += 1
        self.events.append("rollback")

    def close(self) -> None:
        self.close_calls += 1
        self.events.append("connection-close")


class IntegrationBrowser:
    def __init__(self, pages: tuple[PlacePage, ...], events: list[object]) -> None:
        self.pages = deque(pages)
        self.events = events

    def fetch(self, target) -> PlacePage:
        self.events.append(("fetch", target.place_id))
        return self.pages.popleft()

    def close(self) -> None:
        self.events.append("browser-close")


class IntegrationBrowserFactory:
    def __init__(self, browser: IntegrationBrowser, events: list[object]) -> None:
        self.browser = browser
        self.events = events

    def create(self) -> IntegrationBrowser:
        self.events.append("browser-create")
        return self.browser


def config(tmp_path: Path) -> PlaceKeywordConfig:
    return PlaceKeywordConfig(
        db_server="localhost",
        db_port=1433,
        db_database="naverDB",
        db_user="collector",
        db_password="secret",
        headless=True,
        timeout_seconds=30,
        artifact_root=tmp_path / "artifacts",
    )


def place_page(place_id: str, keywords: tuple[str, ...]) -> PlacePage:
    rendered = ",".join(f'"{keyword}"' for keyword in keywords)
    return PlacePage(
        f"https://m.place.naver.com/restaurant/{place_id}/home",
        f'<script>{{"id":"{place_id}","keywordList":[{rendered}]}}</script>',
    )


def run_cli(
    tmp_path: Path,
    connection: IntegrationConnection,
    browser_factory: IntegrationBrowserFactory,
    *extra_args: str,
):
    from scripts.place_keyword_collector.cli import main

    output = StringIO()
    errors = StringIO()
    exit_code = main(
        ["--rank-run-id", RANK_RUN_ID, *extra_args],
        repo_root=tmp_path,
        stdout=output,
        stderr=errors,
        uuid_factory=lambda: UUID(RUN_ID),
        clock=lambda: NOW,
        config_loader=lambda _: config(tmp_path),
        connect_database=lambda _: connection,
        browser_factory_builder=lambda _: browser_factory,
    )
    return exit_code, output.getvalue(), errors.getvalue()


def test_cli_composes_rank_source_repository_browser_parser_and_collector(tmp_path: Path):
    connection = IntegrationConnection(
        [
            ("1", "첫 매장"),
            ("2", "둘째 매장"),
            ("1", "중복 매장명"),
        ]
    )
    browser = IntegrationBrowser(
        (
            place_page("1", ("순대", "순댓국")),
            place_page("2", ("국밥",)),
        ),
        connection.events,
    )
    browser_factory = IntegrationBrowserFactory(browser, connection.events)

    exit_code, output, errors = run_cli(
        tmp_path,
        connection,
        browser_factory,
    )

    assert exit_code == 0
    assert errors == ""
    assert [snapshot[1][2] for snapshot in connection.snapshots] == ["1", "2"]
    assert [row[2] for row in connection.results[101]] == ["순대", "순댓국"]
    assert [row[2] for row in connection.results[102]] == ["국밥"]
    assert connection.effective_updates == [(101, 101), (102, 102)]
    assert connection.commits == 2
    assert connection.events.index("browser-create") > max(
        index
        for index, event in enumerate(connection.events)
        if isinstance(event, tuple) and event[0] == "execute"
        and event[1].startswith("select top (1)")
    )
    assert output == (
        f"run_id={RUN_ID} rank_run_id={RANK_RUN_ID} targets=2 due=2 "
        "processed=2 reused=0 SUCCESS=2 failed=0 aborted=false\n"
    )


def test_rollback_test_runs_full_collection_path_without_commits(tmp_path: Path):
    connection = IntegrationConnection([("1", "첫 매장")])
    browser = IntegrationBrowser(
        (place_page("1", ("순대",)),),
        connection.events,
    )
    browser_factory = IntegrationBrowserFactory(browser, connection.events)

    exit_code, output, errors = run_cli(
        tmp_path,
        connection,
        browser_factory,
        "--rollback-test",
    )

    assert exit_code == 0
    assert errors == ""
    assert len(connection.snapshots) == 1
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert "processed=1" in output


def test_script_entrypoint_exposes_cli_help_without_database_or_browser():
    repo_root = Path(__file__).parents[1]
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"

    completed = subprocess.run(
        [
            str(repo_root / ".venv" / "Scripts" / "python.exe"),
            str(repo_root / "scripts" / "run_place_keyword_collector.py"),
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
        "--rank-run-id",
        "--top-n",
        "--refresh-policy",
        "--include-place-id",
        "--force-refresh",
        "--dry-run",
        "--rollback-test",
    ):
        assert option in completed.stdout
