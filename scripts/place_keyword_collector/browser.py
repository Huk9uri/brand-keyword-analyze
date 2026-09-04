"""Selenium acquisition for mobile Naver Place pages.

This module deliberately stops at acquiring a stable page.  Interpreting the
representative-keyword payload belongs to :mod:`parser`.
"""

from __future__ import annotations

import html as html_module
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options

from .models import RankPlaceTarget


MOBILE_PLACE_HOME = "https://m.place.naver.com/restaurant/{place_id}/home"
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)

# These are complete Naver restriction messages rather than broad fragments
# such as "접근" or "오류", both of which occur on legitimate Place pages.
NAVER_RESTRICTION_MARKERS = (
    "비정상적인 접근이 감지되었습니다.",
    "서비스 이용이 일시적으로 제한되었습니다.",
    "현재 서비스 이용이 제한되었습니다.",
    "접근이 제한된 페이지입니다.",
)

_DEFINITIVE_TARGET_KEYS = (
    "name",
    "businessName",
    "category",
    "businessCategory",
    "bookingBusinessId",
)


@dataclass(frozen=True)
class PlacePage:
    """The final browser URL and source, without parser conclusions."""

    final_url: str
    html: str


class PlaceBrowserError(RuntimeError):
    """Base browser failure carrying the last safely captured state."""

    def __init__(self, message: str, *, last_url: str, html: str) -> None:
        super().__init__(message)
        self.last_url = last_url
        self.html = html


class BlockedPageError(PlaceBrowserError):
    """Naver rendered an explicit access-restriction page."""


class PlaceLoadTimeout(PlaceBrowserError):
    """The target page did not become ready within the shared deadline."""


def is_blocked_page(source: str) -> bool:
    """Return whether source contains one of Naver's exact restriction texts."""

    return any(marker in (source or "") for marker in NAVER_RESTRICTION_MARKERS)


def is_place_page_ready(source: str, requested_place_id: str) -> bool:
    """Return whether source definitively contains the requested Place object."""

    place_id = str(requested_place_id).strip()
    if not place_id:
        return False

    for candidate in _source_candidates(source or ""):
        match = _target_id_match(candidate, place_id)
        if match is None:
            continue
        if re.search(r'["\']keywordList["\']\s*:', candidate):
            return True

        object_start = candidate.rfind("{", 0, match.start())
        object_end = candidate.find("}", match.end())
        if object_start < 0 or object_end < 0:
            continue
        target_object = candidate[object_start : object_end + 1]
        if any(
            re.search(rf'["\']{re.escape(key)}["\']\s*:', target_object)
            for key in _DEFINITIVE_TARGET_KEYS
        ):
            return True
        if (
            re.search(r'["\']x["\']\s*:', target_object)
            and re.search(r'["\']y["\']\s*:', target_object)
        ):
            return True
    return False


class PlacePageBrowser:
    """Acquire one or more Place pages using a reusable WebDriver session."""

    def __init__(
        self,
        driver: Any,
        *,
        timeout_seconds: float = 30,
        poll_interval: float = 0.25,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be greater than zero")
        self.driver = driver
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_url = ""
        self._last_html = ""

    def fetch(self, target: RankPlaceTarget) -> PlacePage:
        """Navigate to a mobile Place home page and wait for target evidence."""

        place_id = str(target.place_id).strip()
        target_url = MOBILE_PLACE_HOME.format(place_id=quote(place_id, safe=""))
        deadline = self._monotonic() + self.timeout_seconds

        try:
            self.driver.set_page_load_timeout(self.timeout_seconds)
            self.driver.get(target_url)
        except TimeoutException as exc:
            self._capture_best_effort()
            raise self._timeout("Place navigation exceeded the collection deadline") from exc
        except Exception as exc:
            self._capture_best_effort()
            raise self._error("Place navigation failed") from exc

        self._capture_or_raise()
        if self._monotonic() >= deadline:
            raise self._timeout("Place navigation exceeded the collection deadline")

        while True:
            if self._monotonic() >= deadline:
                raise self._timeout("Place page did not become ready before the collection deadline")
            if is_blocked_page(self._last_html):
                raise BlockedPageError(
                    "Naver returned an access-restriction page",
                    last_url=self._last_url,
                    html=self._last_html,
                )
            if is_place_page_ready(self._last_html, place_id):
                return PlacePage(final_url=self._last_url, html=self._last_html)

            remaining = deadline - self._monotonic()
            self._sleep(min(self.poll_interval, remaining))
            self._capture_or_raise()

    def save_evidence(self, directory: Path, html: str) -> tuple[Path, Path]:
        """Write final-failure HTML and a screenshot to ``directory``."""

        directory = Path(directory)
        html_path = directory / "page.html"
        screenshot_path = directory / "screenshot.png"
        self._last_html = html
        self._capture_url_best_effort()

        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise self._error("Could not create the evidence directory") from exc
        try:
            html_path.write_text(html, encoding="utf-8")
        except OSError as exc:
            raise self._error("Could not write HTML evidence") from exc
        try:
            saved = self.driver.save_screenshot(str(screenshot_path))
        except Exception as exc:
            raise self._error("Could not save screenshot evidence") from exc
        if saved is False:
            raise self._error("WebDriver declined to save screenshot evidence")
        return html_path, screenshot_path

    def close(self) -> None:
        """Close the reusable WebDriver session."""

        try:
            self.driver.quit()
        except Exception as exc:
            self._capture_best_effort()
            raise self._error("Could not close the Place browser") from exc

    def _capture_or_raise(self) -> None:
        try:
            current_url = self.driver.current_url
            source = self.driver.page_source
        except Exception as exc:
            self._capture_best_effort()
            raise self._error("Could not inspect the Place browser state") from exc
        self._last_url = current_url or ""
        self._last_html = source or ""

    def _capture_best_effort(self) -> None:
        self._capture_url_best_effort()
        try:
            self._last_html = self.driver.page_source or ""
        except Exception:
            pass

    def _capture_url_best_effort(self) -> None:
        try:
            self._last_url = self.driver.current_url or ""
        except Exception:
            pass

    def _timeout(self, message: str) -> PlaceLoadTimeout:
        return PlaceLoadTimeout(message, last_url=self._last_url, html=self._last_html)

    def _error(self, message: str) -> PlaceBrowserError:
        # Underlying WebDriver and OS messages can contain proxy URLs, tokens, or
        # credential-bearing paths, so the public error deliberately omits them.
        return PlaceBrowserError(message, last_url=self._last_url, html=self._last_html)


class BrowserFactory:
    """Build mobile-configured reusable Place browser sessions."""

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_seconds: float = 30,
        poll_interval: float = 0.25,
        driver_builder: Callable[..., Any] | None = None,
    ) -> None:
        self.headless = headless
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self._driver_builder = driver_builder or webdriver.Chrome

    def create(self) -> PlacePageBrowser:
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument(f"--user-agent={MOBILE_USER_AGENT}")

        try:
            driver = self._driver_builder(options=options)
            driver.set_window_size(390, 844)
        except Exception as exc:
            raise PlaceBrowserError(
                "Could not create the Place browser session",
                last_url="",
                html="",
            ) from exc
        return PlacePageBrowser(
            driver,
            timeout_seconds=self.timeout_seconds,
            poll_interval=self.poll_interval,
        )


def _source_candidates(source: str) -> tuple[str, ...]:
    decoded_entities = html_module.unescape(source)
    decoded_quotes = decoded_entities.replace(r'\"', '"').replace(r"\'", "'")
    return tuple(dict.fromkeys((source, decoded_entities, decoded_quotes)))


def _target_id_match(source: str, place_id: str) -> re.Match[str] | None:
    escaped_id = re.escape(place_id)
    pattern = re.compile(
        rf'["\'](?:id|placeId|place_id)["\']\s*:\s*'
        rf'(?:["\']{escaped_id}["\']|{escaped_id})(?=\s*[,}}])'
    )
    return pattern.search(source)


# Descriptive alias for callers that have both search and Place browser factories.
PlaceBrowserFactory = BrowserFactory


__all__ = [
    "BlockedPageError",
    "BrowserFactory",
    "MOBILE_USER_AGENT",
    "PlaceBrowserError",
    "PlaceBrowserFactory",
    "PlaceLoadTimeout",
    "PlacePage",
    "PlacePageBrowser",
    "is_blocked_page",
    "is_place_page_ready",
]
