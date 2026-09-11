from pathlib import Path


SQL = Path("sql/yuksudang_summer_event_analysis.sql")


def test_query_uses_only_validated_source_databases():
    text = SQL.read_text(encoding="utf-8")
    assert "SKYPOS.dbo.T_POS_SALE_CMDT" in text
    assert "SEIERP_HD.dbo.FROP_STORE" in text
    assert "SEIERP_HD.dbo.FRMI_MENULINKCODE" in text
    assert "SEIERP_HD.dbo.BSIT_ITEM" in text
    assert "IYN_PromotionDB.dbo.T_PROMO_STORE_CLASSIFICATION" in text
    assert "midaworks" not in text.lower()


def test_query_contains_yuksudang_codes_and_safe_net_sales_formula():
    text = SQL.read_text(encoding="utf-8")
    for token in ("FRZIYF", "YKSD", "gubun='02'", "CD_CORP='02'", "CD_BRAND='002'"):
        assert token in text
    assert "SC_AMT_TTL - ISNULL(p.SC_ADD_AMT,0)" in text


def test_query_has_five_year_and_2026_sections():
    text = SQL.read_text(encoding="utf-8")
    assert "[결과 1]" in text
    assert "[결과 2]" in text
    assert "2022-07-01" in text
    assert "2026-08-16" in text
    assert "기준선" in text and "사전행사" in text and "본행사" in text
