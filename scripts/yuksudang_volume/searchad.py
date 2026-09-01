import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import NaverConfig


SEARCHAD_BASE_URL = "https://api.searchad.naver.com"
KEYWORD_TOOL_URI = "/keywordstool"


class SearchAdError(RuntimeError):
    """Base error for SearchAd transport and response failures."""


class SearchAdAuthError(SearchAdError):
    """Raised for non-retryable authentication or authorization failures."""


def normalize_keyword(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def build_signature(
    timestamp: str,
    method: str,
    uri: str,
    secret_key: str,
) -> str:
    message = f"{timestamp}.{method}.{uri}".encode()
    digest = hmac.new(secret_key.encode(), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


@dataclass(frozen=True)
class SearchVolume:
    keyword: str
    pc: int | None
    mobile: int | None
    status: str
    raw_pc: str | int | None
    raw_mobile: str | int | None

    @property
    def total(self) -> int | None:
        if self.pc is None or self.mobile is None:
            return None
        return self.pc + self.mobile


def _parse_count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def parse_keyword_rows(
    payload: dict,
    requested: list[str],
) -> dict[str, SearchVolume]:
    by_normalized = {
        normalize_keyword(str(row.get("relKeyword", ""))): row
        for row in payload.get("keywordList", [])
    }
    result: dict[str, SearchVolume] = {}
    for keyword in requested:
        row = by_normalized.get(normalize_keyword(keyword))
        if not row:
            result[keyword] = SearchVolume(
                keyword,
                None,
                None,
                "searchad_no_data",
                None,
                None,
            )
            continue

        raw_pc = row.get("monthlyPcQcCnt")
        raw_mobile = row.get("monthlyMobileQcCnt")
        pc = _parse_count(raw_pc)
        mobile = _parse_count(raw_mobile)
        status = (
            "success"
            if pc is not None and mobile is not None
            else "searchad_low_volume"
        )
        result[keyword] = SearchVolume(
            keyword,
            pc,
            mobile,
            status,
            raw_pc,
            raw_mobile,
        )
    return result


class SearchAdClient:
    def __init__(
        self,
        config: NaverConfig,
        *,
        timeout_seconds: float = 20.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._timeout_seconds = timeout_seconds
        self._sleep = sleep

    def _request(self, keywords: list[str]) -> dict:
        params = urlencode(
            {
                "hintKeywords": ",".join(keywords),
                "showDetail": "1",
            }
        )
        url = f"{SEARCHAD_BASE_URL}{KEYWORD_TOOL_URI}?{params}"
        delays = (0, 1, 2, 4)
        last_error: Exception | None = None

        for attempt, delay in enumerate(delays):
            if delay:
                self._sleep(delay)
            timestamp = str(int(time.time() * 1000))
            headers = {
                "X-Timestamp": timestamp,
                "X-API-KEY": self._config.searchad_api_key,
                "X-Customer": self._config.searchad_customer_id,
                "X-Signature": build_signature(
                    timestamp,
                    "GET",
                    KEYWORD_TOOL_URI,
                    self._config.searchad_secret_key,
                ),
            }
            request = Request(url, method="GET", headers=headers)
            try:
                with urlopen(request, timeout=self._timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as error:
                if error.code in (401, 403):
                    raise SearchAdAuthError(
                        f"SearchAd authentication failed with HTTP {error.code}"
                    ) from error
                if error.code != 429 and not 500 <= error.code < 600:
                    raise SearchAdError(
                        f"SearchAd request failed with HTTP {error.code}"
                    ) from error
                last_error = error
            except URLError as error:
                last_error = error

            if attempt == len(delays) - 1:
                break

        raise SearchAdError("SearchAd request failed after retries") from last_error

    def fetch_volumes(self, keywords: list[str]) -> dict[str, SearchVolume]:
        unique: list[str] = []
        seen: set[str] = set()
        for keyword in keywords:
            normalized = normalize_keyword(keyword)
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique.append(keyword)

        result: dict[str, SearchVolume] = {}
        for start in range(0, len(unique), 5):
            chunk = unique[start : start + 5]
            result.update(parse_keyword_rows(self._request(chunk), chunk))
        return result
