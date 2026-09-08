from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from uuid import UUID

import pytest

from scripts.place_keyword_collector.browser import PlacePage
from scripts.place_keyword_collector.collector import CollectorSummary
from scripts.place_keyword_collector.config import ConfigError, PlaceKeywordConfig
from scripts.place_keyword_collector.models import (
    KeywordCollectStatus,
    PreviousVersion,
    RankPlaceTarget,
    RefreshPolicy,
)
from scripts.place_keyword_collector.repository import (
    FatalRepositoryError,
    TaskPersistenceError,
)


RUN_ID = "11111111-1111-1111-1111-111111111111"
RANK_RUN_ID = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 9, 4, 12, 0)


def target(place_id: str) -> RankPlaceTarget:
    return RankPlaceTarget(place_id, f"매장 {place_id}")


def page(place_id: str, *keywords: str) -> PlacePage:
    rendered = ",".join(f'"{keyword}"' for keyword in keywords)
    return PlacePage(
        f"https://m.place.naver.com/restaurant/{place_id}/home",
        f'<script>{{"id":"{place_id}","keywordList":[{rendered}]}}</script>',
    )


def previous(days_ago: int) -> PreviousVersion:
    return PreviousVersion(
        effective_snapshot_id=73,
        content_hash="a" * 64,
        checked_at=NOW - timedelta(days=days_ago),
        status=KeywordCollectStatus.SUCCESS,
    )


class FakeCursor:
    def __init__(self, events: list[object]) -> None:
        self.events = events

    def close(self) -> None:
        self.events.append("rank-cursor-close")


class FakeConnection:
    def __init__(self, events: list[object]) -> None:
        self.events = events
        self.commits = 0
        self.rollbacks = 0
        self.close_calls = 0

    def cursor(self) -> FakeCursor:
        self.events.append("rank-cursor")
        return FakeCursor(self.events)

    def commit(self) -> None:
        self.commits += 1
        self.events.append("commit")

    def rollback(self) -> None:
        self.rollbacks += 1
        self.events.append("rollback")

    def close(self) -> None:
        self.close_calls += 1
        self.events.append("connection-close")


class FakeRankSource:
    def __init__(
        self,
        cursor: FakeCursor,
        targets: tuple[RankPlaceTarget, ...],
        events: list[object],
    ) -> None:
        self.cursor = cursor
        self.targets = targets
        self.events = events

    def load(self, rank_run_id: str, top_n: int):
        self.events.append(("rank-load", rank_run_id, top_n))
        return self.targets


class FakeRepository:
    def __init__(
        self,
        connection,
        previous_by_place: dict[str, PreviousVersion],
        events: list[object],
        *,
        preflight_error: Exception | None = None,
        save_error: Exception | None = None,
    ) -> None:
        self.connection = connection
        self.previous_by_place = previous_by_place
        self.events = events
        self.preflight_error = preflight_error
        self.save_error = save_error
        self.save_calls = 0

    def preflight(self, expected_database: str = "naverDB") -> None:
        self.events.append(("preflight", expected_database))
        if self.preflight_error is not None:
            raise self.preflight_error

    def get_previous(self, place_id: str):
        self.events.append(("previous", place_id))
        return self.previous_by_place.get(place_id)

    def save(self, snapshot, keywords) -> int:
        self.save_calls += 1
        self.events.append(("save", snapshot.target.place_id))
        if self.save_error is not None:
            raise self.save_error
        self.connection.commit()
        return self.save_calls

    def close(self) -> None:
        self.connection.close()


class FakeBrowser:
    def __init__(self, pages: tuple[PlacePage, ...], events: list[object]) -> None:
        self.pages = deque(pages)
        self.events = events
        self.close_calls = 0

    def fetch(self, place_target: RankPlaceTarget) -> PlacePage:
        self.events.append(("fetch", place_target.place_id))
        return self.pages.popleft()

    def close(self) -> None:
        self.close_calls += 1
        self.events.append("browser-close")


class FakeBrowserFactory:
    def __init__(self, browser: FakeBrowser, events: list[object]) -> None:
        self.browser = browser
        self.events = events
        self.create_calls = 0

    def create(self) -> FakeBrowser:
        self.create_calls += 1
        self.events.append("browser-create")
        return self.browser


class CliHarness:
    def __init__(
        self,
        tmp_path: Path,
        *,
        targets: tuple[RankPlaceTarget, ...],
        previous_by_place: dict[str, PreviousVersion] | None = None,
        pages: tuple[PlacePage, ...] | None = None,
        preflight_error: Exception | None = None,
        save_error: Exception | None = None,
        collector_factory=None,
        config_error: Exception | None = None,
    ) -> None:
        self.tmp_path = tmp_path
        self.targets = targets
        self.events: list[object] = []
        self.connection = FakeConnection(self.events)
        self.repository = FakeRepository(
            self.connection,
            previous_by_place or {},
            self.events,
            preflight_error=preflight_error,
            save_error=save_error,
        )
        if pages is None:
            pages = tuple(page(item.place_id, f"키워드 {item.place_id}") for item in targets)
        self.browser = FakeBrowser(pages, self.events)
        self.browser_factory = FakeBrowserFactory(self.browser, self.events)
        self.collector_factory = collector_factory
        self.config_error = config_error
        self.stdout = StringIO()
        self.stderr = StringIO()

    @property
    def output(self) -> str:
        return self.stdout.getvalue()

    @property
    def errors(self) -> str:
        return self.stderr.getvalue()

    @property
    def browser_create_calls(self) -> int:
        return self.browser_factory.create_calls

    @property
    def repository_save_calls(self) -> int:
        return self.repository.save_calls

    def run(self, argv: list[str]) -> int:
        from scripts.place_keyword_collector import cli

        config = PlaceKeywordConfig(
            db_server="localhost",
            db_port=1433,
            db_database="naverDB",
            db_user="collector",
            db_password="secret",
            headless=True,
            timeout_seconds=30,
            artifact_root=self.tmp_path / "artifacts",
        )

        def load_config(repo_root: Path) -> PlaceKeywordConfig:
            self.events.append("config")
            if self.config_error is not None:
                raise self.config_error
            return config

        def build_repository(connection):
            self.repository.connection = connection
            return self.repository

        options = {
            "repo_root": self.tmp_path,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "uuid_factory": lambda: UUID(RUN_ID),
            "clock": lambda: NOW,
            "config_loader": load_config,
            "connect_database": lambda _: self.events.append("connect") or self.connection,
            "rank_source_factory": lambda cursor: FakeRankSource(
                cursor, self.targets, self.events
            ),
            "repository_factory": build_repository,
            "browser_factory_builder": lambda _: self.events.append(
                "browser-factory"
            )
            or self.browser_factory,
        }
        if self.collector_factory is not None:
            options["collector_factory"] = self.collector_factory
        return cli.main(argv, **options)


def test_cli_requires_rank_run_id():
    from scripts.place_keyword_collector.cli import parse_args

    with pytest.raises(SystemExit) as caught:
        parse_args([])

    assert caught.value.code == 2


def test_cli_defaults_to_top_ten_and_monthly():
    from scripts.place_keyword_collector.cli import parse_args

    args = parse_args(["--rank-run-id", RANK_RUN_ID])

    assert args.top_n == 10
    assert args.refresh_policy == "monthly"


@pytest.mark.parametrize("rank_run_id", ["not-a-uuid", "../escape"])
def test_cli_rejects_non_uuid_rank_run_id(rank_run_id: str):
    from scripts.place_keyword_collector.cli import parse_args

    with pytest.raises(SystemExit) as caught:
        parse_args(["--rank-run-id", rank_run_id])

    assert caught.value.code == 2


def test_cli_accepts_all_collection_options():
    from scripts.place_keyword_collector.cli import parse_args

    args = parse_args(
        [
            "--rank-run-id",
            RANK_RUN_ID,
            "--top-n",
            "7",
            "--refresh-policy",
            "weekly",
            "--include-place-id",
            "2",
            "--include-place-id",
            "1",
            "--force-refresh",
            "--dry-run",
            "--rollback-test",
        ]
    )

    assert args.top_n == 7
    assert args.refresh_policy == "weekly"
    assert args.include_place_id == ["2", "1"]
    assert args.force_refresh is True
    assert args.dry_run is True
    assert args.rollback_test is True


@pytest.mark.parametrize("top_n", ["0", "21", "not-a-number"])
def test_cli_rejects_top_n_outside_rank_card_boundary(top_n: str):
    from scripts.place_keyword_collector.cli import parse_args

    with pytest.raises(SystemExit) as caught:
        parse_args(["--rank-run-id", RANK_RUN_ID, "--top-n", top_n])

    assert caught.value.code == 2


def test_include_place_id_preserves_rank_source_order():
    from scripts.place_keyword_collector.cli import select_included_targets

    targets = (target("1"), target("2"), target("3"))

    selected = select_included_targets(targets, ("3", "1"))

    assert [item.place_id for item in selected] == ["1", "3"]


def test_include_place_id_rejects_ids_absent_from_rank_run():
    from scripts.place_keyword_collector.cli import CliError, select_included_targets

    targets = (RankPlaceTarget("13149768", "농민백암순대 본점"),)

    with pytest.raises(
        CliError,
        match="requested Place ID is absent from the rank run: 999",
    ):
        select_included_targets(targets, ("999",))


@pytest.mark.parametrize("place_id", ["../escape", "12/34", "１２３", "abc"])
def test_cli_rejects_non_numeric_include_place_id(place_id: str):
    from scripts.place_keyword_collector.cli import parse_args

    with pytest.raises(SystemExit) as caught:
        parse_args(
            [
                "--rank-run-id",
                RANK_RUN_ID,
                "--include-place-id",
                place_id,
            ]
        )

    assert caught.value.code == 2


def test_dry_run_lists_unique_target_count_without_browser_or_writes(tmp_path: Path):
    harness = CliHarness(
        tmp_path,
        targets=(target("1"), target("2"), target("1"), target("3")),
    )

    assert harness.run(["--rank-run-id", RANK_RUN_ID, "--dry-run"]) == 0

    assert harness.output == (
        f"run_id={RUN_ID} rank_run_id={RANK_RUN_ID} targets=3 due=3 dry_run=true\n"
    )
    assert harness.browser_create_calls == 0
    assert harness.repository_save_calls == 0
    assert harness.connection.commits == 0
    assert harness.connection.rollbacks == 0


def test_dry_run_calculates_due_count_from_refresh_policy(tmp_path: Path):
    harness = CliHarness(
        tmp_path,
        targets=(target("1"), target("2")),
        previous_by_place={"1": previous(days_ago=1), "2": previous(days_ago=40)},
    )

    assert harness.run(["--rank-run-id", RANK_RUN_ID, "--dry-run"]) == 0

    assert "targets=2 due=1 dry_run=true" in harness.output
    assert harness.browser_create_calls == 0


def test_include_filter_is_validated_before_due_lookups(tmp_path: Path):
    harness = CliHarness(tmp_path, targets=(target("1"), target("2")))

    exit_code = harness.run(
        ["--rank-run-id", RANK_RUN_ID, "--include-place-id", "999"]
    )

    assert exit_code == 2
    assert harness.errors == (
        "error=requested Place ID is absent from the rank run: 999\n"
    )
    assert not any(
        isinstance(event, tuple) and event[0] == "previous"
        for event in harness.events
    )
    assert harness.browser_create_calls == 0


def test_schema_preflight_and_all_due_lookups_precede_browser_creation(tmp_path: Path):
    harness = CliHarness(
        tmp_path,
        targets=(target("1"), target("2")),
        pages=(page("1", "순대"), page("2", "국밥")),
    )

    assert harness.run(["--rank-run-id", RANK_RUN_ID]) == 0

    assert harness.events.index(("preflight", "naverDB")) < harness.events.index(
        "browser-create"
    )
    assert harness.events.index(("previous", "2")) < harness.events.index(
        "browser-create"
    )
    assert harness.repository_save_calls == 2
    assert harness.connection.commits == 2
    assert "targets=2 due=2 processed=2 reused=0 SUCCESS=2" in harness.output


def test_force_refresh_collects_a_recent_target(tmp_path: Path):
    harness = CliHarness(
        tmp_path,
        targets=(target("1"),),
        previous_by_place={"1": previous(days_ago=1)},
        pages=(page("1", "새 키워드"),),
    )

    assert (
        harness.run(["--rank-run-id", RANK_RUN_ID, "--force-refresh"]) == 0
    )

    assert harness.repository_save_calls == 1
    assert "due=1 processed=1 reused=0" in harness.output


def test_rollback_test_converts_repository_commits_to_rollbacks(tmp_path: Path):
    harness = CliHarness(
        tmp_path,
        targets=(target("1"),),
        pages=(page("1", "순대"),),
    )

    assert harness.run(["--rank-run-id", RANK_RUN_ID, "--rollback-test"]) == 0

    assert harness.browser_create_calls == 1
    assert harness.repository_save_calls == 1
    assert harness.connection.commits == 0
    assert harness.connection.rollbacks == 1


def test_controlled_abort_returns_exit_one(tmp_path: Path):
    def collector_factory(*args, **kwargs):
        class AbortingCollector:
            def run(self, targets, run_id, rank_run_id, policy, force_refresh=False):
                return CollectorSummary(
                    run_id=run_id,
                    rank_run_id=rank_run_id,
                    target_count=len(tuple(targets)),
                    success_count=0,
                    empty_count=0,
                    failed_count=5,
                    processed_count=5,
                    status_counts={KeywordCollectStatus.LOAD_TIMEOUT: 5},
                    aborted=True,
                    abort_reason="aborted after 5 identical consecutive failures",
                )

        return AbortingCollector()

    harness = CliHarness(
        tmp_path,
        targets=tuple(target(str(index)) for index in range(1, 7)),
        collector_factory=collector_factory,
    )

    assert harness.run(["--rank-run-id", RANK_RUN_ID]) == 1
    assert "aborted=true" in harness.output


def test_task_persistence_failure_returns_exit_one_and_closes_browser(tmp_path: Path):
    harness = CliHarness(
        tmp_path,
        targets=(target("1"),),
        pages=(page("1", "순대"),),
        save_error=TaskPersistenceError("driver secret detail"),
    )

    assert harness.run(["--rank-run-id", RANK_RUN_ID]) == 1

    assert harness.errors == "error=task persistence failed\n"
    assert "secret" not in harness.errors
    assert harness.browser.close_calls == 1


def test_preflight_failure_returns_exit_two_without_browser(tmp_path: Path):
    harness = CliHarness(
        tmp_path,
        targets=(target("1"),),
        preflight_error=FatalRepositoryError("schema driver secret"),
    )

    assert harness.run(["--rank-run-id", RANK_RUN_ID]) == 2

    assert harness.errors == "error=database preflight or persistence failed\n"
    assert "secret" not in harness.errors
    assert harness.browser_create_calls == 0
    assert harness.connection.close_calls == 1


def test_configuration_failure_returns_exit_two_before_database(tmp_path: Path):
    harness = CliHarness(
        tmp_path,
        targets=(target("1"),),
        config_error=ConfigError("missing environment keys: DB_SERVER"),
    )

    assert harness.run(["--rank-run-id", RANK_RUN_ID]) == 2

    assert harness.errors == "error=missing environment keys: DB_SERVER\n"
    assert "connect" not in harness.events
