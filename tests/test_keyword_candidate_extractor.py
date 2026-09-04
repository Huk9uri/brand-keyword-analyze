from datetime import date

from scripts.keyword_candidate_discovery.extractor import RuleBasedExtractor
from scripts.keyword_candidate_discovery.models import AnalysisWindow, RawReview, ReviewSourceType, TermCategory


def _review(context):
    return RawReview(ReviewSourceType.VISITOR, 1, "1", "p1", "테스트점", date(2026, 8, 1), context)


def test_extracts_searchable_dining_expressions_and_deduplicates_review():
    extractor = RuleBasedExtractor(AnalysisWindow(date(2026, 9, 4)))

    terms = extractor.extract(_review("혼자 먹기 편해서 혼밥할 때 좋고 해장하기에도 좋아요"))

    assert [(term.normalized_keyword, term.term_category) for term in terms] == [
        ("혼밥", TermCategory.DINING_CONTEXT),
        ("해장", TermCategory.VISIT_PURPOSE),
    ]


def test_marks_non_visit_intent_for_exclusion():
    extractor = RuleBasedExtractor(AnalysisWindow(date(2026, 9, 4)))

    terms = extractor.extract(_review("집에서 먹으려고 설렁탕 밀키트 택배 주문했어요"))

    by_keyword = {term.normalized_keyword: term for term in terms}
    assert by_keyword["설렁탕"].term_category is TermCategory.MENU
    assert by_keyword["밀키트"].term_category is TermCategory.NON_VISIT_INTENT
    assert by_keyword["택배"].term_category is TermCategory.NON_VISIT_INTENT


def test_does_not_emit_generic_sentiment_as_candidate():
    extractor = RuleBasedExtractor(AnalysisWindow(date(2026, 9, 4)))

    assert extractor.extract(_review("음식이 맛있고 직원이 친절해요")) == ()
