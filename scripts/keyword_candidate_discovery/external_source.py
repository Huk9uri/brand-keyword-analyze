from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .models import ExternalKeyword, TermCategory
from .review_source import normalize_brand_code, normalize_context


_SOURCE_FLAGS = {
    "MENU": "from_menu",
    "BRAND_MENU": "from_brand_menu",
    "OPERATION": "from_operation_keyword",
    "SEARCHAD": "from_searchad_related",
}


def external_keywords_from_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[ExternalKeyword, ...]:
    keywords: list[ExternalKeyword] = []
    for row in rows:
        keyword = normalize_context(row.get("keyword"))
        if not keyword:
            continue
        source = str(row.get("source") or "").strip().upper()
        if source not in _SOURCE_FLAGS:
            raise ValueError(f"unsupported external keyword source: {source}")
        category_name = str(row.get("category") or "UNKNOWN").strip().upper()
        category = TermCategory(category_name)
        flags = {name: False for name in _SOURCE_FLAGS.values()}
        flags[_SOURCE_FLAGS[source]] = True
        keywords.append(ExternalKeyword(
            brand_code=normalize_brand_code(row.get("brand_code")),
            place_id=str(row.get("place_id") or "").strip(),
            normalized_keyword=keyword,
            term_category=category,
            **flags,
        ))
    return tuple(keywords)

