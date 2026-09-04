import json
from pathlib import Path

import pytest

from scripts.place_keyword_collector.parser import (
    KeywordListParseError,
    KeywordListParser,
    PlaceMismatchError,
    normalize_keyword,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "place_keyword_collector"


def fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def serialized_payload(payload: object, layers: int) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for _ in range(layers):
        encoded = json.dumps(encoded, ensure_ascii=False)
    return f"<script>{encoded}</script>"


def test_parser_extracts_target_keyword_list_in_original_order():
    parsed = KeywordListParser().parse(fixture("keyword_list.html"), "13149768")
    assert [item.raw_keyword for item in parsed.keywords] == ["순대", "순댓국", "국밥", "수육"]
    assert [item.keyword_order for item in parsed.keywords] == [1, 2, 3, 4]


def test_parser_does_not_take_keyword_list_from_another_place():
    with pytest.raises(PlaceMismatchError):
        KeywordListParser().parse(fixture("wrong_place_object.html"), "13149768")


def test_parser_accepts_a_definitive_empty_array():
    parsed = KeywordListParser().parse(fixture("empty_keyword_list.html"), "13149768")
    assert parsed.place_id == "13149768"
    assert parsed.keywords == ()


def test_parser_distinguishes_missing_keyword_list_from_empty_array():
    with pytest.raises(KeywordListParseError) as caught:
        KeywordListParser().parse(fixture("missing_keyword_list.html"), "13149768")
    assert type(caught.value) is KeywordListParseError


def test_parser_requires_id_and_keyword_list_on_the_same_object():
    html = """
    <script type="application/json">
      {"places":[{"id":"13149768"},{"id":"99999999","keywordList":["wrong"]}]}
    </script>
    """
    with pytest.raises(PlaceMismatchError):
        KeywordListParser().parse(html, "13149768")


def test_parser_decodes_serialized_json_and_preserves_raw_values():
    html = r'''<script>window.x = JSON.parse("{\"place\":{\"id\":\"13149768\",\"keywordList\":[\"  ABC　Store  \",\"\",\"abc store\",\"순대\"]}}");</script>'''
    parsed = KeywordListParser().parse(html, "13149768")
    assert [
        (item.keyword_order, item.raw_keyword, item.normalized_keyword)
        for item in parsed.keywords
    ] == [(1, "  ABC　Store  ", "abc store"), (4, "순대", "순대")]


@pytest.mark.parametrize("layers", [0, 1])
def test_parser_preserves_html_entity_text_inside_json_keywords(layers: int):
    html = serialized_payload(
        {"place": {"id": "13149768", "keywordList": ["R&amp;D", "A&quot;B"]}},
        layers,
    )

    parsed = KeywordListParser().parse(html, "13149768")

    assert [item.raw_keyword for item in parsed.keywords] == ["R&amp;D", "A&quot;B"]
    assert [item.normalized_keyword for item in parsed.keywords] == [
        "r&amp;d",
        "a&quot;b",
    ]


def test_parser_decodes_quote_entities_only_when_needed_for_json_structure():
    html = """
    <script>
      {&quot;place&quot;:{&quot;id&quot;:&quot;13149768&quot;,
      &quot;keywordList&quot;:[&quot;R&amp;D&quot;]}}
    </script>
    """

    parsed = KeywordListParser().parse(html, "13149768")

    assert parsed.keywords[0].raw_keyword == "R&amp;D"


def test_parser_accepts_at_most_four_serialized_string_layers():
    payload = {"place": {"id": "13149768", "keywordList": ["순대"]}}

    parsed = KeywordListParser().parse(serialized_payload(payload, 4), "13149768")

    assert [item.raw_keyword for item in parsed.keywords] == ["순대"]


def test_parser_rejects_payload_beyond_four_serialized_string_layers():
    payload = {"place": {"id": "13149768", "keywordList": ["순대"]}}

    with pytest.raises(KeywordListParseError) as caught:
        KeywordListParser().parse(serialized_payload(payload, 5), "13149768")
    assert type(caught.value) is KeywordListParseError


def test_normalize_keyword_only_applies_nfkc_whitespace_and_casefold():
    assert normalize_keyword("  ＡＢＣ\t순댓국  ") == "abc 순댓국"
