from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from .models import CandidateScope, ExtractedTerm, KeywordCandidate, SaveSummary


CANDIDATE_INSERT_SQL = """
INSERT INTO dbo.naver_keyword_discovery_candidate (
    run_id, brand_code, candidate_scope, place_id, normalized_keyword, term_category,
    store_review_count, brand_review_count, brand_store_count, weighted_mention_score,
    from_menu, from_brand_menu, from_operation_keyword, from_searchad_related,
    from_review, candidate_status, generated_at
)
OUTPUT INSERTED.candidate_id
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

REVIEW_TERM_INSERT_SQL = """
INSERT INTO dbo.naver_keyword_discovery_review_term (
    candidate_id, run_id, source_type, source_review_id, brand_code, place_id,
    review_date, raw_expression, normalized_keyword, term_category, time_weight,
    extraction_method, review_required, evidence_excerpt, analyzed_at
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


class CandidateRepositoryError(RuntimeError):
    pass


class CandidateRepository:
    def __init__(self, connection: Any):
        self._connection = connection

    def save_run(
        self,
        run_id: str,
        terms: Sequence[ExtractedTerm],
        candidates: Sequence[KeywordCandidate],
    ) -> SaveSummary:
        cursor = self._connection.cursor()
        now = datetime.now()
        candidate_ids: dict[tuple[str, CandidateScope, str, str], int] = {}
        try:
            for candidate in candidates:
                cursor.execute(CANDIDATE_INSERT_SQL, _candidate_values(run_id, candidate, now))
                row = cursor.fetchone()
                if row is None:
                    raise CandidateRepositoryError("candidate insert returned no identity")
                candidate_ids[_candidate_key(candidate)] = int(row[0])

            for term in terms:
                key = (term.review.brand_code, CandidateScope.STORE, term.review.place_id, term.normalized_keyword)
                candidate_id = candidate_ids.get(key)
                if candidate_id is None:
                    raise CandidateRepositoryError("review term has no matching store candidate")
                cursor.execute(REVIEW_TERM_INSERT_SQL, _term_values(candidate_id, run_id, term, now))

            self._connection.commit()
            return SaveSummary(len(candidates), len(terms))
        except Exception as exc:
            try:
                self._connection.rollback()
            except Exception as rollback_exc:
                raise CandidateRepositoryError("candidate discovery rollback failed") from rollback_exc
            if isinstance(exc, CandidateRepositoryError):
                raise
            raise CandidateRepositoryError("failed to save candidate discovery run") from exc
        finally:
            cursor.close()


def _candidate_key(candidate: KeywordCandidate) -> tuple[str, CandidateScope, str, str]:
    return candidate.brand_code, candidate.candidate_scope, candidate.place_id, candidate.normalized_keyword


def _candidate_values(run_id: str, item: KeywordCandidate, now: datetime) -> tuple[object, ...]:
    return (
        run_id, item.brand_code, item.candidate_scope.value, item.place_id,
        item.normalized_keyword, item.term_category.value,
        item.store_review_count, item.brand_review_count, item.brand_store_count,
        item.weighted_mention_score, item.from_menu, item.from_brand_menu,
        item.from_operation_keyword, item.from_searchad_related, item.from_review,
        item.candidate_status.value, now,
    )


def _term_values(
    candidate_id: int, run_id: str, term: ExtractedTerm, now: datetime
) -> tuple[object, ...]:
    review = term.review
    return (
        candidate_id, run_id, review.source_type.value, review.source_review_id,
        review.brand_code, review.place_id, review.review_date, term.raw_expression,
        term.normalized_keyword, term.term_category.value, term.time_weight,
        term.extraction_method, term.review_required, term.evidence_excerpt, now,
    )

