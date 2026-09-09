from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymssql
from dotenv import dotenv_values

from .batch import load_batch_plan, run_batch_plan
from .extractor import RuleBasedExtractor
from .models import AnalysisWindow
from .repository import CandidateRepository
from .review_source import ReviewRepository
from .searchad_source import SearchAdRelatedClient


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="매장별 키워드 후보 일괄 발굴")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--expand-searchad", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_false", dest="dry_run")
    mode.add_argument("--dry-run", action="store_true", dest="dry_run")
    parser.set_defaults(dry_run=True)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    plan = load_batch_plan(args.input)
    values = {key: value for key, value in dotenv_values(args.env_file).items() if value is not None}
    required = (
        "DB_SERVER", "DB_PORT", "KEYWORD_DISCOVERY_DB_DATABASE",
        "KEYWORD_DISCOVERY_DB_USER", "KEYWORD_DISCOVERY_DB_PASSWORD",
    )
    missing = [key for key in required if not str(values.get(key, "")).strip()]
    if missing:
        raise SystemExit("missing environment keys: " + ", ".join(missing))

    related_keywords: tuple[str, ...] = ()
    if args.expand_searchad:
        searchad_keys = (
            "NAVER_SEARCHAD_CUSTOMER_ID", "NAVER_SEARCHAD_API_KEY", "NAVER_SEARCHAD_SECRET_KEY",
        )
        missing = [key for key in searchad_keys if not str(values.get(key, "")).strip()]
        if missing:
            raise SystemExit("missing SearchAd environment keys: " + ", ".join(missing))
        related_keywords = SearchAdRelatedClient(
            *(values[key] for key in searchad_keys)
        ).fetch_related(plan.brand_menus)

    connection = pymssql.connect(
        server=values["DB_SERVER"],
        port=values["DB_PORT"],
        database=values["KEYWORD_DISCOVERY_DB_DATABASE"],
        user=values["KEYWORD_DISCOVERY_DB_USER"],
        password=values["KEYWORD_DISCOVERY_DB_PASSWORD"],
        encryption=(
            "require"
            if str(values.get("DB_ENCRYPT", "true")).lower() in {"1", "true", "yes", "on"}
            else None
        ),
        autocommit=False,
        use_datetime2=True,
    )
    try:
        window = AnalysisWindow(plan.as_of, plan.months)
        summaries = run_batch_plan(
            plan,
            ReviewRepository(connection),
            RuleBasedExtractor(window),
            CandidateRepository(connection),
            related_keywords=related_keywords,
            dry_run=args.dry_run,
        )
        result = {
            "brand_code": plan.brand_code,
            "brand_menus": plan.brand_menus,
            "related_keyword_count": len(related_keywords),
            "store_count": len(plan.stores),
            "dry_run": args.dry_run,
            "stores": summaries,
        }
        print(json.dumps(result, ensure_ascii=False, default=str, sort_keys=True))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
