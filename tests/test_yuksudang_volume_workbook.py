import json
import subprocess
from pathlib import Path


NODE = (
    Path.home()
    / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
)
SOURCE = Path(
    r"C:\Users\user1\Downloads\육수당_매장별 대표키워드 적용 5가지 산출 (1).xlsx"
)


def test_builder_creates_result_workbook_and_previews(tmp_path: Path):
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps(
            {
                "metadata": {
                    "source_file": str(SOURCE),
                    "period_start": "2026-08-03",
                    "period_end": "2026-09-01",
                    "collected_at": "2026-09-01T12:00:00+09:00",
                    "model_version": "v1",
                },
                "summary": {
                    "stores": 1,
                    "keyword_slots": 1,
                    "success_keywords": 1,
                    "failed_keywords": 0,
                    "daily_rows": 1,
                },
                "keywords": [
                    {
                        "store_name": "육수당 문래SK점",
                        "slot": "keyword1",
                        "keyword": "문래동",
                        "monthly_pc": 30,
                        "monthly_mobile": 60,
                        "monthly_total": 90,
                        "raw_pc": 30,
                        "raw_mobile": 60,
                        "estimated_total": 90,
                        "daily_average": 3.0,
                        "peak_date": "2026-08-03",
                        "peak_volume": 3,
                        "ratio_sum": 30.0,
                        "status": "success",
                        "error_reason": "",
                    }
                ],
                "daily_rows": [
                    {
                        "store_name": "육수당 문래SK점",
                        "slot": "keyword1",
                        "keyword": "문래동",
                        "search_date": "2026-08-03",
                        "monthly_pc": 30,
                        "monthly_mobile": 60,
                        "monthly_total": 90,
                        "ratio": 1.0,
                        "estimated_pc": 1,
                        "estimated_mobile": 2,
                        "estimated_total": 3,
                        "status": "success",
                        "error_reason": "",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "result.xlsx"
    preview_dir = tmp_path / "preview"

    subprocess.run(
        [
            str(NODE),
            "scripts/node/build_yuksudang_volume_workbook.mjs",
            "--input",
            str(SOURCE),
            "--results",
            str(results),
            "--output",
            str(output),
            "--preview-dir",
            str(preview_dir),
        ],
        check=True,
    )

    assert output.exists() and output.stat().st_size > 0
    assert (preview_dir / "summary.png").is_file()
    assert (preview_dir / "daily.png").is_file()
