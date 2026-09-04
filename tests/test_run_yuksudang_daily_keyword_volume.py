import subprocess
from pathlib import Path


PYTHON = Path(__file__).parents[1] / ".venv/Scripts/python.exe"
SOURCE = Path(
    r"C:\Users\user1\Downloads\육수당_매장별 대표키워드 적용 5가지 산출 (1).xlsx"
)
FINAL_SETUP_SOURCE = Path(
    r"C:\Users\user1\Documents\카카오톡 받은 파일\26년 2분기 네이버플레이스 키워드 셋업 (3).xlsx"
)


def test_cli_dry_run_does_not_print_secrets(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NAVER_SEARCHAD_CUSTOMER_ID=123\n"
        "NAVER_SEARCHAD_API_KEY=license-value\n"
        "NAVER_SEARCHAD_SECRET_KEY=search-secret\n"
        "NAVER_DATALAB_CLIENT_ID=client-value\n"
        "NAVER_DATALAB_CLIENT_SECRET=client-secret-value\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(PYTHON),
            "scripts/run_yuksudang_daily_keyword_volume.py",
            "--input",
            str(SOURCE),
            "--store",
            "육수당 문래SK점",
            "--end-date",
            "2026-09-01",
            "--env-file",
            str(env_file),
            "--output-dir",
            str(tmp_path / "output"),
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert "stores=1" in completed.stdout
    assert "keyword_slots=3" in completed.stdout
    assert "unique_keywords=3" in completed.stdout
    assert "license-value" not in completed.stdout
    assert "search-secret" not in completed.stdout
    assert "client-secret-value" not in completed.stdout


def test_cli_dry_run_supports_final_setup_sheet(tmp_path: Path):
    completed = subprocess.run(
        [
            str(PYTHON),
            "scripts/run_yuksudang_daily_keyword_volume.py",
            "--input",
            str(FINAL_SETUP_SOURCE),
            "--sheet",
            "운영팀 최종 수정본 키워드",
            "--keyword-prefix",
            "대표키워드",
            "--end-date",
            "2026-09-01",
            "--env-file",
            str(Path(__file__).parents[1] / ".env"),
            "--output-dir",
            str(tmp_path / "output"),
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert "stores=136" in completed.stdout
    assert "keyword_slots=680" in completed.stdout
