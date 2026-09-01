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
