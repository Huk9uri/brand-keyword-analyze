import json
from pathlib import Path

from scripts.yuksudang_volume.searchad import (
    build_hint_keywords,
    build_signature,
    normalize_keyword,
    parse_keyword_rows,
)


def _fixture() -> dict:
    return json.loads(
        Path(
            "tests/fixtures/yuksudang_volume/searchad_keywordstool.json"
        ).read_text(encoding="utf-8")
    )


def test_build_signature_is_stable():
    assert build_signature(
        "1700000000000",
        "GET",
        "/keywordstool",
        "secret",
    ) == "A6Gzu+sW9C2ovLsH+T+rFrie81KwHy1xrodUFQERKf4="


def test_normalize_keyword_removes_all_whitespace_and_case():
    assert normalize_keyword(" 문래 SK\tV1 Center ") == "문래skv1center"


def test_build_hint_keywords_removes_invalid_whitespace():
    assert build_hint_keywords(
        ["문래동", "문래역", "문래 SK V1 center"]
    ) == "문래동,문래역,문래skv1center"


def test_parse_keyword_rows_preserves_low_volume_state():
    rows = parse_keyword_rows(_fixture(), ["문래동", "문래 SK V1 center"])

    assert rows["문래동"].pc == 4560
    assert rows["문래동"].mobile == 15300
    assert rows["문래동"].status == "success"
    assert rows["문래 SK V1 center"].pc is None
    assert rows["문래 SK V1 center"].mobile == 100
    assert rows["문래 SK V1 center"].status == "searchad_low_volume"


def test_parse_keyword_rows_marks_missing_exact_keyword():
    rows = parse_keyword_rows(_fixture(), ["없는키워드"])

    assert rows["없는키워드"].status == "searchad_no_data"
    assert rows["없는키워드"].pc is None
    assert rows["없는키워드"].mobile is None
