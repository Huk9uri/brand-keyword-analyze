from pathlib import Path


FILES = sorted(Path("sql/yuksudang_outputs").glob("*.sql"))
SQL = "\n".join(p.read_text(encoding="utf-8") for p in FILES)


def test_six_independent_outputs_exist():
    assert len(FILES) == 6
    for number in range(1, 7):
        assert FILES[number - 1].name.startswith(f"0{number}_")


def test_calendar_is_cte_and_temp_calendar_is_removed():
    assert all("event_calendar AS" in p.read_text(encoding="utf-8") for p in FILES)
    assert "#cal" not in SQL


def test_channel_comes_from_acorn_without_prefix_guessing():
    assert "midaworks.dbo.v_yksd_pos_sale" in SQL
    assert "a.channel" in SQL
    assert "LIKE 'Y%'" not in SQL
    assert "배달(추정)" not in SQL


def test_required_erp_and_pos_sources_remain():
    for token in (
        "SKYPOS.dbo.T_POS_SALE_CMDT",
        "SEIERP_HD.dbo.FROP_STORE",
        "SEIERP_HD.dbo.FROP_STORESUB",
        "SEIERP_HD.dbo.FRMI_MENULINKCODE",
        "SEIERP_HD.dbo.BSIT_ITEM",
        "SEIERP_HD.dbo.BSIT_ITEMCLASS_MDD",
        "IYN_PromotionDB.dbo.T_PROMO_STORE_CLASSIFICATION",
    ):
        assert token in SQL
