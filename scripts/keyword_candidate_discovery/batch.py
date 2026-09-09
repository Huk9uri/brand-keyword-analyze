from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .models import ExternalKeyword, TermCategory
from .models import AnalysisWindow
from .pipeline import run_discovery
from .review_source import normalize_brand_code, normalize_context


@dataclass(frozen=True)
class BatchStore:
    store_name: str
    place_id: str


@dataclass(frozen=True)
class BatchPlan:
    brand_code: str
    as_of: date
    months: int
    brand_menus: tuple[str, ...]
    stores: tuple[BatchStore, ...]


def load_batch_plan(path: Path) -> BatchPlan:
    payload = json.loads(path.read_text(encoding="utf-8"))
    menus = tuple(
        dict.fromkeys(normalize_context(value) for value in payload.get("brand_menus", []))
    )
    menus = tuple(value for value in menus if value)
    if not menus:
        raise ValueError("브랜드 공통 메뉴가 필요합니다")
    if len(menus) > 5:
        raise ValueError("검색광고 시드 메뉴는 최대 5개까지 허용됩니다")

    stores = tuple(
        BatchStore(str(row.get("store_name") or "").strip(), str(row.get("place_id") or "").strip())
        for row in payload.get("stores", [])
    )
    if not stores or any(not row.store_name or not row.place_id for row in stores):
        raise ValueError("모든 매장에 매장명과 Place ID가 필요합니다")
    place_ids = [row.place_id for row in stores]
    if len(place_ids) != len(set(place_ids)):
        raise ValueError("중복 Place ID는 허용되지 않습니다")

    months = int(payload.get("months", 12))
    if months < 1:
        raise ValueError("분석 개월 수는 1 이상이어야 합니다")
    return BatchPlan(
        brand_code=normalize_brand_code(payload.get("brand_code")),
        as_of=date.fromisoformat(str(payload["as_of"])),
        months=months,
        brand_menus=menus,
        stores=stores,
    )


def build_store_external_keywords(
    plan: BatchPlan,
    related_keywords: tuple[str, ...] = (),
) -> tuple[ExternalKeyword, ...]:
    rows: list[ExternalKeyword] = []
    related = tuple(
        value for value in dict.fromkeys(normalize_context(value) for value in related_keywords) if value
    )
    for store in plan.stores:
        rows.extend(
            ExternalKeyword(
                plan.brand_code, menu, TermCategory.MENU, store.place_id, from_menu=True
            )
            for menu in plan.brand_menus
        )
        rows.extend(
            ExternalKeyword(
                plan.brand_code, keyword, TermCategory.UNKNOWN, store.place_id,
                from_searchad_related=True,
            )
            for keyword in related
        )
    return tuple(rows)


def run_batch_plan(
    plan: BatchPlan,
    source,
    extractor,
    sink,
    *,
    related_keywords: tuple[str, ...] = (),
    dry_run: bool = True,
) -> tuple[dict, ...]:
    external_rows = build_store_external_keywords(plan, related_keywords)
    window = AnalysisWindow(plan.as_of, plan.months)
    summaries: list[dict] = []
    for store in plan.stores:
        store_external = tuple(row for row in external_rows if row.place_id == store.place_id)
        summary = run_discovery(
            plan.brand_code,
            window,
            source,
            extractor,
            sink,
            external_keywords=store_external,
            target_place_id=store.place_id,
            include_brand_candidates=False,
            dry_run=dry_run,
        )
        summaries.append({
            "store_name": store.store_name,
            "place_id": store.place_id,
            **summary.__dict__,
        })
    return tuple(summaries)
