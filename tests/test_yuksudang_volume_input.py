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


def test_extractor_returns_three_keyword_slots(tmp_path: Path):
    output = tmp_path / "input.json"

    subprocess.run(
        [
            str(NODE),
            "scripts/node/extract_yuksudang_keywords.mjs",
            "--input",
            str(SOURCE),
            "--output",
            str(output),
            "--store",
            "육수당 문래SK점",
        ],
        check=True,
    )

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["stores"][0]["store_name"] == "육수당 문래SK점"
    assert [
        item["keyword"] for item in data["stores"][0]["keywords"]
    ] == ["문래동", "문래역", "문래 SK V1 center"]


def test_extractor_rejects_unknown_store(tmp_path: Path):
    output = tmp_path / "input.json"

    completed = subprocess.run(
        [
            str(NODE),
            "scripts/node/extract_yuksudang_keywords.mjs",
            "--input",
            str(SOURCE),
            "--output",
            str(output),
            "--store",
            "존재하지 않는 매장",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode != 0
    assert "store not found" in completed.stderr
