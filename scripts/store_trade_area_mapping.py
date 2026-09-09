"""매장 대상 뷰와 상권 분류표를 안전하게 매핑한다."""

from __future__ import annotations

import re
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable, Mapping
from pathlib import Path


@dataclass(frozen=True)
class StoreTarget:
    store_name: str
    place_id: str
    store_code: str | None = None
    naver_store_name: str | None = None


@dataclass(frozen=True)
class PdfTradeArea:
    store_name: str
    trade_area_type: str


@dataclass(frozen=True)
class TradeAreaMapping:
    brand: str
    db_store_name: str
    place_id: str
    pdf_store_name: str | None
    trade_area_type: str | None
    match_status: str
    match_method: str | None
    store_code: str | None = None
    naver_store_name: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def normalize_store_name(store_name: str, brand: str) -> str:
    value = re.sub(r"\s+", "", store_name or "")
    normalized_brand = re.sub(r"\s+", "", brand or "")
    value = value.replace("한촌설렁탕&갈비", normalized_brand)
    if value.startswith(normalized_brand):
        value = value[len(normalized_brand) :]
    value = re.sub(r"\(법인\)$", "", value)
    value = re.sub(r"(?:지점|점)$", "", value)
    return value


def map_trade_areas(
    brand: str,
    targets: Iterable[StoreTarget],
    source_rows: Iterable[PdfTradeArea],
    manual_aliases: Mapping[str, str] | None = None,
) -> list[TradeAreaMapping]:
    source_index: dict[str, list[PdfTradeArea]] = {}
    for row in source_rows:
        key = normalize_store_name(row.store_name, brand)
        source_index.setdefault(key, []).append(row)

    mappings: list[TradeAreaMapping] = []
    aliases = manual_aliases or {}
    for target in targets:
        key = normalize_store_name(target.store_name, brand)
        alias_name = aliases.get(target.store_name)
        if alias_name:
            matches = source_index.get(normalize_store_name(alias_name, brand), [])
            match_method = "MANUAL_ALIAS"
        else:
            matches = source_index.get(key, [])
            match_method = "NORMALIZED_NAME"
        if not matches and target.naver_store_name:
            naver_key = normalize_store_name(target.naver_store_name, brand)
            matches = source_index.get(naver_key, [])
            match_method = "NAVER_NORMALIZED_NAME"
        if len(matches) == 1:
            matched = matches[0]
            mappings.append(
                TradeAreaMapping(
                    brand=brand,
                    db_store_name=target.store_name,
                    place_id=target.place_id,
                    pdf_store_name=matched.store_name,
                    trade_area_type=matched.trade_area_type,
                    match_status="MATCHED",
                    match_method=match_method,
                    store_code=target.store_code,
                    naver_store_name=target.naver_store_name,
                )
            )
        else:
            mappings.append(
                TradeAreaMapping(
                    brand=brand,
                    db_store_name=target.store_name,
                    place_id=target.place_id,
                    pdf_store_name=None,
                    trade_area_type=None,
                    match_status="AMBIGUOUS" if matches else "UNMATCHED",
                    match_method=None,
                    store_code=target.store_code,
                    naver_store_name=target.naver_store_name,
                )
            )
    return mappings


def build_mapping_document(
    source_pdf: str,
    source_view: str,
    mappings: Iterable[TradeAreaMapping],
) -> dict[str, object]:
    rows = list(mappings)
    return {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {"pdf": source_pdf, "database_view": source_view},
        "summary": {
            "total_db_stores": len(rows),
            "matched": sum(row.match_status == "MATCHED" for row in rows),
            "ambiguous": sum(row.match_status == "AMBIGUOUS" for row in rows),
            "unmatched": sum(row.match_status == "UNMATCHED" for row in rows),
            "missing_place_id": sum(not row.place_id for row in rows),
        },
        "stores": [row.to_dict() for row in rows],
    }


def load_pdf_trade_areas(path: str | Path) -> list[PdfTradeArea]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [PdfTradeArea(row["store_name"], row["trade_area_type"]) for row in payload["rows"]]


def write_mapping_document(path: str | Path, document: dict[str, object]) -> None:
    Path(path).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
