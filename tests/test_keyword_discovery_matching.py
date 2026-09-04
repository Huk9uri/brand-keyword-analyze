from dataclasses import FrozenInstanceError

import pytest

from scripts.keyword_discovery_rank.matching import OwnStore, OwnStoreMatcher
from scripts.keyword_discovery_rank.models import MatchMethod, ParsedResult


def result(place_id: str, place_name: str) -> ParsedResult:
    return ParsedResult(
        raw_position=1,
        organic_rank=1,
        place_id=place_id,
        place_name=place_name,
        category="국밥",
        is_ad=False,
        detail_url=f"https://m.place.naver.com/restaurant/{place_id}",
        distance_text="100m",
    )


def matcher(*, manual_place_id_mappings=None) -> OwnStoreMatcher:
    return OwnStoreMatcher(
        (
            OwnStore("S1", "육수당 선릉점", "place-s1"),
            OwnStore("S2", "육수당 강남점", "place-s2"),
        ),
        manual_place_id_mappings=manual_place_id_mappings,
    )


def test_place_id_match_has_highest_precedence_over_manual_mapping_and_name():
    decision = matcher(manual_place_id_mappings={"place-s1": "S2"}).match(
        result("place-s1", "육수당 강남점")
    )

    assert (decision.is_own_store, decision.matched_store_id, decision.match_method) == (
        True,
        "S1",
        MatchMethod.PLACE_ID,
    )


def test_manual_place_id_mapping_precedes_exact_name():
    decision = matcher(manual_place_id_mappings={"legacy-place": "S2"}).match(
        result("legacy-place", "육수당 선릉점")
    )

    assert (decision.is_own_store, decision.matched_store_id, decision.match_method) == (
        True,
        "S2",
        MatchMethod.MANUAL_MAPPING,
    )


def test_exact_name_match_precedes_normalized_name():
    decision = matcher().match(result("unmapped-place", "육수당 선릉점"))

    assert (decision.is_own_store, decision.matched_store_id, decision.match_method) == (
        True,
        "S1",
        MatchMethod.EXACT_NAME,
    )


def test_normalized_name_match_removes_nfkc_spacing_and_punctuation_only():
    unicode_matcher = OwnStoreMatcher((OwnStore("S1", "YUKSU-DANG 선릉점"),))

    decision = unicode_matcher.match(result("unmapped-place", "ｙｕｋｓｕ　ｄａｎｇ 선릉점"))

    assert (decision.is_own_store, decision.matched_store_id, decision.match_method) == (
        True,
        "S1",
        MatchMethod.NORMALIZED_NAME,
    )


@pytest.mark.parametrize(
    "competitor_name",
    [
        "육수당 선릉점 2호점",
        "신 육수당 선릉점",
        "육수당 선릉",
        "육수당 선릉점프",
    ],
)
def test_near_name_competitors_are_not_matched_by_containment(competitor_name):
    decision = matcher().match(result("unmapped-place", competitor_name))

    assert (decision.is_own_store, decision.matched_store_id, decision.match_method) == (
        False,
        None,
        MatchMethod.NONE,
    )


def test_empty_place_id_does_not_activate_an_empty_manual_mapping_key():
    decision = matcher(manual_place_id_mappings={"": "S1"}).match(result("", "경쟁 국밥집"))

    assert (decision.is_own_store, decision.matched_store_id, decision.match_method) == (
        False,
        None,
        MatchMethod.NONE,
    )


def test_match_decision_applies_to_frozen_parsed_result_without_mutating_it():
    parsed_result = result("unmapped-place", "육수당 선릉점")
    decision = matcher().match(parsed_result)

    matched = decision.apply_to(parsed_result)

    assert (matched.is_own_store, matched.matched_store_id, matched.match_method) == (
        True,
        "S1",
        MatchMethod.EXACT_NAME,
    )
    assert parsed_result.is_own_store is False
    with pytest.raises(FrozenInstanceError):
        matched.is_own_store = False
