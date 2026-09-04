from scripts.keyword_candidate_discovery.external_source import external_keywords_from_rows


def test_external_rows_are_normalized_and_blank_keywords_are_skipped():
    rows = [
        {"brand_code": "01", "place_id": "p1", "keyword": " 설렁탕 ", "source": "MENU", "category": "MENU"},
        {"brand_code": "01", "place_id": "p1", "keyword": "", "source": "OPERATION", "category": "MENU"},
    ]

    keywords = external_keywords_from_rows(rows)

    assert len(keywords) == 1
    assert keywords[0].brand_code == "1"
    assert keywords[0].normalized_keyword == "설렁탕"
    assert keywords[0].from_menu
