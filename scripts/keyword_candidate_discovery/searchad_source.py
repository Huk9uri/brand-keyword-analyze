from __future__ import annotations

import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scripts.yuksudang_volume.searchad import (
    KEYWORD_TOOL_URI, SEARCHAD_BASE_URL, build_hint_keywords, build_signature, normalize_keyword,
)


def parse_related_keywords(payload: dict, *, seed_keywords: tuple[str, ...]) -> tuple[str, ...]:
    seed_keys = {normalize_keyword(keyword) for keyword in seed_keywords}
    seen = set(seed_keys)
    related: list[str] = []
    for row in payload.get("keywordList", []):
        keyword = str(row.get("relKeyword") or "").strip()
        normalized = normalize_keyword(keyword)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        related.append(keyword)
    return tuple(related)


class SearchAdRelatedClient:
    def __init__(self, customer_id: str, api_key: str, secret_key: str, *, timeout_seconds: float = 20.0):
        self._customer_id = customer_id
        self._api_key = api_key
        self._secret_key = secret_key
        self._timeout_seconds = timeout_seconds

    def fetch_related(self, seed_keywords: tuple[str, ...]) -> tuple[str, ...]:
        if not seed_keywords:
            return ()
        params = urlencode({"hintKeywords": build_hint_keywords(list(seed_keywords[:5])), "showDetail": "1"})
        timestamp = str(int(time.time() * 1000))
        request = Request(
            f"{SEARCHAD_BASE_URL}{KEYWORD_TOOL_URI}?{params}",
            method="GET",
            headers={
                "X-Timestamp": timestamp,
                "X-API-KEY": self._api_key,
                "X-Customer": self._customer_id,
                "X-Signature": build_signature(timestamp, "GET", KEYWORD_TOOL_URI, self._secret_key),
            },
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return parse_related_keywords(payload, seed_keywords=seed_keywords)

