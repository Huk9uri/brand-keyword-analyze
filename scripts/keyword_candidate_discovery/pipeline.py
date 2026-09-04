from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from .aggregator import aggregate_candidates
from .models import AnalysisWindow, DiscoverySummary, ExternalKeyword, ExtractedTerm, RawReview
from .review_source import prepare_reviews


class ReviewSource(Protocol):
    def iter_reviews(
        self, brand_code: str, window: AnalysisWindow, target_place_id: str | None = None
    ): ...


class Extractor(Protocol):
    def extract(self, review: RawReview) -> tuple[ExtractedTerm, ...]: ...


class CandidateSink(Protocol):
    def save_run(self, run_id: str, terms, candidates): ...


def run_discovery(
    brand_code: str,
    window: AnalysisWindow,
    source: ReviewSource,
    extractor: Extractor,
    sink: CandidateSink,
    *,
    external_keywords: Iterable[ExternalKeyword] = (),
    target_place_id: str | None = None,
    include_brand_candidates: bool = True,
    dry_run: bool = True,
    run_id: str | None = None,
) -> DiscoverySummary:
    actual_run_id = run_id or str(uuid4())
    source_rows = tuple(source.iter_reviews(brand_code, window, target_place_id))
    reviews = prepare_reviews(source_rows, window, target_place_id=target_place_id)
    terms = tuple(term for review in reviews for term in extractor.extract(review))
    candidates = aggregate_candidates(
        terms,
        tuple(external_keywords),
        include_brand_candidates=include_brand_candidates,
    )
    if not dry_run:
        sink.save_run(actual_run_id, terms, candidates)
    counts = Counter(candidate.candidate_status.value for candidate in candidates)
    return DiscoverySummary(
        run_id=actual_run_id,
        source_review_count=len(source_rows),
        valid_review_count=len(reviews),
        extracted_term_count=len(terms),
        candidate_count=len(candidates),
        status_counts=dict(sorted(counts.items())),
        dry_run=dry_run,
        completed_at=datetime.now(),
    )
