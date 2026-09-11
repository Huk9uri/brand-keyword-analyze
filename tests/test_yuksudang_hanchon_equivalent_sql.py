from pathlib import Path


FILES = sorted(Path("sql/yuksudang_hanchon_equivalent").glob("0[12]_*.sql"))
SQL = "\n".join(p.read_text(encoding="utf-8") for p in FILES)


def test_two_hanchon_equivalent_queries_exist():
    assert len(FILES) == 2


def test_yuksudang_sources_codes_and_menu_ids():
    for token in ("FRZIYF", "YKSD", "CD_CORP='02'", "CD_BRAND='002'", "000000027081", "midaworks.dbo.v_yksd_pos_sale"):
        assert token in SQL
    assert "FT1490" not in SQL and "HC1001" not in SQL and "000000028893" not in SQL


def test_channel_is_acorn_mapping_not_prefix_guess():
    assert "MAX(channel) channel" in SQL
    assert "LIKE 'Y%'" not in SQL
    assert "미매핑" in SQL


def test_calendar_is_cte():
    assert "event_calendar AS" in SQL
    assert "#cal" not in SQL
