from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .models import (
    CandidateScope, CandidateStatus, ExternalKeyword, ExtractedTerm,
    KeywordCandidate, TermCategory,
)


def aggregate_candidates(
    terms: Iterable[ExtractedTerm],
    external_keywords: Iterable[ExternalKeyword],
    *,
    store_review_threshold: int = 3,
    brand_store_threshold: int = 3,
    include_brand_candidates: bool = True,
) -> tuple[KeywordCandidate, ...]:
    term_rows = tuple(terms)
    external_rows = tuple(external_keywords)
    output: dict[tuple[str, CandidateScope, str, str], KeywordCandidate] = {}

    by_brand_keyword: dict[tuple[str, str], list[ExtractedTerm]] = defaultdict(list)
    by_store_keyword: dict[tuple[str, str, str], list[ExtractedTerm]] = defaultdict(list)
    for term in term_rows:
        review = term.review
        by_brand_keyword[(review.brand_code, term.normalized_keyword)].append(term)
        by_store_keyword[(review.brand_code, review.place_id, term.normalized_keyword)].append(term)

    if include_brand_candidates:
        for (brand_code, keyword), brand_terms in by_brand_keyword.items():
            brand_review_ids = _review_keys(brand_terms)
            brand_store_count = len({term.review.place_id for term in brand_terms})
            category = _category(brand_terms)
            candidate = _build_review_candidate(
                brand_code, CandidateScope.BRAND, "", keyword, category,
                store_review_count=0,
                brand_review_count=len(brand_review_ids),
                brand_store_count=brand_store_count,
                weighted_score=_weighted_score(brand_terms),
                ready=brand_store_count >= brand_store_threshold,
                review_required=any(term.review_required for term in brand_terms),
            )
            output[_key(candidate)] = candidate

    for (brand_code, place_id, keyword), store_terms in by_store_keyword.items():
        brand_terms = by_brand_keyword[(brand_code, keyword)]
        store_count = len(_review_keys(store_terms))
        candidate = _build_review_candidate(
            brand_code, CandidateScope.STORE, place_id, keyword, _category(store_terms),
            store_review_count=store_count,
            brand_review_count=len(_review_keys(brand_terms)),
            brand_store_count=len({term.review.place_id for term in brand_terms}),
            weighted_score=_weighted_score(store_terms),
            ready=store_count >= store_review_threshold,
            review_required=any(term.review_required for term in store_terms),
        )
        output[_key(candidate)] = candidate

    for external in external_rows:
        scope = CandidateScope.STORE if external.place_id else CandidateScope.BRAND
        if scope is CandidateScope.BRAND and not include_brand_candidates:
            continue
        key = (external.brand_code, scope, external.place_id, external.normalized_keyword)
        current = output.get(key)
        if current is None:
            current = KeywordCandidate(
                external.brand_code, scope, external.place_id, external.normalized_keyword,
                external.term_category, 0, 0, 0, 0.0,
                False, False, False, False, False, CandidateStatus.READY,
            )
        output[key] = KeywordCandidate(
            current.brand_code, current.candidate_scope, current.place_id,
            current.normalized_keyword, current.term_category,
            current.store_review_count, current.brand_review_count, current.brand_store_count,
            current.weighted_mention_score,
            current.from_menu or external.from_menu,
            current.from_brand_menu or external.from_brand_menu,
            current.from_operation_keyword or external.from_operation_keyword,
            current.from_searchad_related or external.from_searchad_related,
            current.from_review,
            CandidateStatus.EXCLUDED if current.term_category is TermCategory.NON_VISIT_INTENT else CandidateStatus.READY,
        )

    return tuple(sorted(output.values(), key=lambda item: (
        item.brand_code, item.normalized_keyword, item.candidate_scope.value, item.place_id
    )))


def _build_review_candidate(
    brand_code: str, scope: CandidateScope, place_id: str, keyword: str,
    category: TermCategory, *, store_review_count: int, brand_review_count: int,
    brand_store_count: int, weighted_score: float, ready: bool, review_required: bool,
) -> KeywordCandidate:
    if category is TermCategory.NON_VISIT_INTENT:
        status = CandidateStatus.EXCLUDED
    elif review_required:
        status = CandidateStatus.REVIEW_REQUIRED
    elif ready:
        status = CandidateStatus.READY
    else:
        status = CandidateStatus.INSUFFICIENT_EVIDENCE
    return KeywordCandidate(
        brand_code, scope, place_id, keyword, category,
        store_review_count, brand_review_count, brand_store_count, weighted_score,
        False, False, False, False, True, status,
    )


def _review_keys(terms: Iterable[ExtractedTerm]) -> set[tuple[str, int]]:
    return {(term.review.source_type.value, term.review.source_review_id) for term in terms}


def _weighted_score(terms: Iterable[ExtractedTerm]) -> float:
    per_review: dict[tuple[str, int], float] = {}
    for term in terms:
        key = (term.review.source_type.value, term.review.source_review_id)
        per_review[key] = max(per_review.get(key, 0.0), term.time_weight)
    return round(sum(per_review.values()), 3)


def _category(terms: Iterable[ExtractedTerm]) -> TermCategory:
    categories = [term.term_category for term in terms]
    return categories[0] if categories else TermCategory.UNKNOWN


def _key(candidate: KeywordCandidate) -> tuple[str, CandidateScope, str, str]:
    return (candidate.brand_code, candidate.candidate_scope, candidate.place_id, candidate.normalized_keyword)
