from datetime import datetime, timezone

from scripts.place_keyword_collector.change import content_hash, decide_change
from scripts.place_keyword_collector.models import (
    CollectedKeyword,
    KeywordCollectStatus,
    ParsedKeywordList,
    PreviousVersion,
)


def keywords(*values: str) -> tuple[CollectedKeyword, ...]:
    return tuple(CollectedKeyword(i, value, value.casefold()) for i, value in enumerate(values, 1))


def previous(hash_value: str, snapshot_id: int = 41) -> PreviousVersion:
    return PreviousVersion(
        effective_snapshot_id=snapshot_id,
        content_hash=hash_value,
        checked_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        status=KeywordCollectStatus.SUCCESS,
    )


def test_content_hash_is_deterministic_and_includes_normalized_order():
    original = keywords("순대", "순댓국", "국밥")
    same = keywords("순대", "순댓국", "국밥")
    reordered = keywords("국밥", "순대", "순댓국")
    assert content_hash(original) == content_hash(same)
    assert len(content_hash(original)) == 64
    assert content_hash(original) != content_hash(reordered)


def test_content_hash_uses_normalized_values_not_raw_formatting():
    left = (CollectedKeyword(1, " ABC ", "abc"),)
    right = (CollectedKeyword(8, "ＡＢＣ", "abc"),)
    assert content_hash(left) == content_hash(right)


def test_empty_content_hash_is_deterministic():
    assert content_hash(()) == content_hash(())
    assert len(content_hash(())) == 64


def test_first_observation_is_a_changed_success_version():
    parsed = ParsedKeywordList("13149768", keywords("순대"))
    decision = decide_change(None, parsed)
    assert decision.status is KeywordCollectStatus.SUCCESS
    assert decision.content_hash == content_hash(parsed.keywords)
    assert decision.is_changed is True
    assert decision.effective_snapshot_id is None


def test_unchanged_observation_reuses_previous_effective_snapshot():
    parsed = ParsedKeywordList("13149768", keywords("순대"))
    decision = decide_change(previous(content_hash(parsed.keywords), 73), parsed)
    assert decision.status is KeywordCollectStatus.SUCCESS
    assert decision.is_changed is False
    assert decision.effective_snapshot_id == 73


def test_changed_observation_starts_a_new_effective_version():
    parsed = ParsedKeywordList("13149768", keywords("순댓국"))
    decision = decide_change(previous(content_hash(keywords("순대")), 73), parsed)
    assert decision.is_changed is True
    assert decision.effective_snapshot_id is None


def test_empty_observations_are_valid_versions_and_support_unchanged_detection():
    parsed = ParsedKeywordList("13149768", ())
    first = decide_change(None, parsed)
    unchanged = decide_change(previous(content_hash(()), 91), parsed)
    assert first.status is KeywordCollectStatus.EMPTY
    assert first.is_changed is True
    assert unchanged.status is KeywordCollectStatus.EMPTY
    assert unchanged.is_changed is False
    assert unchanged.effective_snapshot_id == 91
