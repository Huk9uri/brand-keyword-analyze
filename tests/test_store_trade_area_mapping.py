from scripts.store_trade_area_mapping import (
    PdfTradeArea,
    StoreTarget,
    build_mapping_document,
    load_pdf_trade_areas,
    write_mapping_document,
    map_trade_areas,
    normalize_store_name,
)


def test_normalize_store_name_removes_brand_spacing_and_branch_suffix():
    assert normalize_store_name("한촌설렁탕 선릉역점", "한촌설렁탕") == "선릉역"
    assert normalize_store_name("한촌 설렁탕  선릉역 지점", "한촌설렁탕") == "선릉역"


def test_map_trade_areas_matches_unique_normalized_name():
    targets = [StoreTarget("한촌설렁탕 선릉역점", "31076466")]
    source_rows = [PdfTradeArea("한촌설렁탕 선릉역점", "주거복합")]

    result = map_trade_areas("한촌설렁탕", targets, source_rows)

    assert result[0].match_status == "MATCHED"
    assert result[0].match_method == "NORMALIZED_NAME"
    assert result[0].trade_area_type == "주거복합"


def test_map_trade_areas_does_not_guess_ambiguous_normalized_name():
    targets = [StoreTarget("한촌설렁탕 중앙점", "1")]
    source_rows = [
        PdfTradeArea("한촌설렁탕 중앙점", "오피스"),
        PdfTradeArea("한촌설렁탕 중앙지점", "주거복합"),
    ]

    result = map_trade_areas("한촌설렁탕", targets, source_rows)

    assert result[0].match_status == "AMBIGUOUS"
    assert result[0].trade_area_type is None


def test_map_trade_areas_keeps_unmatched_database_store():
    targets = [StoreTarget("한촌설렁탕 신규점", "999")]

    result = map_trade_areas("한촌설렁탕", targets, [])

    assert result[0].match_status == "UNMATCHED"
    assert result[0].place_id == "999"


def test_map_trade_areas_falls_back_to_unique_naver_store_name():
    targets = [StoreTarget("성남태평점", "1414337460", naver_store_name="한촌설렁탕 성남점")]
    source_rows = [PdfTradeArea("한촌설렁탕 성남점", "주거밀집")]

    result = map_trade_areas("한촌설렁탕", targets, source_rows)

    assert result[0].match_status == "MATCHED"
    assert result[0].match_method == "NAVER_NORMALIZED_NAME"


def test_map_trade_areas_applies_explicit_manual_alias():
    targets = [StoreTarget("강동점", "11627699")]
    source_rows = [PdfTradeArea("한촌설렁탕 강동명일점", "주거복합")]

    result = map_trade_areas(
        "한촌설렁탕",
        targets,
        source_rows,
        manual_aliases={"강동점": "한촌설렁탕 강동명일점"},
    )

    assert result[0].match_status == "MATCHED"
    assert result[0].match_method == "MANUAL_ALIAS"
    assert result[0].pdf_store_name == "한촌설렁탕 강동명일점"


def test_build_mapping_document_summarizes_match_results():
    mappings = map_trade_areas(
        "한촌설렁탕",
        [StoreTarget("한촌설렁탕 선릉역점", "31076466"), StoreTarget("신규점", "")],
        [PdfTradeArea("한촌설렁탕 선릉역점", "주거복합")],
    )

    document = build_mapping_document("매장별_상권.pdf", "vw_naver_store_hours_targets", mappings)

    assert document["summary"] == {
        "total_db_stores": 2,
        "matched": 1,
        "ambiguous": 0,
        "unmatched": 1,
        "missing_place_id": 1,
    }
    assert len(document["stores"]) == 2


def test_source_rows_and_output_document_round_trip_as_utf8_json(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(
        '{"rows":[{"store_name":"한촌설렁탕 선릉역점","trade_area_type":"주거복합"}]}',
        encoding="utf-8",
    )
    output = tmp_path / "output.json"

    rows = load_pdf_trade_areas(source)
    write_mapping_document(output, {"stores": [{"db_store_name": rows[0].store_name}]})

    assert "한촌설렁탕 선릉역점" in output.read_text(encoding="utf-8")
