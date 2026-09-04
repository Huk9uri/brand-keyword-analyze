from datetime import date

from scripts.keyword_candidate_discovery.models import AnalysisWindow, ReviewSourceType
from scripts.keyword_candidate_discovery.review_source import normalize_brand_code, prepare_reviews


def _row(source, review_id, brand_code, place_id, review_date, context, auxiliary_text=None):
    return {
        "source_type": source,
        "source_review_id": review_id,
        "brand_code": brand_code,
        "place_id": place_id,
        "place_name": "테스트점",
        "review_date": review_date,
        "context": context,
        "auxiliary_text": auxiliary_text,
    }


def test_normalize_brand_code_merges_padded_and_unpadded_codes():
    assert normalize_brand_code("01") == "1"
    assert normalize_brand_code("1") == "1"
    assert normalize_brand_code("02") == "2"


def test_prepare_reviews_filters_invalid_rows_and_deduplicates_content():
    window = AnalysisWindow(as_of=date(2026, 9, 4), months=12)
    rows = [
        _row("BLOG", 1, "01", "p1", date(2026, 8, 1), " 혼자   먹기 좋아요 ", "제목"),
        _row("BLOG", 2, "1", "p1", date(2026, 8, 1), "혼자 먹기 좋아요", "다른 제목"),
        _row("VISITOR", 3, "01", "p1", date(2025, 9, 3), "오래된 리뷰"),
        _row("VISITOR", 4, "01", "p1", date(1900, 1, 1), "비정상 날짜"),
        _row("VISITOR", 5, "01", "p1", date(2026, 8, 1), "  "),
        _row("VISITOR", 6, "01", "", date(2026, 8, 1), "매장 없음"),
    ]

    reviews = prepare_reviews(rows, window)

    assert len(reviews) == 1
    assert reviews[0].source_type is ReviewSourceType.BLOG
    assert reviews[0].source_review_id == 1
    assert reviews[0].brand_code == "1"
    assert reviews[0].context == "혼자 먹기 좋아요"
    assert reviews[0].auxiliary_text == "제목"


def test_analysis_window_assigns_recency_weights():
    window = AnalysisWindow(as_of=date(2026, 9, 4), months=12)

    assert window.weight_for(date(2026, 8, 4)) == 1.0
    assert window.weight_for(date(2026, 4, 4)) == 0.8
    assert window.weight_for(date(2025, 11, 4)) == 0.5
    assert window.includes(date(2025, 9, 4))
    assert not window.includes(date(2025, 9, 3))
