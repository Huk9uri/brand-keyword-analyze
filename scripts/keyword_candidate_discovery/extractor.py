from __future__ import annotations

import re

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
            if keyword == "24시간" and not _is_current_twenty_four_hour_service(searchable_text):
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


_TWENTY_FOUR_HOUR_SERVICE = re.compile(r"24\s*시간\s*(?:연중무휴\s*)?(?:영업|운영|오픈)")
_OPENING_HOURS_RANGE = re.compile(
    r"영업\s*시간(?:은|이|:)?\s*(?:매일\s*)?"
    r"(?P<start_hour>\d{1,2}):(?P<start_minute>\d{2})\s*[~～\-]\s*"
    r"(?P<end_hour>\d{1,2}):(?P<end_minute>\d{2})"
)
_HISTORICAL_OR_UNCERTAIN = ("과거", "예전", "이전", "한 적", "했던", "같았", "것 같다", "추정")


def _is_current_twenty_four_hour_service(text: str) -> bool:
    schedules = tuple(_OPENING_HOURS_RANGE.finditer(text))
    if schedules and not all(_is_full_day_schedule(match) for match in schedules):
        return False

    for match in _TWENTY_FOUR_HOUR_SERVICE.finditer(text):
        context = text[max(0, match.start() - 40):min(len(text), match.end() + 40)]
        if not any(marker in context for marker in _HISTORICAL_OR_UNCERTAIN):
            return True
    return False


def _is_full_day_schedule(match: re.Match[str]) -> bool:
    start = (int(match.group("start_hour")), int(match.group("start_minute")))
    end = (int(match.group("end_hour")), int(match.group("end_minute")))
    return start == (0, 0) and end in {(24, 0), (0, 0)}
