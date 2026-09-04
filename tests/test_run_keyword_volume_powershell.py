import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
NODE = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"


def test_powershell_wrapper_runs_dry_run():
    input_path = ROOT / "inputs/keyword_input.xlsx"
    input_path.parent.mkdir(exist_ok=True)
    subprocess.run([str(NODE), "tests/fixtures/build_keyword_input_fixture.mjs", str(input_path), "valid"], cwd=ROOT, check=True)
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "run_keyword_volume.ps1", "-DryRun"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
    finally:
        input_path.unlink(missing_ok=True)
    assert completed.returncode == 0
    assert "dry_run=true" in completed.stdout
