from datetime import datetime, timezone

import pytest

from scripts.place_keyword_collector.models import (
    CollectedKeyword,
    CollectionSummary,
    KeywordCollectStatus,
    KeywordSnapshot,
    ParsedKeywordList,
    PreviousVersion,
    RankPlaceTarget,
    RefreshPolicy,
)


def test_status_and_refresh_policy_preserve_persistence_values():
    assert RefreshPolicy.MONTHLY.value == "MONTHLY"
    assert RefreshPolicy.WEEKLY.value == "WEEKLY"
    assert {status.value for status in KeywordCollectStatus} == {
        "SUCCESS",
        "EMPTY",
        "BLOCKED",
        "LOAD_TIMEOUT",
        "PLACE_MISMATCH",
        "PARSE_ERROR",
    }


def test_contract_records_preserve_keyword_order_and_snapshot_lineage():
    checked_at = datetime(2026, 9, 4, 10, 30, tzinfo=timezone.utc)
    target = RankPlaceTarget(place_id="13149768", place_name="농민백암순대 본점")
    keywords = ParsedKeywordList(
        place_id=target.place_id,
        keywords=(
            CollectedKeyword(1, "순대", "순대"),
            CollectedKeyword(2, " 순댓국 ", "순댓국"),
        ),
    )
    previous = PreviousVersion(
        effective_snapshot_id=7,
        content_hash="abc123",
        checked_at=checked_at,
        status=KeywordCollectStatus.SUCCESS,
    )
    snapshot = KeywordSnapshot(
        snapshot_id=8,
        run_id="collect-run",
        rank_run_id="rank-run",
        target=target,
        source_url="https://m.place.naver.com/restaurant/13149768/home",
        status=KeywordCollectStatus.SUCCESS,
        content_hash="def456",
        is_changed=True,
        effective_snapshot_id=8,
        keyword_count=2,
        parser_version="v1",
        collect_msg=None,
        checked_at=checked_at,
    )
    summary = CollectionSummary(
        run_id="collect-run",
        rank_run_id="rank-run",
        target_count=1,
        success_count=1,
        empty_count=0,
        failed_count=0,
    )

    assert keywords.keywords[1].keyword_order == 2
    assert previous.effective_snapshot_id == 7
    assert snapshot.target == target
    assert snapshot.effective_snapshot_id == snapshot.snapshot_id
    assert summary.target_count == summary.success_count + summary.empty_count + summary.failed_count


def test_contract_records_are_immutable():
    target = RankPlaceTarget(place_id="13149768", place_name="농민백암순대 본점")

    with pytest.raises(Exception):
        target.place_name = "changed"  # type: ignore[misc]
