from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class ReviewSourceType(str, Enum):
    BLOG = "BLOG"
    VISITOR = "VISITOR"


class CandidateScope(str, Enum):
    STORE = "STORE"
    BRAND = "BRAND"


class CandidateStatus(str, Enum):
    READY = "READY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    EXCLUDED = "EXCLUDED"


class TermCategory(str, Enum):
    MENU = "MENU"
    DINING_CONTEXT = "DINING_CONTEXT"
    VISIT_PURPOSE = "VISIT_PURPOSE"
    SERVICE_ATTRIBUTE = "SERVICE_ATTRIBUTE"
    FOOD_ATTRIBUTE = "FOOD_ATTRIBUTE"
    NON_VISIT_INTENT = "NON_VISIT_INTENT"
    UNKNOWN = "UNKNOWN"


def subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    month_lengths = (31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return date(year, month, min(value.day, month_lengths[month - 1]))


@dataclass(frozen=True)
class AnalysisWindow:
    as_of: date
    months: int = 12

    @property
    def start_date(self) -> date:
        return subtract_months(self.as_of, self.months)

    def includes(self, review_date: date) -> bool:
        return self.start_date <= review_date <= self.as_of and review_date != date(1900, 1, 1)

    def weight_for(self, review_date: date) -> float:
        if review_date >= subtract_months(self.as_of, 3):
            return 1.0
        if review_date >= subtract_months(self.as_of, 6):
            return 0.8
        if self.includes(review_date):
            return 0.5
        raise ValueError("review date is outside the analysis window")


@dataclass(frozen=True)
class RawReview:
    source_type: ReviewSourceType
    source_review_id: int
    brand_code: str
    place_id: str
    place_name: str
    review_date: date
    context: str
    auxiliary_text: str | None = None


@dataclass(frozen=True)
class ExtractedTerm:
    review: RawReview
    raw_expression: str
    normalized_keyword: str
    term_category: TermCategory
    time_weight: float
    extraction_method: str = "RULE"
    review_required: bool = False
    evidence_excerpt: str = ""


@dataclass(frozen=True)
class ExternalKeyword:
    brand_code: str
    normalized_keyword: str
    term_category: TermCategory
    place_id: str = ""
    from_menu: bool = False
    from_brand_menu: bool = False
    from_operation_keyword: bool = False
    from_searchad_related: bool = False


@dataclass(frozen=True)
class KeywordCandidate:
    brand_code: str
    candidate_scope: CandidateScope
    place_id: str
    normalized_keyword: str
    term_category: TermCategory
    store_review_count: int
    brand_review_count: int
    brand_store_count: int
    weighted_mention_score: float
    from_menu: bool
    from_brand_menu: bool
    from_operation_keyword: bool
    from_searchad_related: bool
    from_review: bool
    candidate_status: CandidateStatus


@dataclass(frozen=True)
class SaveSummary:
    candidate_count: int
    review_term_count: int


@dataclass(frozen=True)
class DiscoverySummary:
    run_id: str
    source_review_count: int
    valid_review_count: int
    extracted_term_count: int
    candidate_count: int
    status_counts: dict[str, int]
    dry_run: bool
    completed_at: datetime

