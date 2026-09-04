from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

from .models import DeviceType, SearchPage, SearchTask
from .place_cards import semantic_place_cards


MOBILE_SEARCH_URL = "https://m.search.naver.com/search.naver"
PC_SEARCH_URL = "https://search.naver.com/search.naver"
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)

RESULT_CARD_SELECTOR = (
    "li[data-nmb_res-doc-id], li[data-nmb_rese-doc-id], "
    "[data-naver-place-card], li.place-result-card, li.VLTHu"
)
DIRECT_PLACE_SELECTOR = "[data-laim-exp-id^='nmb_lpa']"
RESULT_END_SELECTOR = "[data-naver-search-end]"
MORE_RESULTS_XPATH = (
    "//*[@id='place-app-root']//*[@role='button' and "
    "contains(normalize-space(.), '펼쳐서 더보기')]"
)
NO_RESULT_TEXTS = ("검색결과가 없습니다", "검색 결과가 없습니다")
ERROR_TEXTS = (
    "일시적인 오류",
    "오류가 발생했습니다",
    "서비스 접속이 원활하지 않습니다",
    "잠시 후 다시 시도",
)
RESULT_END_TEXTS = ("검색 결과의 끝", "더 이상 검색 결과가 없습니다")
LOCATION_UNAVAILABLE_TEXT = "위치 정보 없음"


class BrowserError(RuntimeError):
    """Base failure containing the last browser state for retry evidence."""

    def __init__(self, message: str, *, last_url: str, html: str) -> None:
        super().__init__(message)
        self.last_url = last_url
        self.html = html


class QueryMismatch(BrowserError):
    """The browser never reached a URL for the requested query."""


class SearchStateTimeout(BrowserError):
    """The matching search page did not reach a confirmed terminal state."""


class SearchPageError(BrowserError):
    """Naver rendered an explicit search error page."""


class BrowserSessionError(BrowserError):
    """WebDriver failed while creating or operating a browser session."""


def query_matches_url(url: str, requested_query: str) -> bool:
    """Return whether a Naver URL contains the requested decoded query."""

    try:
        parameters = parse_qs(urlparse(url).query, keep_blank_values=True)
    except (TypeError, ValueError):
        return False

    expected = _normalize_query(requested_query)
    return any(
        _normalize_query(value) == expected
        for name in ("query", "searchText")
        for value in parameters.get(name, ())
    )


def detect_page_state(url: str, html: str, requested_query: str) -> str:
    """Classify rendered DOM only after the URL proves it belongs to the query."""

    if not query_matches_url(url, requested_query):
        return "QUERY_MISMATCH"

    soup = BeautifulSoup(html or "", "html.parser")
    for non_visible in soup.select("script, style, template, noscript"):
        non_visible.decompose()
    for non_visible in reversed(soup.find_all(True)):
        style = "".join(str(non_visible.get("style", "")).lower().split())
        if (
            non_visible.has_attr("hidden")
            or str(non_visible.get("aria-hidden", "")).lower() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        ):
            non_visible.decompose()
    visible_text = " ".join(soup.stripped_strings)
    if any(marker in visible_text for marker in ERROR_TEXTS):
        return "ERROR"
    if any(marker in visible_text for marker in NO_RESULT_TEXTS):
        return "NO_RESULT"
    if LOCATION_UNAVAILABLE_TEXT in visible_text:
        return "LOCATION_PENDING"
    if semantic_place_cards(soup) or soup.select_one(RESULT_CARD_SELECTOR) is not None or soup.select_one(DIRECT_PLACE_SELECTOR) is not None:
        return "RESULTS"
    return "LOADING"


class BrowserSession:
    def __init__(
        self,
        driver: Any,
        *,
        timeout_seconds: float = 30,
        result_limit: int = 20,
        poll_interval: float = 0.25,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        location_override_active: bool = False,
    ) -> None:
        self.driver = driver
        self.timeout_seconds = timeout_seconds
        self.result_limit = result_limit
        self.poll_interval = poll_interval
        self._monotonic = monotonic
        self._sleep = sleep
        self.location_override_active = location_override_active
        self._last_url = ""
        self._last_html = ""

    def search(self, task: SearchTask) -> SearchPage:
        search_url = _build_search_url(task)
        deadline = self._monotonic() + self.timeout_seconds
        try:
            self.driver.set_page_load_timeout(self.timeout_seconds)
            self.driver.get(search_url)
        except TimeoutException as exc:
            self._capture_best_effort()
            raise SearchStateTimeout(
                f"search navigation did not complete before timeout: {exc}",
                last_url=self._last_url,
                html=self._last_html,
            ) from exc
        except Exception as exc:
            raise self._session_error("failed to load search URL", exc) from exc

        self._capture()
        if self._monotonic() >= deadline:
            raise SearchStateTimeout(
                "search navigation exceeded the task timeout",
                last_url=self._last_url,
                html=self._last_html,
            )

        last_state = "LOADING"
        more_control_clicked = False
        location_activated = not (
            self.location_override_active and _query_requires_location_activation(task)
        )
        stable_signature: int | None = None
        stable_polls = 0
        while True:
            self._capture()
            if not location_activated:
                if self._activate_current_location_if_needed():
                    location_activated = True
                    stable_signature = None
                    stable_polls = 0
                if not location_activated:
                    if self._monotonic() >= deadline:
                        raise SearchStateTimeout(
                            "current-location control did not become available before timeout",
                            last_url=self._last_url,
                            html=self._last_html,
                        )
                    self._sleep(self.poll_interval)
                    continue
            last_state = detect_page_state(self._last_url, self._last_html, task.query)
            observed_count, end_reached = _result_progress(self._last_html)
            signature = observed_count
            if last_state == "RESULTS" and signature == stable_signature:
                stable_polls += 1
            elif last_state == "RESULTS":
                stable_signature = signature
                stable_polls = 1
            else:
                stable_signature = None
                stable_polls = 0

            if last_state == "ERROR":
                raise SearchPageError(
                    "Naver returned an explicit search error",
                    last_url=self._last_url,
                    html=self._last_html,
                )
            if last_state == "NO_RESULT":
                return SearchPage(self._last_url, self._last_html, "NO_RESULT", 0, True)
            if (
                last_state == "RESULTS"
                and observed_count < self.result_limit
                and not end_reached
                and not more_control_clicked
            ):
                try:
                    more_control_clicked = self._click_more_results_if_available()
                    if more_control_clicked:
                        stable_signature = None
                        stable_polls = 0
                except Exception as exc:
                    raise self._session_error("failed while expanding search results", exc) from exc
            expanded_end_reached = (
                last_state == "RESULTS"
                and more_control_clicked
                and stable_polls >= 3
                and not self._more_results_control_available()
            )
            if last_state == "RESULTS" and (
                observed_count >= self.result_limit or end_reached or stable_polls >= 3
            ):
                return SearchPage(
                    self._last_url,
                    self._last_html,
                    "RESULTS",
                    observed_count,
                    end_reached or expanded_end_reached,
                )

            if self._monotonic() >= deadline:
                exception_type = QueryMismatch if last_state == "QUERY_MISMATCH" else SearchStateTimeout
                message = (
                    "search URL did not match requested query"
                    if exception_type is QueryMismatch
                    else "search state did not complete before timeout"
                )
                raise exception_type(message, last_url=self._last_url, html=self._last_html)

            if last_state == "RESULTS":
                try:
                    self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                except Exception as exc:
                    raise self._session_error("failed while expanding search results", exc) from exc
            self._sleep(self.poll_interval)

    def save_evidence(self, directory: Path, *, html: str | None = None) -> tuple[Path, Path]:
        directory = Path(directory)
        html_path = directory / "page.html"
        screenshot_path = directory / "screenshot.png"

        if html is None:
            self._capture()
            html = self._last_html
        else:
            self._last_html = html
            self._capture_url_best_effort()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise self._session_error("failed to create evidence directory", exc) from exc
        try:
            html_path.write_text(html, encoding="utf-8")
        except OSError as exc:
            raise self._session_error("failed to write HTML evidence", exc) from exc
        try:
            saved = self.driver.save_screenshot(str(screenshot_path))
        except Exception as exc:
            raise self._session_error("failed to save screenshot evidence", exc) from exc
        if saved is False:
            raise BrowserSessionError(
                "WebDriver declined to save screenshot evidence",
                last_url=self._last_url,
                html=self._last_html,
            )
        return html_path, screenshot_path

    def _capture(self) -> None:
        try:
            self._last_url = self.driver.current_url
            self._last_html = self.driver.page_source
        except Exception as exc:
            raise self._session_error("failed to inspect browser state", exc) from exc

    def _click_more_results_if_available(self) -> bool:
        for element in self.driver.find_elements(By.XPATH, MORE_RESULTS_XPATH):
            if element.is_displayed() and element.is_enabled():
                element.click()
                return True
        return False

    def _more_results_control_available(self) -> bool:
        return any(
            element.is_displayed() and element.is_enabled()
            for element in self.driver.find_elements(By.XPATH, MORE_RESULTS_XPATH)
        )

    def _activate_current_location_if_needed(self) -> bool:
        for element in self.driver.find_elements(By.ID, "_my_location"):
            if element.is_displayed() and element.is_enabled():
                element.click()
                self._sleep(self.poll_interval)
                return True
        return False

    def _capture_best_effort(self) -> None:
        self._capture_url_best_effort()
        try:
            self._last_html = self.driver.page_source
        except Exception:
            pass

    def _capture_url_best_effort(self) -> None:
        try:
            self._last_url = self.driver.current_url
        except Exception:
            pass

    def _session_error(self, message: str, cause: Exception) -> BrowserSessionError:
        return BrowserSessionError(
            f"{message}: {cause}",
            last_url=self._last_url,
            html=self._last_html,
        )


class BrowserFactory:
    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_seconds: float = 30,
        result_limit: int = 20,
        poll_interval: float = 0.25,
        driver_builder: Callable[..., Any] | None = None,
    ) -> None:
        self.headless = headless
        self.timeout_seconds = timeout_seconds
        self.result_limit = result_limit
        self.poll_interval = poll_interval
        self._driver_builder = driver_builder or webdriver.Chrome

    def create(
        self,
        device_type: DeviceType,
        latitude: float | None,
        longitude: float | None,
    ) -> BrowserSession:
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        if device_type is DeviceType.MOBILE:
            options.add_argument(f"--user-agent={MOBILE_USER_AGENT}")
            viewport = (390, 844)
        else:
            viewport = (1440, 1000)

        try:
            driver = self._driver_builder(options=options)
            driver.set_window_size(*viewport)
            if latitude is not None and longitude is not None:
                driver.execute_cdp_cmd(
                    "Emulation.setGeolocationOverride",
                    {"latitude": latitude, "longitude": longitude, "accuracy": 100},
                )
                search_origin = (
                    "https://m.search.naver.com"
                    if device_type is DeviceType.MOBILE
                    else "https://search.naver.com"
                )
                driver.execute_cdp_cmd(
                    "Browser.grantPermissions",
                    {"origin": search_origin, "permissions": ["geolocation"]},
                )
        except Exception as exc:
            raise BrowserSessionError(
                f"failed to create browser session: {exc}",
                last_url="",
                html="",
            ) from exc
        return BrowserSession(
            driver,
            timeout_seconds=self.timeout_seconds,
            result_limit=self.result_limit,
            poll_interval=self.poll_interval,
            location_override_active=latitude is not None and longitude is not None,
        )


def _query_requires_location_activation(task: SearchTask) -> bool:
    query = re.sub(r"\s+", "", task.query).casefold()
    location = re.sub(r"\s+", "", task.location_name).casefold()
    location = re.sub(r"(?:역)?점$", "", location)
    return bool(location) and location not in query


def _normalize_query(value: str) -> str:
    return " ".join(value.split())


def _build_search_url(task: SearchTask) -> str:
    base_url = MOBILE_SEARCH_URL if task.device_type is DeviceType.MOBILE else PC_SEARCH_URL
    parameters = {"where": "m" if task.device_type is DeviceType.MOBILE else "place", "query": task.query}
    return f"{base_url}?{urlencode(parameters)}"


def _result_progress(html: str) -> tuple[int, bool]:
    soup = BeautifulSoup(html or "", "html.parser")
    identified_cards = soup.select(RESULT_CARD_SELECTOR)
    count = len(identified_cards) if identified_cards else len(semantic_place_cards(soup))
    direct_place = soup.select_one(DIRECT_PLACE_SELECTOR)
    if count == 0 and direct_place is not None:
        return 1, True
    text = " ".join(soup.stripped_strings)
    end_reached = soup.select_one(RESULT_END_SELECTOR) is not None or any(
        marker in text for marker in RESULT_END_TEXTS
    )
    return count, end_reached
