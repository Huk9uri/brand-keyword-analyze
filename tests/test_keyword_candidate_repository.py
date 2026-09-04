from datetime import date

from scripts.keyword_candidate_discovery.models import (
    CandidateScope, CandidateStatus, ExtractedTerm, KeywordCandidate, RawReview,
    ReviewSourceType, SaveSummary, TermCategory,
)
from scripts.keyword_candidate_discovery.repository import CandidateRepository


class Cursor:
    def __init__(self, fail_terms=False):
        self.fail_terms = fail_terms
        self.candidate_ids = iter((101, 102))
        self.executions = []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))
        if self.fail_terms and "review_term" in sql:
            raise RuntimeError("term insert failed")

    def fetchone(self):
        return (next(self.candidate_ids),)

    def close(self):
        pass


class Connection:
    def __init__(self, fail_terms=False):
        self.cursor_instance = Cursor(fail_terms)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _candidate():
    return KeywordCandidate("1", CandidateScope.STORE, "p1", "혼밥", TermCategory.DINING_CONTEXT,
                            3, 3, 1, 3.0, False, False, False, False, True, CandidateStatus.READY)


def _term():
    review = RawReview(ReviewSourceType.VISITOR, 1, "1", "p1", "매장", date(2026, 8, 1), "혼밥하기 좋아요")
    return ExtractedTerm(review, "혼밥", "혼밥", TermCategory.DINING_CONTEXT, 1.0,
                         evidence_excerpt=review.context)


def test_save_run_commits_candidates_and_evidence_atomically():
    connection = Connection()

    result = CandidateRepository(connection).save_run("00000000-0000-0000-0000-000000000001", (_term(),), (_candidate(),))

    assert result == SaveSummary(candidate_count=1, review_term_count=1)
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_save_run_rolls_back_when_evidence_insert_fails():
    connection = Connection(fail_terms=True)

    try:
        CandidateRepository(connection).save_run("00000000-0000-0000-0000-000000000001", (_term(),), (_candidate(),))
    except RuntimeError as exc:
        assert "candidate discovery run" in str(exc)
    else:
        raise AssertionError("expected repository failure")

    assert connection.commits == 0
    assert connection.rollbacks == 1

