from pathlib import Path


SQL = Path("sql/yuksudang_hanchon_equivalent/03_2026_menu_cannibalization.sql").read_text(encoding="utf-8")


def test_cannibalization_uses_acorn_channel_and_erp_menu_mapping():
    for token in ("midaworks.dbo.v_yksd_pos_sale", "a.channel", "SEIERP_HD.dbo.FRMI_MENULINKCODE"):
        assert token in SQL


def test_target_comparison_and_periods_are_explicit():
    for token in ("000000027081", "000000029748", "기준선", "사전행사", "본행사"):
        assert token in SQL


def test_comparable_cohort_and_noncausal_labels_exist():
    assert "COUNT(DISTINCT 구간)=3" in SQL
    for label in ("강한 대체 징후", "부분 대체 징후", "증분 성장"):
        assert label in SQL
