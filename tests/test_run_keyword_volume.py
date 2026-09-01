import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
PYTHON = ROOT / ".venv/Scripts/python.exe"
NODE = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"


def test_defaults_to_canonical_input_and_timestamped_output():
    input_path = ROOT / "inputs/keyword_input.xlsx"
    input_path.parent.mkdir(exist_ok=True)
    subprocess.run([str(NODE), "tests/fixtures/build_keyword_input_fixture.mjs", str(input_path), "valid"], cwd=ROOT, check=True)
    try:
        completed = subprocess.run(
            [str(PYTHON), "scripts/run_keyword_volume.py", "--dry-run", "--end-date", "2026-09-01", "--now", "2026-09-01T12:34:56"],
            cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
        )
    finally:
        input_path.unlink(missing_ok=True)
    assert "dry_run=true" in completed.stdout
    assert "stores=1" in completed.stdout
    assert "keyword_slots=3" in completed.stdout
    assert "output_dir=" in completed.stdout
    assert "20260901_123456" in completed.stdout
