from datetime import date

from scripts.keyword_candidate_discovery.cli import parse_args


def test_cli_defaults_to_dry_run_and_twelve_month_window():
    args = parse_args(["--brand-code", "01", "--as-of", "2026-09-04"])

    assert args.brand_code == "01"
    assert args.as_of == date(2026, 9, 4)
    assert args.months == 12
    assert args.dry_run


def test_cli_requires_explicit_write_flag_for_persistence():
    args = parse_args(["--brand-code", "1", "--as-of", "2026-09-04", "--write"])

    assert not args.dry_run


def test_cli_accepts_target_place_scope():
    args = parse_args([
        "--brand-code", "1", "--as-of", "2026-09-04",
        "--target-place-id", "31076466",
    ])

    assert args.target_place_id == "31076466"
