from datetime import date

from scripts.keyword_candidate_discovery.aggregator import aggregate_candidates
from scripts.keyword_candidate_discovery.models import (
    CandidateScope, CandidateStatus, ExtractedTerm, ExternalKeyword, RawReview,
    ReviewSourceType, TermCategory,
)


def _term(review_id, place_id, keyword="혼밥", weight=1.0, category=TermCategory.DINING_CONTEXT):
    review = RawReview(ReviewSourceType.VISITOR, review_id, "1", place_id, place_id, date(2026, 8, 1), keyword)
    return ExtractedTerm(review, keyword, keyword, category, weight, evidence_excerpt=keyword)


def test_store_and_brand_thresholds_are_evaluated_separately():
    terms = tuple(_term(index, place) for index, place in enumerate(("p1", "p1", "p1", "p2", "p3"), 1))

    candidates = aggregate_candidates(terms, ())

    by_key = {(item.candidate_scope, item.place_id): item for item in candidates if item.normalized_keyword == "혼밥"}
    assert by_key[(CandidateScope.STORE, "p1")].candidate_status is CandidateStatus.READY
    assert by_key[(CandidateScope.STORE, "p2")].candidate_status is CandidateStatus.INSUFFICIENT_EVIDENCE
    assert by_key[(CandidateScope.BRAND, "")].candidate_status is CandidateStatus.READY
    assert by_key[(CandidateScope.BRAND, "")].brand_store_count == 3


def test_external_sources_merge_flags_into_one_store_candidate():
    external = (
        ExternalKeyword("1", "설렁탕", TermCategory.MENU, "p1", from_menu=True),
        ExternalKeyword("1", "설렁탕", TermCategory.MENU, "p1", from_operation_keyword=True),
        ExternalKeyword("1", "설렁탕", TermCategory.MENU, "p1", from_searchad_related=True),
    )

    candidates = aggregate_candidates((), external)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.from_menu and candidate.from_operation_keyword and candidate.from_searchad_related
    assert candidate.candidate_status is CandidateStatus.READY


def test_non_visit_intent_is_excluded_even_when_repeated():
    terms = tuple(_term(i, "p1", "밀키트", category=TermCategory.NON_VISIT_INTENT) for i in range(1, 4))

    candidates = aggregate_candidates(terms, ())

    assert all(item.candidate_status is CandidateStatus.EXCLUDED for item in candidates)


def test_store_only_mode_omits_brand_candidates():
    terms = tuple(_term(index, "p1") for index in range(1, 4))

    candidates = aggregate_candidates(terms, (), include_brand_candidates=False)

    assert candidates
    assert all(item.candidate_scope is CandidateScope.STORE for item in candidates)
