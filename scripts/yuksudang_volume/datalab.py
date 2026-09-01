import json
import time
from datetime import date, timedelta
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import NaverConfig
from .searchad import normalize_keyword


DATALAB_SEARCH_URL = "https://openapi.naver.com/v1/datalab/search"


class DataLabError(RuntimeError):
    """Base error for DataLab transport and response failures."""


class DataLabAuthError(DataLabError):
    """Raised for non-retryable authentication or authorization failures."""


def _date_grid(start_date: date, end_date: date) -> dict[date, float]:
    if end_date < start_date:
        raise ValueError("end_date must not precede start_date")
    return {
        start_date + timedelta(days=offset): 0.0
        for offset in range((end_date - start_date).days + 1)
    }


def normalize_series(
    payload: dict,
    keywords: list[str],
    start_date: date,
    end_date: date,
) -> dict[str, dict[date, float]]:
    by_title = {
        normalize_keyword(str(group.get("title", ""))): group
        for group in payload.get("results", [])
    }
    result: dict[str, dict[date, float]] = {}
    for keyword in keywords:
        series = _date_grid(start_date, end_date)
        group = by_title.get(normalize_keyword(keyword), {})
        for point in group.get("data", []):
            try:
                day = date.fromisoformat(str(point["period"]))
                ratio = float(point["ratio"])
            except (KeyError, TypeError, ValueError):
                continue
            if day in series and ratio >= 0:
                series[day] = ratio
        result[keyword] = series
    return result


class DataLabClient:
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

    def _request(
        self,
        keywords: list[str],
        start_date: date,
        end_date: date,
    ) -> dict:
        body = json.dumps(
            {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "timeUnit": "date",
                "keywordGroups": [
                    {"groupName": keyword, "keywords": [keyword]}
                    for keyword in keywords
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        delays = (0, 1, 2, 4)
        last_error: Exception | None = None

        for attempt, delay in enumerate(delays):
            if delay:
                self._sleep(delay)
            request = Request(
                DATALAB_SEARCH_URL,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-Naver-Client-Id": self._config.datalab_client_id,
                    "X-Naver-Client-Secret": self._config.datalab_client_secret,
                },
            )
            try:
                with urlopen(request, timeout=self._timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as error:
                if error.code in (401, 403):
                    raise DataLabAuthError(
                        f"DataLab authentication failed with HTTP {error.code}"
                    ) from error
                if error.code != 429 and not 500 <= error.code < 600:
                    raise DataLabError(
                        f"DataLab request failed with HTTP {error.code}"
                    ) from error
                last_error = error
            except URLError as error:
                last_error = error

            if attempt == len(delays) - 1:
                break

        raise DataLabError("DataLab request failed after retries") from last_error

    def fetch_daily_ratios(
        self,
        keywords: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[str, dict[date, float]]:
        unique: list[str] = []
        seen: set[str] = set()
        for keyword in keywords:
            normalized = normalize_keyword(keyword)
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique.append(keyword)

        if not unique:
            return {}
        if len(unique) > 5:
            raise ValueError("DataLab supports at most five keyword groups per request")
        payload = self._request(unique, start_date, end_date)
        return normalize_series(payload, unique, start_date, end_date)
