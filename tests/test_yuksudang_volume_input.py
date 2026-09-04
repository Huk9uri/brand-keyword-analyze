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
FINAL_SETUP_SOURCE = Path(
    r"C:\Users\user1\Documents\카카오톡 받은 파일\26년 2분기 네이버플레이스 키워드 셋업 (3).xlsx"
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


def test_extractor_reads_five_final_setup_keywords(tmp_path: Path):
    output = tmp_path / "input.json"

    subprocess.run(
        [
            str(NODE),
            "scripts/node/extract_yuksudang_keywords.mjs",
            "--input",
            str(FINAL_SETUP_SOURCE),
            "--output",
            str(output),
            "--sheet",
            "운영팀 최종 수정본 키워드",
            "--keyword-prefix",
            "대표키워드",
            "--store",
            "한촌설렁탕 천안쌍용점",
        ],
        check=True,
    )

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["sheet"] == "운영팀 최종 수정본 키워드"
    assert data["stores"][0]["store_name"] == "한촌설렁탕 천안쌍용점"
    assert data["stores"][0]["keywords"] == [
        {"slot": "keyword1", "keyword": "쌍용동갈비탕"},
        {"slot": "keyword2", "keyword": "봉명역혼밥"},
        {"slot": "keyword3", "keyword": "해장"},
        {"slot": "keyword4", "keyword": "갈비탕"},
        {"slot": "keyword5", "keyword": "쌍용동삼계탕"},
    ]
