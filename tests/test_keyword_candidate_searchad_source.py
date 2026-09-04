from scripts.keyword_candidate_discovery.searchad_source import parse_related_keywords


def test_related_keyword_rows_are_deduplicated_and_seed_is_removed():
    payload = {"keywordList": [
        {"relKeyword": "설렁탕"},
        {"relKeyword": "선릉역설렁탕"},
        {"relKeyword": "선릉역 설렁탕"},
        {"relKeyword": ""},
    ]}

    result = parse_related_keywords(payload, seed_keywords=("설렁탕",))

    assert result == ("선릉역설렁탕",)
