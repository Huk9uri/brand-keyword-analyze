from pathlib import Path


SQL_DIR = Path("sql/yuksudang_delivery_tip")
FILES = sorted(SQL_DIR.glob("*.sql"))


def read_sql() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in FILES)


def test_nine_queries_cover_design_snapshot_and_all_store_analysis():
    assert [path.name[:2] for path in FILES] == [f"{n:02d}" for n in range(1, 10)]


def test_store_mapping_uses_yuksudang_erp_and_delivery_sources():
    sql = read_sql()
    assert "SEIERP_HD.dbo.FROP_STORE" in sql
    assert "CD_CORP = '02'" in sql
    assert "yuksudang_delivery.dbo.channel_group_store_info" in sql
    assert "yuksudang_delivery.dbo.bae_shop" in sql
    assert "yuksudang_delivery.dbo.eat_shop" in sql
    assert "hanchon_delivery" not in sql


def test_store_mapping_normalizes_actual_platform_app_type_values():
    sql = (SQL_DIR / "01_store_mapping_diagnostic.sql").read_text(encoding="utf-8")
    assert "WHEN app_type = 'Baemin' THEN 'BAE'" in sql
    assert "WHEN app_type = 'CoupangEats' THEN 'EAT'" in sql


def test_platform_queries_preserve_raw_fee_text_and_remove_duplicate_snapshots():
    sql = read_sql()
    for table in (
        "bae_rank_rival",
        "bae_rank_rival_delivery_tip_by_order_amount",
        "bae_rank_rival_delivery_tip_by_region",
        "bae_rank_rival_delivery_tip_by_etc",
        "eat_rank_rival",
        "eat_rank_rival_delivery_fee_info",
    ):
        assert f"yuksudang_delivery.dbo.{table}" in sql
    assert "SELECT DISTINCT" in sql
    assert "raw_text" in sql
    assert "parse_status" in sql


def test_scenarios_and_final_metrics_are_defined():
    sql = read_sql()
    for amount in (15000, 20000, 25000, 30000):
        assert str(amount) in sql
    for metric in (
        "competitor_median_fee",
        "competitor_p25_fee",
        "competitor_p75_fee",
        "fee_gap",
        "own_fee_percentile",
        "free_delivery_ratio",
        "cheaper_competitor_ratio",
        "priority_score",
    ):
        assert metric in sql


def test_unknown_fee_patterns_remain_explicitly_unparsed():
    sql = read_sql()
    assert "FAILED" in sql
    assert "TRY_CONVERT" in sql
    assert "COALESCE(delivery_fee, 0)" not in sql


def test_snapshot_analysis_filters_verified_own_brand_and_emits_quality_outputs():
    sql = (SQL_DIR / "08_latest_snapshot_analysis.sql").read_text(encoding="utf-8")
    assert "2026-08-20" in sql
    assert "LIKE N'%육수당%'" in sql
    for output in (
        "SUMMARY_KPI",
        "STORE_PRIORITY",
        "EXCLUDED_OWN_LISTING",
        "PARSE_QUALITY",
    ):
        assert output in sql


def test_all_store_analysis_supports_bounded_and_open_ended_fee_ranges():
    sql = (SQL_DIR / "09_all_store_sheet_dataset.sql").read_text(encoding="utf-8")
    for token in (
        "RANGE_EXCLUSIVE",
        "LOWER_OPEN",
        "order_amount_min",
        "order_amount_max",
        "AMBIGUOUS_OVERLAP",
        "NO_APPLICABLE_RANGE",
    ):
        assert token in sql


def test_all_store_analysis_uses_yuksudang_20k_representative_band():
    sql = (SQL_DIR / "09_all_store_sheet_dataset.sql").read_text(encoding="utf-8")
    assert "pay_amount>=15000 AND pay_amount<25000" in sql
    assert "pay_amount>=20000 AND pay_amount<30000" not in sql
