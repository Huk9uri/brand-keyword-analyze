from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable

import pytest
from selenium.common.exceptions import TimeoutException

import scripts.place_keyword_collector.browser as browser_module
from scripts.place_keyword_collector.browser import (
    MOBILE_USER_AGENT,
    BlockedPageError,
    BrowserFactory,
    PlaceBrowserError,
    PlaceLoadTimeout,
    PlacePage,
    PlacePageBrowser,
)
from scripts.place_keyword_collector.models import RankPlaceTarget


FIXTURES = Path(__file__).parent / "fixtures" / "place_keyword_collector"
READY_HTML = (
    '<html><script>window.__PLACE_STATE__={"restaurant":'
    '{"id":"13149768","keywordList":["순대"]}};</script></html>'
)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def target() -> RankPlaceTarget:
    return RankPlaceTarget("13149768", "농민백암순대 본점")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeDriver:
    def __init__(
        self,
        *,
        pages: tuple[str, ...] = (READY_HTML,),
        url: str = "https://m.place.naver.com/restaurant/13149768/home",
        on_get: Callable[[], None] | None = None,
    ) -> None:
        self.pages = pages
        self.url = url
        self.on_get = on_get
        self.requested_url = ""
        self.page_load_timeout: float | None = None
        self.page_reads = 0
        self.screenshot_result = True
        self.screenshot_path = ""
        self.quit_calls = 0

    def set_page_load_timeout(self, seconds: float) -> None:
        self.page_load_timeout = seconds

    def get(self, url: str) -> None:
        self.requested_url = url
        if self.on_get is not None:
            self.on_get()

    @property
    def current_url(self) -> str:
        return self.url

    @property
    def page_source(self) -> str:
        page = self.pages[min(self.page_reads, len(self.pages) - 1)]
        self.page_reads += 1
        return page

    def save_screenshot(self, path: str) -> bool:
        self.screenshot_path = path
        if self.screenshot_result:
            Path(path).write_bytes(b"png")
        return self.screenshot_result

    def quit(self) -> None:
        self.quit_calls += 1


def browser(
    driver: FakeDriver,
    clock: FakeClock | None = None,
    *,
    timeout_seconds: float = 3,
) -> PlacePageBrowser:
    clock = clock or FakeClock()
    return PlacePageBrowser(
        driver,
        timeout_seconds=timeout_seconds,
        poll_interval=1,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


def test_browser_uses_mobile_place_home_url_and_returns_unparsed_page():
    driver = FakeDriver()

    page = browser(driver).fetch(target())

    assert driver.requested_url == "https://m.place.naver.com/restaurant/13149768/home"
    assert page == PlacePage(final_url=driver.url, html=READY_HTML)


def test_browser_classifies_exact_access_restriction_with_last_state():
    html = fixture("blocked.html")
    driver = FakeDriver(pages=(html,))

    with pytest.raises(BlockedPageError) as raised:
        browser(driver).fetch(target())

    assert raised.value.last_url == driver.url
    assert raised.value.html == html


def test_browser_does_not_classify_unrelated_access_word_as_restriction():
    driver = FakeDriver(
        pages=(
            '<html><p>주차장 접근 경로</p><script>{"id":"13149768",'
            '"keywordList":[]}</script></html>',
        )
    )

    assert browser(driver).fetch(target()).final_url == driver.url


def test_browser_polls_until_definitive_target_object_is_available():
    driver = FakeDriver(
        pages=(
            "<html><body>loading</body></html>",
            '<html><script>{"restaurant":{"id":"13149768","name":"농민백암순대 본점"}}</script></html>',
        )
    )
    clock = FakeClock()

    page = browser(driver, clock).fetch(target())

    assert "농민백암순대 본점" in page.html
    assert clock.sleeps == [1]


def test_browser_checks_later_target_object_after_early_sparse_id_reference():
    html = (
        '<html><script>{"references":[{"id":"13149768"}],'
        '"restaurant":{"id":"13149768","name":"농민백암순대 본점"}}</script></html>'
    )

    page = browser(FakeDriver(pages=(html,))).fetch(target())

    assert page.html == html


def test_browser_requires_exact_requested_place_id_before_ready():
    driver = FakeDriver(
        pages=(
            '<html><script>{"id":"131497680","keywordList":[]}</script></html>',
        )
    )
    clock = FakeClock()

    with pytest.raises(PlaceLoadTimeout) as raised:
        browser(driver, clock, timeout_seconds=2).fetch(target())

    assert raised.value.html == driver.pages[0]
    assert clock.now == 2


def test_navigation_and_polling_share_one_deadline():
    clock = FakeClock()
    driver = FakeDriver(
        pages=("<html>loading</html>",),
        on_get=lambda: setattr(clock, "now", 2.5),
    )

    with pytest.raises(PlaceLoadTimeout):
        browser(driver, clock, timeout_seconds=3).fetch(target())

    assert driver.page_load_timeout == 3
    assert clock.sleeps == [0.5]
    assert clock.now == 3


def test_navigation_that_returns_after_deadline_is_timeout_even_if_page_is_ready():
    clock = FakeClock()
    driver = FakeDriver(
        on_get=lambda: setattr(clock, "now", 3.1),
    )

    with pytest.raises(PlaceLoadTimeout) as raised:
        browser(driver, clock, timeout_seconds=3).fetch(target())

    assert raised.value.html == READY_HTML


def test_blocked_navigation_has_priority_when_navigation_reaches_deadline():
    clock = FakeClock()
    blocked = fixture("blocked.html")
    driver = FakeDriver(
        pages=(blocked,),
        on_get=lambda: setattr(clock, "now", 3),
    )

    with pytest.raises(BlockedPageError) as raised:
        browser(driver, clock, timeout_seconds=3).fetch(target())

    assert raised.value.html == blocked


def test_page_that_becomes_ready_at_deadline_is_still_timeout():
    clock = FakeClock()
    driver = FakeDriver(pages=("<html>loading</html>", READY_HTML))

    with pytest.raises(PlaceLoadTimeout) as raised:
        browser(driver, clock, timeout_seconds=1).fetch(target())

    assert raised.value.html == READY_HTML
    assert clock.now == 1


def test_blocked_poll_has_priority_when_it_appears_at_deadline():
    clock = FakeClock()
    blocked = fixture("blocked.html")
    driver = FakeDriver(pages=("<html>loading</html>", blocked))

    with pytest.raises(BlockedPageError) as raised:
        browser(driver, clock, timeout_seconds=1).fetch(target())

    assert raised.value.html == blocked
    assert clock.now == 1


def test_scan_that_crosses_deadline_times_out_without_nonpositive_sleep(monkeypatch):
    clock = FakeClock()
    real_readiness_scan = browser_module.is_place_page_ready

    def slow_readiness_scan(source: str, requested_place_id: str) -> bool:
        ready = real_readiness_scan(source, requested_place_id)
        clock.now = 1.1
        return ready

    def reject_nonpositive_sleep(seconds: float) -> None:
        if seconds <= 0:
            raise AssertionError(f"nonpositive sleep: {seconds}")
        clock.sleep(seconds)

    monkeypatch.setattr(browser_module, "is_place_page_ready", slow_readiness_scan)
    instance = PlacePageBrowser(
        FakeDriver(pages=("<html>loading</html>",)),
        timeout_seconds=1,
        poll_interval=1,
        monotonic=clock.monotonic,
        sleep=reject_nonpositive_sleep,
    )

    with pytest.raises(PlaceLoadTimeout):
        instance.fetch(target())

    assert clock.sleeps == []


def test_selenium_navigation_timeout_preserves_best_available_state():
    class TimedOutDriver(FakeDriver):
        def get(self, url: str) -> None:
            self.requested_url = url
            raise TimeoutException("secret-token=do-not-copy")

    driver = TimedOutDriver(pages=("<html>partial</html>",))

    with pytest.raises(PlaceLoadTimeout) as raised:
        browser(driver).fetch(target())

    assert raised.value.last_url == driver.url
    assert raised.value.html == "<html>partial</html>"
    assert "do-not-copy" not in str(raised.value)


def test_selenium_navigation_timeout_prioritizes_captured_blocked_page():
    class TimedOutBlockedDriver(FakeDriver):
        def get(self, url: str) -> None:
            self.requested_url = url
            raise TimeoutException("navigation timed out")

    html = fixture("blocked.html")
    driver = TimedOutBlockedDriver(pages=(html,))

    with pytest.raises(BlockedPageError) as raised:
        browser(driver).fetch(target())

    assert type(raised.value) is BlockedPageError
    assert raised.value.last_url == driver.url
    assert raised.value.html == html


def test_generic_driver_failure_is_typed_and_does_not_echo_credentials():
    class FailedDriver(FakeDriver):
        def get(self, url: str) -> None:
            raise RuntimeError("password=hunter2")

    with pytest.raises(PlaceBrowserError) as raised:
        browser(FailedDriver()).fetch(target())

    assert "hunter2" not in str(raised.value)
    assert hasattr(raised.value, "last_url")
    assert hasattr(raised.value, "html")


def test_sanitized_browser_error_traceback_does_not_retain_sensitive_cause():
    secret = "password=traceback-secret"

    class FailedDriver(FakeDriver):
        def get(self, url: str) -> None:
            raise RuntimeError(secret)

    with pytest.raises(PlaceBrowserError) as raised:
        browser(FailedDriver()).fetch(target())

    rendered = "".join(
        traceback.format_exception(
            raised.type,
            raised.value,
            raised.value.__traceback__,
        )
    )
    assert secret not in rendered
    assert raised.value.__cause__ is None


def test_save_evidence_writes_supplied_html_and_screenshot(tmp_path: Path):
    driver = FakeDriver()
    instance = browser(driver)

    html_path, screenshot_path = instance.save_evidence(tmp_path, "<html>failure</html>")

    assert html_path.read_text(encoding="utf-8") == "<html>failure</html>"
    assert screenshot_path.read_bytes() == b"png"
    assert driver.screenshot_path == str(screenshot_path)


def test_save_evidence_rejects_false_screenshot_result(tmp_path: Path):
    driver = FakeDriver()
    driver.screenshot_result = False

    with pytest.raises(PlaceBrowserError, match="screenshot") as raised:
        browser(driver).save_evidence(tmp_path, "<html>failure</html>")

    assert raised.value.html == "<html>failure</html>"


def test_evidence_write_failure_does_not_echo_sensitive_path(tmp_path: Path):
    sensitive = tmp_path / "password=hunter2"
    sensitive.write_text("blocking file", encoding="utf-8")

    with pytest.raises(PlaceBrowserError) as raised:
        browser(FakeDriver()).save_evidence(sensitive / "evidence", "<html>failure</html>")

    assert "hunter2" not in str(raised.value)


def test_factory_configures_mobile_user_agent_headless_and_viewport():
    created: dict[str, object] = {}

    def build_driver(*, options):
        created["arguments"] = tuple(options.arguments)
        driver = FakeDriver()
        driver.window_size = None
        driver.set_window_size = lambda width, height: setattr(driver, "window_size", (width, height))
        created["driver"] = driver
        return driver

    instance = BrowserFactory(driver_builder=build_driver).create()

    assert "--headless=new" in created["arguments"]
    assert f"--user-agent={MOBILE_USER_AGENT}" in created["arguments"]
    assert created["driver"].window_size == (390, 844)
    instance.close()
    assert created["driver"].quit_calls == 1


def test_factory_wraps_creation_failure_without_credentials():
    def fail(*, options):
        raise RuntimeError("webdriver-token=secret")

    with pytest.raises(PlaceBrowserError) as raised:
        BrowserFactory(driver_builder=fail).create()

    assert raised.value.last_url == ""
    assert raised.value.html == ""
    assert "secret" not in str(raised.value)
