from dataclasses import replace

import pytest

from scripts.keyword_discovery_rank.models import CollectStatus, ParsedResult, ParsedSearch
from scripts.keyword_discovery_rank.validation import ResultValidator


def result(
    raw_position: int,
    organic_rank: int | None,
    place_id: str,
    *,
    is_ad: bool = False,
    place_name: str | None = None,
    detail_id: str | None = None,
    category: str | None = "국밥",
    distance_text: str | None = "100m",
) -> ParsedResult:
    resolved_detail_id = place_id if detail_id is None else detail_id
    return ParsedResult(
        raw_position,
        organic_rank,
        place_id,
        place_name if place_name is not None else f"매장 {place_id}",
        category,
        is_ad,
        f"https://m.place.naver.com/restaurant/{resolved_detail_id}" if resolved_detail_id else "",
        distance_text,
    )


def validate(rows, *, observed=None, ended=True, limit=20):
    rows = tuple(rows)
    parsed = ParsedSearch(rows, len(rows) if observed is None else observed, ended)
    return ResultValidator().validate(parsed, limit)


def test_complete_results_allow_missing_optional_category_and_distance():
    outcome = validate([result(1, 1, "101", category=None, distance_text=None)])

    assert outcome.status is CollectStatus.SUCCESS
    assert outcome.results[0].category is None
    assert outcome.results[0].distance_text is None
    assert outcome.message is None


@pytest.mark.parametrize(
    ("rows", "message_fragment"),
    [
        ([result(1, 1, "101"), result(3, 2, "102")], "raw_position"),
        ([result(1, 1, "101"), result(2, 3, "102")], "organic_rank"),
        ([result(1, 1, "101"), result(2, 1, "102")], "duplicate organic_rank"),
        ([result(1, 1, "101"), result(2, 2, "102", is_ad=True)], "advertisement"),
        ([result(1, 1, "101", detail_id="999")], "URL place ID"),
    ],
)
def test_rank_and_url_id_invariant_failures_are_explicit(rows, message_fragment):
    outcome = validate(rows)

    assert outcome.status is CollectStatus.VALIDATION_ERROR
    assert outcome.results == ()
    assert message_fragment in outcome.message


def test_missing_required_card_fields_are_partial_and_only_valid_rows_are_accepted():
    rows = [
        result(1, 1, "101"),
        result(2, 2, "", place_name="아이디 없음"),
        result(3, 3, "103", place_name=""),
    ]

    outcome = validate(rows)

    assert outcome.status is CollectStatus.PARTIAL
    assert [row.place_id for row in outcome.results] == ["101"]
    assert "2 malformed required card(s)" in outcome.message


def test_parser_card_shortfall_is_partial_and_preserves_observed_count():
    outcome = validate([result(1, 1, "101")], observed=3)

    assert outcome.status is CollectStatus.PARTIAL
    assert outcome.observed_result_count == 3
    assert [row.place_id for row in outcome.results] == ["101"]
    assert "2 rendered card(s) were not parsed" in outcome.message


@pytest.mark.parametrize(
    ("ended", "expected_status"),
    [(True, CollectStatus.SUCCESS), (False, CollectStatus.PARTIAL)],
)
def test_short_valid_results_require_an_end_marker(ended, expected_status):
    outcome = validate([result(1, 1, "101"), result(2, 2, "102")], ended=ended)

    assert outcome.status is expected_status


def test_confirmed_empty_results_are_no_result():
    outcome = validate([], observed=0, ended=True)

    assert outcome.status is CollectStatus.NO_RESULT
    assert outcome.results == ()


def test_unconfirmed_empty_results_are_partial():
    outcome = validate([], observed=0, ended=False)

    assert outcome.status is CollectStatus.PARTIAL
    assert "end marker" in outcome.message


def test_observed_batch_beyond_limit_accepts_only_first_requested_visible_cards():
    rows = tuple(result(index, index, str(1000 + index)) for index in range(1, 26))

    outcome = validate(rows, observed=25, ended=False, limit=20)

    assert outcome.status is CollectStatus.SUCCESS
    assert len(outcome.results) == 20
    assert [row.raw_position for row in outcome.results] == list(range(1, 21))
    assert outcome.observed_result_count == 25


def test_cards_after_requested_limit_do_not_change_accepted_prefix_status():
    rows = [result(index, index, str(1000 + index)) for index in range(1, 21)]
    rows.append(replace(result(21, 21, "1021"), detail_url="https://m.place.naver.com/restaurant/9999"))

    outcome = validate(rows, observed=21, ended=False, limit=20)

    assert outcome.status is CollectStatus.SUCCESS
    assert len(outcome.results) == 20


@pytest.mark.parametrize("requested_limit", [0, -1, True])
def test_requested_limit_must_be_a_positive_integer(requested_limit):
    with pytest.raises(ValueError, match="positive integer"):
        validate([], limit=requested_limit)
