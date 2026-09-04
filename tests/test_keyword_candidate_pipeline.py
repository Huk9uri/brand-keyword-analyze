from datetime import date

from scripts.keyword_candidate_discovery.extractor import RuleBasedExtractor
from scripts.keyword_candidate_discovery.models import AnalysisWindow
from scripts.keyword_candidate_discovery.pipeline import run_discovery


class Source:
    def iter_reviews(self, brand_code, window, target_place_id=None):
        return tuple({
            "source_type": "VISITOR", "source_review_id": index, "brand_code": brand_code,
            "place_id": "p1", "place_name": "매장", "review_date": date(2026, 8, index),
            "context": "혼밥하기 좋아요", "auxiliary_text": None,
        } for index in (1, 2, 3))


class Sink:
    def __init__(self):
        self.calls = []

    def save_run(self, run_id, terms, candidates):
        self.calls.append((run_id, terms, candidates))


def test_dry_run_builds_candidates_without_writing():
    window = AnalysisWindow(date(2026, 9, 4))
    sink = Sink()

    summary = run_discovery("1", window, Source(), RuleBasedExtractor(window), sink, dry_run=True)

    assert summary.source_review_count == 3
    assert summary.valid_review_count == 3
    assert summary.extracted_term_count == 3
    assert summary.status_counts["READY"] >= 1
    assert sink.calls == []


def test_live_run_persists_one_run():
    window = AnalysisWindow(date(2026, 9, 4))
    sink = Sink()

    summary = run_discovery("1", window, Source(), RuleBasedExtractor(window), sink, dry_run=False)

    assert not summary.dry_run
    assert len(sink.calls) == 1


def test_target_place_run_only_builds_store_candidates_for_that_place():
    window = AnalysisWindow(date(2026, 9, 4))
    sink = Sink()

    run_discovery(
        "1", window, Source(), RuleBasedExtractor(window), sink,
        target_place_id="p1", include_brand_candidates=False, dry_run=False,
    )

    candidates = sink.calls[0][2]
    assert candidates
    assert all(candidate.place_id == "p1" for candidate in candidates)
    assert all(candidate.candidate_scope.value == "STORE" for candidate in candidates)
