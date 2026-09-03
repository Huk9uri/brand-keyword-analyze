from pathlib import Path

from scripts.keyword_discovery_rank.models import SearchPage
from scripts.keyword_discovery_rank.parser import PARSER_VERSION, DomResultParser


FIXTURES = Path(__file__).parent / "fixtures" / "keyword_discovery_rank"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parser_extracts_mixed_organic_and_ad_cards_in_screen_order():
    page = SearchPage(
        "https://m.search.naver.com/search.naver?query=test",
        fixture("mixed_results.html"),
        "RESULTS",
        4,
        True,
    )

    parsed = DomResultParser().parse(page)

    assert PARSER_VERSION == "dom-v2"
    assert [row.raw_position for row in parsed.results] == [1, 2, 3, 4]
    assert [row.organic_rank for row in parsed.results] == [1, None, 2, 3]
    assert [row.place_id for row in parsed.results] == ["1001", "9001", "1002", "1003"]
    assert [row.place_name for row in parsed.results] == [
        "육수당 선릉점",
        "서울국밥 광고점",
        "국밥마을",
        "진한설렁탕",
    ]
    assert [row.category for row in parsed.results] == ["국밥", "한식", "순대,순댓국", None]
    assert [row.is_ad for row in parsed.results] == [False, True, False, False]
    assert [row.detail_url for row in parsed.results] == [
        "https://m.place.naver.com/restaurant/1001",
        "https://m.place.naver.com/restaurant/9001",
        "https://m.place.naver.com/restaurant/1002",
        "https://m.place.naver.com/restaurant/1003",
    ]
    assert [row.distance_text for row in parsed.results] == ["120m", "350m", "0.8km", None]
    assert (parsed.observed_result_count, parsed.result_end_reached) == (4, True)


def test_parser_preserves_malformed_cards_for_validator_and_rendered_count():
    page = SearchPage("https://example.test", fixture("partial_results.html"), "RESULTS", 5, True)

    parsed = DomResultParser().parse(page)

    assert len(parsed.results) == 3
    assert [row.raw_position for row in parsed.results] == [1, 2, 3]
    assert [row.organic_rank for row in parsed.results] == [1, 2, 3]
    assert parsed.results[1].place_id == ""
    assert parsed.results[2].place_name == ""
    assert parsed.observed_result_count == 5


def test_parser_returns_empty_search_for_explicit_no_result_page():
    page = SearchPage("https://example.test", "<p>검색결과가 없습니다.</p>", "NO_RESULT", 0, True)

    parsed = DomResultParser().parse(page)

    assert parsed.results == ()
    assert (parsed.observed_result_count, parsed.result_end_reached) == (0, True)


def test_parser_prefers_nonblank_detail_anchor_after_name_only_anchor():
    page = SearchPage(
        "https://example.test",
        """
        <li data-naver-place-card>
          <a data-place-name>이름 전용 매장 링크</a>
          <a data-place-detail href="https://m.place.naver.com/restaurant/123">상세 보기</a>
        </li>
        """,
        "RESULTS",
        1,
        True,
    )

    parsed = DomResultParser().parse(page)

    assert parsed.results[0].place_name == "이름 전용 매장 링크"
    assert parsed.results[0].detail_url == "https://m.place.naver.com/restaurant/123"
    assert parsed.results[0].place_id == "123"


def test_parser_extracts_supplied_live_mobile_ad_and_organic_cards():
    page = SearchPage(
        "https://m.search.naver.com/search.naver?query=test",
        fixture("live_mobile_mixed_results.html"),
        "RESULTS",
        2,
        False,
    )

    parsed = DomResultParser().parse(page)

    assert PARSER_VERSION == "dom-v2"
    assert [row.raw_position for row in parsed.results] == [1, 2]
    assert [row.organic_rank for row in parsed.results] == [None, 1]
    assert [row.place_id for row in parsed.results] == ["2089542025", "13149768"]
    assert [row.place_name for row in parsed.results] == ["남도창평국밥", "농민백암순대 본점"]
    assert [row.category for row in parsed.results] == ["한식", "순대,순댓국"]
    assert [row.is_ad for row in parsed.results] == [True, False]
    assert [row.detail_url for row in parsed.results] == [
        "https://m.place.naver.com/restaurant/2089542025",
        "https://m.place.naver.com/restaurant/13149768",
    ]
    assert all("ader.naver.com" not in row.detail_url for row in parsed.results)
