import json
import subprocess
from pathlib import Path

NODE = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"


def test_extracts_and_deduplicates_up_to_five_keywords(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    output = tmp_path / "input.json"
    subprocess.run([str(NODE), "tests/fixtures/build_keyword_input_fixture.mjs", str(source)], check=True)
    subprocess.run([str(NODE), "scripts/node/extract_keyword_input.mjs", "--input", str(source), "--output", str(output)], check=True)
    store = json.loads(output.read_text(encoding="utf-8"))["stores"][0]
    assert store["keywords"] == [
        {"slot": "keyword1", "keyword": "갈비탕"},
        {"slot": "keyword2", "keyword": "해장"},
        {"slot": "keyword5", "keyword": "혼밥"},
    ]


def test_validation_rejects_invalid_workbooks(tmp_path: Path):
    cases = [
        ("missing_sheet", "sheet not found: 키워드입력"),
        ("missing_store_header", "missing required header: 매장명"),
        ("missing_keyword1_header", "missing required header: 키워드1"),
        ("keyword6_header", "앵커 키워드 기반 별도 모델"),
        ("duplicate_store", "duplicate store name"),
        ("no_keywords", "at least one keyword is required"),
        ("orphan_values", "store name is required"),
        ("example_row", "예시 행을 삭제"),
    ]
    for scenario, message in cases:
        source = tmp_path / f"{scenario}.xlsx"
        output = tmp_path / f"{scenario}.json"
        subprocess.run(
            [str(NODE), "tests/fixtures/build_keyword_input_fixture.mjs", str(source), scenario],
            check=True,
        )
        completed = subprocess.run(
            [str(NODE), "scripts/node/extract_keyword_input.mjs", "--input", str(source), "--output", str(output)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert completed.returncode != 0, scenario
        assert message in completed.stderr, scenario
        assert not output.exists(), scenario
