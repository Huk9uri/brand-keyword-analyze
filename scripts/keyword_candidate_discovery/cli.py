from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import pymssql
from dotenv import dotenv_values

from .extractor import RuleBasedExtractor
from .models import AnalysisWindow, ExternalKeyword, TermCategory
from .pipeline import run_discovery
from .repository import CandidateRepository
from .review_source import ReviewRepository, normalize_brand_code
from .searchad_source import SearchAdRelatedClient


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="네이버 원문 리뷰 기반 키워드 후보 발굴")
    parser.add_argument("--brand-code", required=True)
    parser.add_argument("--place-id", default="")
    parser.add_argument("--target-place-id", default="")
    parser.add_argument("--as-of", required=True, type=_date)
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--menu", action="append", default=[])
    parser.add_argument("--brand-menu", action="append", default=[])
    parser.add_argument("--operation-keyword", action="append", default=[])
    parser.add_argument("--expand-searchad", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_false", dest="dry_run")
    mode.add_argument("--dry-run", action="store_true", dest="dry_run")
    parser.set_defaults(dry_run=True)
    args = parser.parse_args(argv)
    if args.months < 1:
        parser.error("--months must be at least 1")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    values = {key: value for key, value in dotenv_values(args.env_file).items() if value is not None}
    required = ("DB_SERVER", "DB_PORT", "KEYWORD_DISCOVERY_DB_DATABASE",
                "KEYWORD_DISCOVERY_DB_USER", "KEYWORD_DISCOVERY_DB_PASSWORD")
    missing = [key for key in required if not str(values.get(key, "")).strip()]
    if missing:
        raise SystemExit("missing environment keys: " + ", ".join(missing))
    connection = pymssql.connect(
        server=values["DB_SERVER"], port=values["DB_PORT"],
        database=values["KEYWORD_DISCOVERY_DB_DATABASE"],
        user=values["KEYWORD_DISCOVERY_DB_USER"], password=values["KEYWORD_DISCOVERY_DB_PASSWORD"],
        encryption="require" if str(values.get("DB_ENCRYPT", "true")).lower() in {"1", "true", "yes", "on"} else None,
        autocommit=False, use_datetime2=True,
    )
    try:
        brand_code = normalize_brand_code(args.brand_code)
        external = _external_keywords(args, brand_code, values)
        window = AnalysisWindow(args.as_of, args.months)
        summary = run_discovery(
            brand_code, window, ReviewRepository(connection), RuleBasedExtractor(window),
            CandidateRepository(connection), external_keywords=external,
            target_place_id=args.target_place_id or None,
            include_brand_candidates=not bool(args.target_place_id),
            dry_run=args.dry_run,
        )
        print(json.dumps(summary.__dict__, ensure_ascii=False, default=str, sort_keys=True))
        return 0
    finally:
        connection.close()


def _external_keywords(args, brand_code: str, values: dict[str, str]) -> tuple[ExternalKeyword, ...]:
    rows: list[ExternalKeyword] = []
    store_place_id = args.target_place_id or args.place_id
    rows.extend(ExternalKeyword(brand_code, keyword.strip(), TermCategory.MENU, store_place_id, from_menu=True)
                for keyword in args.menu if keyword.strip())
    rows.extend(ExternalKeyword(brand_code, keyword.strip(), TermCategory.MENU, "", from_brand_menu=True)
                for keyword in args.brand_menu if keyword.strip())
    rows.extend(ExternalKeyword(brand_code, keyword.strip(), TermCategory.UNKNOWN, store_place_id,
                                from_operation_keyword=True)
                for keyword in args.operation_keyword if keyword.strip())
    if args.expand_searchad:
        keys = ("NAVER_SEARCHAD_CUSTOMER_ID", "NAVER_SEARCHAD_API_KEY", "NAVER_SEARCHAD_SECRET_KEY")
        missing = [key for key in keys if not str(values.get(key, "")).strip()]
        if missing:
            raise SystemExit("missing SearchAd environment keys: " + ", ".join(missing))
        seeds = tuple(dict.fromkeys([*args.menu, *args.brand_menu, *args.operation_keyword]))
        client = SearchAdRelatedClient(*(values[key] for key in keys))
        rows.extend(ExternalKeyword(brand_code, keyword, TermCategory.UNKNOWN, store_place_id,
                                    from_searchad_related=True)
                    for keyword in client.fetch_related(seeds))
    return tuple(rows)


if __name__ == "__main__":
    raise SystemExit(main())
