from datetime import datetime

import pytest

from scripts.place_keyword_collector.models import (
    KeywordCollectStatus,
    PreviousVersion,
    RefreshPolicy,
)


RUN_ID = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 9, 4, 10, 30)


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.params = None
        self.sql = None

    def execute(self, sql, params):
        self.sql = sql
        self.params = params
        return self

    def fetchall(self):
        return list(self._rows)


@pytest.fixture
def fake_cursor():
    return FakeCursor(
        [
            ("13149768", "농민백암순대 본점"),
            ("12006259", "육수당 선릉점"),
        ]
    )


def version(*, checked_at: datetime) -> PreviousVersion:
    return PreviousVersion(
        effective_snapshot_id=42,
        content_hash="a" * 64,
        checked_at=checked_at,
        status=KeywordCollectStatus.SUCCESS,
    )


def test_rank_source_selects_top_ten_organic_and_deduplicates_place_ids(fake_cursor):
    from scripts.place_keyword_collector.rank_source import RankResultSource

    targets = RankResultSource(fake_cursor).load(RUN_ID, 10)

    assert [target.place_id for target in targets] == ["13149768", "12006259"]
    assert fake_cursor.params == (RUN_ID, 10)


def test_rank_source_defaults_to_top_ten_when_limit_is_omitted(fake_cursor):
    from scripts.place_keyword_collector.rank_source import RankResultSource

    RankResultSource(fake_cursor).load(RUN_ID)

    assert fake_cursor.params == (RUN_ID, 10)


def test_rank_source_query_limits_successful_organic_results_and_uses_deterministic_deduplication(
    fake_cursor,
):
    from scripts.place_keyword_collector.rank_source import RankResultSource

    RankResultSource(fake_cursor).load(RUN_ID, 10)

    query = " ".join(fake_cursor.sql.lower().split())
    assert "collect_status in ('success', 'partial')" in query
    assert "organic_rank is not null" in query
    assert "is_ad = 0" in query
    assert "organic_rank <= %s" in query
    assert "row_number() over" in query
    assert "partition by result.place_id" in query
    assert "order by result.organic_rank, result.place_name" in query


def test_monthly_refresh_is_due_one_calendar_month_later():
    from scripts.place_keyword_collector.rank_source import is_refresh_due

    previous = version(checked_at=datetime(2026, 1, 31, 9))

    assert is_refresh_due(previous, RefreshPolicy.MONTHLY, datetime(2026, 2, 28, 9), False)


def test_weekly_refresh_is_due_after_seven_days():
    from scripts.place_keyword_collector.rank_source import is_refresh_due

    previous = version(checked_at=datetime(2026, 9, 1, 10))

    assert not is_refresh_due(previous, RefreshPolicy.WEEKLY, datetime(2026, 9, 8, 9, 59), False)
    assert is_refresh_due(previous, RefreshPolicy.WEEKLY, datetime(2026, 9, 8, 10), False)


def test_absent_previous_version_is_due_for_refresh():
    from scripts.place_keyword_collector.rank_source import is_refresh_due

    assert is_refresh_due(None, RefreshPolicy.MONTHLY, NOW, False)


def test_force_refresh_ignores_recent_check():
    from scripts.place_keyword_collector.rank_source import is_refresh_due

    assert is_refresh_due(version(checked_at=NOW), RefreshPolicy.MONTHLY, NOW, True)
