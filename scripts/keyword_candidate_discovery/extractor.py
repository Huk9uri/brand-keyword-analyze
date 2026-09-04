from __future__ import annotations

from .lexicon import TERM_PATTERNS
from .models import AnalysisWindow, ExtractedTerm, RawReview


class RuleBasedExtractor:
    def __init__(self, window: AnalysisWindow):
        self._window = window

    def extract(self, review: RawReview) -> tuple[ExtractedTerm, ...]:
        searchable_text = " ".join(part for part in (review.context, review.auxiliary_text) if part).casefold()
        found: list[ExtractedTerm] = []
        seen: set[str] = set()
        for variants, keyword, category in TERM_PATTERNS:
            if keyword in seen or not any(variant.casefold() in searchable_text for variant in variants):
                continue
            seen.add(keyword)
            raw_expression = next(variant for variant in variants if variant.casefold() in searchable_text)
            found.append(ExtractedTerm(
                review=review,
                raw_expression=raw_expression,
                normalized_keyword=keyword,
                term_category=category,
                time_weight=self._window.weight_for(review.review_date),
                extraction_method="DICTIONARY",
                evidence_excerpt=review.context[:1000],
            ))
        return tuple(found)

