from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By

from scripts.keyword_discovery_rank.browser import (
    BrowserFactory,
    BrowserSession,
    BrowserSessionError,
    QueryMismatch,
    SearchPageError,
    SearchStateTimeout,
    _result_progress,
    detect_page_state,
    query_matches_url,
)
from scripts.keyword_discovery_rank.models import DeviceType, SearchTask, SourceType


FIXTURES = Path(__file__).parent / "fixtures" / "keyword_discovery_rank"
QUERY = "선릉역 국밥"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def result_html(count: int, *, ended: bool = False) -> str:
    cards = "".join(
        f'<li data-naver-place-card data-place-id="{index}">매장 {index}</li>'
        for index in range(1, count + 1)
    )
    end = '<p data-naver-search-end>검색 결과의 끝입니다.</p>' if ended else ""
    return f"<html><body><ul>{cards}</ul>{end}</body></html>"


@pytest.mark.parametrize("parameter", ["query", "searchText"])
def test_query_matches_url_decodes_korean_search_parameters(parameter: str):
    url = f"https://m.search.naver.com/search.naver?{parameter}=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"

    assert query_matches_url(url, QUERY)
    assert not query_matches_url(url, "강남역 국밥")


def test_detect_page_state_rejects_stale_results_before_accepting_dom():
    assert (
        detect_page_state(
            "https://m.search.naver.com/search.naver?query=previous",
            fixture("results.html"),
            QUERY,
        )
        == "QUERY_MISMATCH"
    )


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [("results.html", "RESULTS"), ("no_result.html", "NO_RESULT"), ("error.html", "ERROR")],
)
def test_detect_page_state_identifies_terminal_dom(fixture_name: str, expected: str):
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"

    assert detect_page_state(url, fixture(fixture_name), QUERY) == expected


def test_detect_page_state_ignores_error_text_in_non_visible_elements():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    html = """
    <html><body>
      <li data-naver-place-card data-place-id="1001">육수당 선릉점</li>
      <script>일시적인 오류</script>
      <style>오류가 발생했습니다</style>
      <template>서비스 접속이 원활하지 않습니다</template>
      <noscript>잠시 후 다시 시도</noscript>
    </body></html>
    """

    assert detect_page_state(url, html, QUERY) == "RESULTS"


def test_detect_page_state_ignores_error_text_in_hidden_dom_blocks():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    html = """
    <html><body>
      <div style="display: none"><strong>일시적인 오류로 정보를 표시할 수 없습니다.</strong></div>
      <div hidden>오류가 발생했습니다</div>
      <div aria-hidden="true">서비스 접속이 원활하지 않습니다</div>
      <li data-nmb_res-doc-id="13149768">농민백암순대 본점</li>
    </body></html>
    """

    assert detect_page_state(url, html, QUERY) == "RESULTS"


def test_detect_page_state_accepts_direct_place_result_as_complete_results():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89+%EC%9C%A1%EC%88%98%EB%8B%B9"
    html = fixture("direct_place_result.html")

    assert detect_page_state(url, html, "선릉 육수당") == "RESULTS"
    assert _result_progress(html) == (1, True)


def test_detect_page_state_leaves_unfinished_loading_undecided():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"

    assert detect_page_state(url, "<html><body>검색 중...</body></html>", QUERY) == "LOADING"


class FakeDriver:
    def __init__(
        self,
        pages: list[tuple[str, str]] | None = None,
        *,
        fail_on: str | None = None,
    ) -> None:
        self.pages = pages or [("about:blank", "")]
        self.page_index = 0
        self.fail_on = fail_on
        self.get_calls: list[str] = []
        self.page_load_timeouts: list[float] = []
        self.window_sizes: list[tuple[int, int]] = []
        self.cdp_calls: list[tuple[str, dict[str, float | int]]] = []
        self.script_calls: list[str] = []
        self.screenshot_paths: list[str] = []
        self.find_element_calls: list[tuple[str, str]] = []
        self.more_button = None

    @property
    def current_url(self) -> str:
        return self.pages[self.page_index][0]

    @property
    def page_source(self) -> str:
        return self.pages[self.page_index][1]

    def get(self, url: str) -> None:
        if self.fail_on == "navigation_timeout":
            raise TimeoutException("navigation timed out")
        if self.fail_on == "get":
            raise RuntimeError("browser disappeared")
        self.get_calls.append(url)

    def set_page_load_timeout(self, seconds: float) -> None:
        self.page_load_timeouts.append(seconds)

    def set_window_size(self, width: int, height: int) -> None:
        self.window_sizes.append((width, height))

    def execute_cdp_cmd(self, command: str, params: dict[str, float | int]) -> None:
        self.cdp_calls.append((command, params))

    def execute_script(self, script: str) -> None:
        if self.fail_on == "scroll":
            raise RuntimeError("scroll failed")
        self.script_calls.append(script)
        if self.page_index < len(self.pages) - 1:
            self.page_index += 1

    def find_elements(self, by: str, value: str):
        self.find_element_calls.append((by, value))
        return [] if self.more_button is None else [self.more_button]

    def save_screenshot(self, path: str) -> bool:
        if self.fail_on == "screenshot":
            raise OSError("screenshot disk failure")
        self.screenshot_paths.append(path)
        Path(path).write_bytes(b"fake-png")
        return True


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.parametrize(
    ("device_type", "viewport"),
    [(DeviceType.MOBILE, (390, 844)), (DeviceType.PC, (1440, 1000))],
)
def test_factory_sets_viewport_and_geolocation(device_type: DeviceType, viewport: tuple[int, int]):
    driver = FakeDriver()
    captured_options = []
    factory = BrowserFactory(driver_builder=lambda *, options: captured_options.append(options) or driver)

    session = factory.create(device_type, 37.5048, 127.0489)

    assert isinstance(session, BrowserSession)
    assert driver.window_sizes == [viewport]
    search_origin = (
        "https://m.search.naver.com"
        if device_type is DeviceType.MOBILE
        else "https://search.naver.com"
    )
    assert driver.cdp_calls == [
        (
            "Emulation.setGeolocationOverride",
            {"latitude": 37.5048, "longitude": 127.0489, "accuracy": 100},
        ),
        ("Browser.grantPermissions", {"origin": search_origin, "permissions": ["geolocation"]}),
    ]
    mobile_arguments = [arg for arg in captured_options[0].arguments if arg.startswith("--user-agent=")]
    assert bool(mobile_arguments) is (device_type is DeviceType.MOBILE)
    if mobile_arguments:
        assert "Android" in mobile_arguments[0] and "Mobile" in mobile_arguments[0]


def test_factory_wraps_driver_creation_failure_with_empty_context():
    def fail_to_create(*, options):
        raise RuntimeError("chrome missing")

    with pytest.raises(BrowserSessionError) as caught:
        BrowserFactory(driver_builder=fail_to_create).create(DeviceType.MOBILE, 37.5, 127.0)

    assert caught.value.last_url == ""
    assert caught.value.html == ""


def make_task(device_type: DeviceType = DeviceType.MOBILE) -> SearchTask:
    return SearchTask(
        "row-2",
        QUERY,
        "S1",
        "육수당 선릉점",
        "선릉점",
        37.5048,
        127.0489,
        SourceType.EXCEL,
        "2",
        device_type,
    )


def make_session(
    driver: FakeDriver,
    *,
    timeout_seconds: float = 2,
    result_limit: int = 20,
    clock: ManualClock | None = None,
):
    clock = clock or ManualClock()
    return BrowserSession(
        driver,
        timeout_seconds=timeout_seconds,
        result_limit=result_limit,
        poll_interval=1,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


def test_search_builds_encoded_mobile_url_and_returns_results_at_limit():
    final_url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    driver = FakeDriver([(final_url, result_html(20))])

    page = make_session(driver).search(make_task())

    requested = urlparse(driver.get_calls[0])
    assert requested.netloc == "m.search.naver.com"
    assert parse_qs(requested.query)["query"] == [QUERY]
    assert page.final_url == final_url
    assert page.html == result_html(20)
    assert (page.state, page.observed_result_count, page.result_end_reached) == ("RESULTS", 20, False)


def test_search_activates_current_location_before_accepting_results():
    url = "https://m.search.naver.com/search.naver?query=%EA%B5%AD%EB%B0%A5"
    before = '<span>위치 정보 없음</span><a id="_my_location">내위치</a>'
    after = result_html(5)

    class LocationDriver(FakeDriver):
        def __init__(self):
            super().__init__([(url, before), (url, after)])
            self.location_clicks = 0

        def find_elements(self, by: str, value: str):
            self.find_element_calls.append((by, value))
            if by == By.ID and value == "_my_location" and self.page_index == 0:
                driver = self

                class LocationButton:
                    def is_displayed(self):
                        return True

                    def is_enabled(self):
                        return True

                    def click(self):
                        driver.location_clicks += 1
                        driver.page_index = 1

                return [LocationButton()]
            return []

    driver = LocationDriver()
    page = make_session(driver, result_limit=5).search(
        SearchTask("location", "국밥", "S1", "매장", "위치", 37.5, 127.0, SourceType.EXCEL, "1")
    )

    assert driver.location_clicks == 1
    assert "위치 정보 없음" not in page.html
    assert page.observed_result_count == 5


def test_search_deadline_covers_navigation_even_if_driver_returns_late():
    final_url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    clock = ManualClock()

    class SlowNavigationDriver(FakeDriver):
        def get(self, url: str) -> None:
            super().get(url)
            clock.sleep(3)

    driver = SlowNavigationDriver([(final_url, result_html(20))])

    with pytest.raises(SearchStateTimeout) as caught:
        make_session(driver, timeout_seconds=2, clock=clock).search(make_task())

    assert driver.page_load_timeouts == [2]
    assert caught.value.last_url == final_url
    assert caught.value.html == result_html(20)


def test_search_maps_selenium_navigation_timeout_to_typed_timeout_with_context():
    final_url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    html = "<html><body>navigation still loading</body></html>"
    driver = FakeDriver([(final_url, html)], fail_on="navigation_timeout")

    with pytest.raises(SearchStateTimeout) as caught:
        make_session(driver).search(make_task())

    assert driver.page_load_timeouts == [2]
    assert caught.value.last_url == final_url
    assert caught.value.html == html


def test_search_uses_desktop_host_for_pc_task():
    final_url = "https://search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    driver = FakeDriver([(final_url, result_html(20))])

    make_session(driver).search(make_task(DeviceType.PC))

    assert urlparse(driver.get_calls[0]).netloc == "search.naver.com"


def test_search_scrolls_until_result_limit_is_reached():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    driver = FakeDriver([(url, result_html(5)), (url, result_html(12)), (url, result_html(20))])

    page = make_session(driver).search(make_task())

    assert len(driver.script_calls) == 2
    assert page.observed_result_count == 20
    assert not page.result_end_reached


def test_live_mobile_cards_are_results_and_more_control_is_not_an_end_marker():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    html = fixture("live_mobile_mixed_results.html")

    assert detect_page_state(url, html, QUERY) == "RESULTS"
    assert _result_progress(html) == (2, False)


def test_semantic_place_links_are_results_without_nmb_identifiers():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A4%EB%A0%81%ED%83%95"
    html = fixture("semantic_place_cards.html")

    assert detect_page_state(url, html, "설렁탕") == "RESULTS"
    assert _result_progress(html) == (2, False)


def test_search_accepts_short_semantic_results_after_dom_stabilizes():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A4%EB%A0%81%ED%83%95"
    driver = FakeDriver([(url, fixture("semantic_place_cards.html"))])

    page = make_session(driver, result_limit=5).search(
        SearchTask(
            "semantic",
            "설렁탕",
            "S1",
            "한촌설렁탕 선릉역점",
            "선릉역점",
            37.5035014,
            127.0517059,
            SourceType.EXCEL,
            "semantic",
            DeviceType.MOBILE,
        )
    )

    assert page.state == "RESULTS"
    assert page.observed_result_count == 2
    assert page.result_end_reached is False


def test_search_clicks_live_more_control_once_before_continuing_scroll_expansion():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    expandable = fixture("live_mobile_mixed_results.html")
    driver = FakeDriver([(url, expandable), (url, result_html(20))])

    class MoreButton:
        def __init__(self):
            self.clicks = 0

        def is_displayed(self):
            return True

        def is_enabled(self):
            return True

        def click(self):
            self.clicks += 1

    button = MoreButton()
    driver.more_button = button

    page = make_session(driver).search(make_task())

    assert page.observed_result_count == 20
    assert button.clicks == 1
    assert driver.find_element_calls == [(By.XPATH, driver.find_element_calls[0][1])]
    assert "role='button'" in driver.find_element_calls[0][1]
    assert "펼쳐서 더보기" in driver.find_element_calls[0][1]
    assert len(driver.script_calls) == 1


def test_search_clicks_more_control_when_it_appears_after_initial_scroll():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"

    class MoreButton:
        def __init__(self):
            self.clicks = 0

        def is_displayed(self):
            return True

        def is_enabled(self):
            return True

        def click(self):
            self.clicks += 1

    button = MoreButton()

    class DelayedMoreDriver(FakeDriver):
        def find_elements(self, by: str, value: str):
            self.find_element_calls.append((by, value))
            return [button] if self.page_index >= 1 else []

    driver = DelayedMoreDriver(
        [(url, result_html(5)), (url, result_html(12)), (url, result_html(20))]
    )

    page = make_session(driver).search(make_task())

    assert page.observed_result_count == 20
    assert button.clicks == 1
    assert len(driver.find_element_calls) == 2


def test_search_does_not_repeat_more_click_while_stuck_before_timeout():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    driver = FakeDriver([(url, fixture("live_mobile_mixed_results.html"))])

    class MoreButton:
        clicks = 0

        def is_displayed(self):
            return True

        def is_enabled(self):
            return True

        def click(self):
            self.clicks += 1

    button = MoreButton()
    driver.more_button = button

    with pytest.raises(SearchStateTimeout):
        make_session(driver).search(make_task())

    assert button.clicks == 1


def test_search_accepts_short_results_only_with_confirmed_end_marker():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    driver = FakeDriver([(url, result_html(5)), (url, result_html(8, ended=True))])

    page = make_session(driver).search(make_task())

    assert (page.observed_result_count, page.result_end_reached) == (8, True)


def test_search_returns_explicit_no_result_as_confirmed_end():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    driver = FakeDriver([(url, fixture("no_result.html"))])

    page = make_session(driver).search(make_task())

    assert (page.state, page.observed_result_count, page.result_end_reached) == ("NO_RESULT", 0, True)


def test_search_raises_query_mismatch_with_last_url_and_html():
    stale_url = "https://m.search.naver.com/search.naver?query=previous"
    stale_html = fixture("results.html")
    driver = FakeDriver([(stale_url, stale_html)])

    with pytest.raises(QueryMismatch) as caught:
        make_session(driver).search(make_task())

    assert caught.value.last_url == stale_url
    assert caught.value.html == stale_html


def test_search_raises_timeout_for_unfinished_loading_with_context():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    html = "<html><body>검색 중...</body></html>"
    driver = FakeDriver([(url, html)])

    with pytest.raises(SearchStateTimeout) as caught:
        make_session(driver).search(make_task())

    assert caught.value.last_url == url
    assert caught.value.html == html


def test_search_raises_page_error_immediately_with_context():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    html = fixture("error.html")
    driver = FakeDriver([(url, html)])

    with pytest.raises(SearchPageError) as caught:
        make_session(driver).search(make_task())

    assert caught.value.last_url == url
    assert caught.value.html == html
    assert driver.script_calls == []


def test_search_wraps_webdriver_failure_and_preserves_last_context():
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    html = result_html(3)
    driver = FakeDriver([(url, html)], fail_on="scroll")

    with pytest.raises(BrowserSessionError) as caught:
        make_session(driver).search(make_task())

    assert caught.value.last_url == url
    assert caught.value.html == html


def test_save_evidence_writes_html_and_screenshot(tmp_path: Path):
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    html = result_html(3)
    driver = FakeDriver([(url, html)])

    html_path, screenshot_path = make_session(driver).save_evidence(tmp_path)

    assert html_path == tmp_path / "page.html"
    assert screenshot_path == tmp_path / "screenshot.png"
    assert html_path.read_text(encoding="utf-8") == html
    assert screenshot_path.read_bytes() == b"fake-png"


def test_save_evidence_wraps_directory_creation_failure_with_context(tmp_path: Path):
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    html = result_html(3)
    driver = FakeDriver([(url, html)])
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("block mkdir", encoding="utf-8")

    with pytest.raises(BrowserSessionError) as caught:
        make_session(driver).save_evidence(blocking_file / "evidence", html=html)

    assert caught.value.last_url == url
    assert caught.value.html == html


def test_save_evidence_wraps_html_write_failure_with_context(tmp_path: Path):
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    html = result_html(3)
    driver = FakeDriver([(url, html)])
    (tmp_path / "page.html").mkdir()

    with pytest.raises(BrowserSessionError) as caught:
        make_session(driver).save_evidence(tmp_path, html=html)

    assert caught.value.last_url == url
    assert caught.value.html == html
    assert driver.screenshot_paths == []


def test_save_evidence_wraps_screenshot_failure_with_context(tmp_path: Path):
    url = "https://m.search.naver.com/search.naver?query=%EC%84%A0%EB%A6%89%EC%97%AD+%EA%B5%AD%EB%B0%A5"
    html = result_html(3)
    driver = FakeDriver([(url, html)], fail_on="screenshot")

    with pytest.raises(BrowserSessionError) as caught:
        make_session(driver).save_evidence(tmp_path, html=html)

    assert caught.value.last_url == url
    assert caught.value.html == html
