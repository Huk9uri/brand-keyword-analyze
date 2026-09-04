from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

from .models import AnalysisWindow, RawReview, ReviewSourceType


REVIEW_SELECT_SQL = """
SELECT 'BLOG' AS source_type, review_blog_id AS source_review_id,
       brand_type AS brand_code, place_id, place_name, [date] AS review_date,
       context, title AS auxiliary_text
FROM dbo.naver_review_blog
WHERE TRY_CONVERT(int, brand_type) = %s AND [date] BETWEEN %s AND %s
UNION ALL
SELECT 'VISITOR', review_visitor_id, brand_type, place_id, place_name, [date],
       context, keyword
FROM dbo.naver_review_visitor
WHERE TRY_CONVERT(int, brand_type) = %s AND [date] BETWEEN %s AND %s
"""


def normalize_brand_code(value: object) -> str:
    rendered = str(value or "").strip()
    if rendered.isdigit():
        return str(int(rendered))
    return rendered.casefold()


def normalize_context(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", " ", text)


def prepare_reviews(rows: Iterable[Mapping[str, Any]], window: AnalysisWindow) -> tuple[RawReview, ...]:
    reviews: list[RawReview] = []
    seen: set[tuple[str, str, object, str]] = set()
    for row in rows:
        context = normalize_context(row.get("context"))
        place_id = str(row.get("place_id") or "").strip()
        review_date = row.get("review_date")
        if not context or not place_id or not hasattr(review_date, "year") or not window.includes(review_date):
            continue
        source_type = ReviewSourceType(str(row["source_type"]).upper())
        dedupe_key = (source_type.value, place_id, review_date, context.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        auxiliary = normalize_context(row.get("auxiliary_text")) or None
        reviews.append(RawReview(
            source_type=source_type,
            source_review_id=int(row["source_review_id"]),
            brand_code=normalize_brand_code(row.get("brand_code")),
            place_id=place_id,
            place_name=normalize_context(row.get("place_name")),
            review_date=review_date,
            context=context,
            auxiliary_text=auxiliary,
        ))
    return tuple(reviews)


class ReviewRepository:
    def __init__(self, connection: Any):
        self._connection = connection

    def iter_reviews(self, brand_code: str, window: AnalysisWindow) -> tuple[Mapping[str, Any], ...]:
        cursor = self._connection.cursor(as_dict=True)
        try:
            numeric_code = int(normalize_brand_code(brand_code))
            cursor.execute(REVIEW_SELECT_SQL, (
                numeric_code, window.start_date, window.as_of,
                numeric_code, window.start_date, window.as_of,
            ))
            return tuple(cursor.fetchall())
        finally:
            cursor.close()
