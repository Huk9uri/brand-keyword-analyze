import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from yuksudang_volume.config import NaverConfig
from yuksudang_volume.datalab import DataLabClient
from yuksudang_volume.pipeline import run_pipeline
from yuksudang_volume.searchad import SearchAdClient, normalize_keyword

ROOT = Path(__file__).resolve().parents[1]
NODE = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
DEFAULT_INPUT = ROOT / "inputs/keyword_input.xlsx"


def parse_args():
    parser = argparse.ArgumentParser(description="표준 엑셀 기반 매장별 키워드 검색량 산출")
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--store")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--now", type=datetime.fromisoformat, default=datetime.now(), help=argparse.SUPPRESS)
    return parser.parse_args()


def output_dir(now: datetime) -> Path:
    base = ROOT / "outputs" / now.strftime("%Y%m%d_%H%M%S")
    candidate, suffix = base, 1
    while candidate.exists():
        candidate = Path(f"{base}_{suffix:02d}")
        suffix += 1
    return candidate


def run_node(script: str, arguments: list[str]):
    subprocess.run([str(NODE), str(ROOT / script), *arguments], cwd=ROOT, check=True)


def main():
    args = parse_args()
    if not DEFAULT_INPUT.is_file():
        raise FileNotFoundError(f"input workbook not found: {DEFAULT_INPUT}")
    target = output_dir(args.now)
    target.mkdir(parents=True)
    input_json = target / "input_keywords.json"
    extract_args = ["--input", str(DEFAULT_INPUT), "--output", str(input_json)]
    if args.store: extract_args += ["--store", args.store]
    run_node("scripts/node/extract_keyword_input.mjs", extract_args)
    payload = json.loads(input_json.read_text(encoding="utf-8"))
    stores = payload["stores"]
    slots = [item for store in stores for item in store["keywords"]]
    unique = {normalize_keyword(item["keyword"]) for item in slots}
    start = args.end_date - timedelta(days=29)
    relative_input = DEFAULT_INPUT.relative_to(ROOT)
    if args.dry_run:
        print(f"dry_run=true input={relative_input} stores={len(stores)} keyword_slots={len(slots)} unique_keywords={len(unique)} period={start}..{args.end_date} output_dir={target}")
        return
    config = NaverConfig.from_env_file(ROOT / ".env")
    result = run_pipeline(payload, SearchAdClient(config), DataLabClient(config), start, args.end_date, target / ".cache", force_refresh=args.force_refresh)
    results_json = target / "daily_volume_results.json"
    results_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result_xlsx = target / f"매장별_키워드_30일_일간검색량_{args.end_date}.xlsx"
    run_node("scripts/node/build_yuksudang_volume_workbook.mjs", ["--input", str(DEFAULT_INPUT), "--results", str(results_json), "--output", str(result_xlsx), "--preview-dir", str(target / "previews")])
    summary = result["summary"]
    print(f"stores={summary['stores']} success_keywords={summary['success_keywords']} failed_keywords={summary['failed_keywords']} daily_rows={summary['daily_rows']} output_dir={target} result_xlsx={result_xlsx}")


if __name__ == "__main__":
    try: main()
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
