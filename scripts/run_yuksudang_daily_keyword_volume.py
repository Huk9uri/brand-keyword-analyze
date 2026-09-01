import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from yuksudang_volume.config import NaverConfig
from yuksudang_volume.datalab import DataLabClient
from yuksudang_volume.pipeline import run_pipeline
from yuksudang_volume.searchad import SearchAdClient, normalize_keyword


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NODE = (
    Path.home()
    / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
)
DEFAULT_NODE_MODULES = (
    Path.home()
    / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="육수당 매장별 키워드 최근 30일 일간 검색량 추정"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--store")
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--node", type=Path, default=DEFAULT_NODE)
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def ensure_node_modules() -> None:
    target = REPO_ROOT / "node_modules"
    if target.exists():
        return
    if not DEFAULT_NODE_MODULES.is_dir():
        raise RuntimeError(f"bundled node_modules not found: {DEFAULT_NODE_MODULES}")
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(target), str(DEFAULT_NODE_MODULES)],
            check=True,
            capture_output=True,
        )
    else:
        target.symlink_to(DEFAULT_NODE_MODULES, target_is_directory=True)


def run_node(node: Path, script: Path, arguments: list[str]) -> None:
    subprocess.run(
        [str(node), str(script), *arguments],
        cwd=REPO_ROOT,
        check=True,
    )


def write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    config = NaverConfig.from_env_file(args.env_file.resolve())
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input workbook not found: {input_path}")
    if not args.node.is_file():
        raise FileNotFoundError(f"Node.js executable not found: {args.node}")

    start_date = args.end_date - timedelta(days=29)
    output_dir = (
        args.output_dir
        if args.output_dir
        else REPO_ROOT / "outputs" / f"yuksudang-volume-{args.end_date.isoformat()}"
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ensure_node_modules()

    input_json = output_dir / "input_keywords.json"
    extractor_args = [
        "--input",
        str(input_path),
        "--output",
        str(input_json),
    ]
    if args.store:
        extractor_args.extend(["--store", args.store])
    run_node(
        args.node,
        REPO_ROOT / "scripts/node/extract_yuksudang_keywords.mjs",
        extractor_args,
    )
    input_payload = json.loads(input_json.read_text(encoding="utf-8"))
    stores = input_payload["stores"]
    slots = [item for store in stores for item in store.get("keywords", [])]
    unique_keywords = {
        normalize_keyword(str(item.get("keyword") or ""))
        for item in slots
        if normalize_keyword(str(item.get("keyword") or ""))
    }

    if args.dry_run:
        print(
            "dry_run=true "
            f"stores={len(stores)} "
            f"keyword_slots={len(slots)} "
            f"unique_keywords={len(unique_keywords)} "
            f"datalab_requests={len(stores)} "
            f"period={start_date.isoformat()}..{args.end_date.isoformat()}"
        )
        return 0

    result = run_pipeline(
        input_payload,
        SearchAdClient(config),
        DataLabClient(config),
        start_date,
        args.end_date,
        output_dir / ".cache",
        force_refresh=args.force_refresh,
    )
    results_json = output_dir / "daily_volume_results.json"
    write_json_atomic(results_json, result)

    output_xlsx = output_dir / (
        f"육수당_매장별_키워드_30일_일간검색량_{args.end_date.isoformat()}.xlsx"
    )
    preview_dir = output_dir / "previews"
    run_node(
        args.node,
        REPO_ROOT / "scripts/node/build_yuksudang_volume_workbook.mjs",
        [
            "--input",
            str(input_path),
            "--results",
            str(results_json),
            "--output",
            str(output_xlsx),
            "--preview-dir",
            str(preview_dir),
        ],
    )

    summary = result["summary"]
    print(
        f"stores={summary['stores']} "
        f"success_keywords={summary['success_keywords']} "
        f"failed_keywords={summary['failed_keywords']} "
        f"daily_rows={summary['daily_rows']}"
    )
    print(f"result_json={results_json}")
    print(f"result_xlsx={output_xlsx}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
