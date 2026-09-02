from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from .models import ParsedResult, ParsedSearch, SearchPage


PARSER_VERSION = "dom-v1"

RESULT_CARD_SELECTOR = "[data-naver-place-card], li.place-result-card, li.VLTHu"
DETAIL_LINK_SELECTOR = "a[data-place-name], a[data-place-detail], a[href*='place.naver.com']"
NAME_SELECTOR = "[data-place-name], .place-name, .YwYLL, .TYaxT"
CATEGORY_SELECTOR = "[data-place-category], .place-category, .category, .YzBgS"
DISTANCE_SELECTOR = "[data-place-distance], .place-distance, .distance"
AD_MARKER_SELECTOR = "[data-place-ad], .place-ad, .ad-badge"

_PATH_PLACE_ID = re.compile(r"/(?:restaurant|place|hospital|hairshop|nailshop)/([^/?#]+)")


class DomResultParser:
    """Parse rendered Naver Place cards without applying acceptance policy."""

    def parse(self, page: SearchPage) -> ParsedSearch:
        soup = BeautifulSoup(page.html or "", "html.parser")
        cards = soup.select(RESULT_CARD_SELECTOR)
        results: list[ParsedResult] = []
        next_organic_rank = 1

        for raw_position, card in enumerate(cards, start=1):
            is_ad = _is_ad(card)
            organic_rank = None if is_ad else next_organic_rank
            if not is_ad:
                next_organic_rank += 1

            link = card.select_one(DETAIL_LINK_SELECTOR)
            detail_url = _attribute(link, "href")
            place_id = _attribute(card, "data-place-id") or _place_id_from_url(detail_url)
            results.append(
                ParsedResult(
                    raw_position=raw_position,
                    organic_rank=organic_rank,
                    place_id=place_id,
                    place_name=_place_name(card, link),
                    category=_optional_text(card, CATEGORY_SELECTOR),
                    is_ad=is_ad,
                    detail_url=detail_url,
                    distance_text=_optional_text(card, DISTANCE_SELECTOR),
                )
            )

        return ParsedSearch(
            results=tuple(results),
            observed_result_count=page.observed_result_count,
            result_end_reached=page.result_end_reached,
        )


def _is_ad(card: Tag) -> bool:
    attribute = _attribute(card, "data-is-ad").casefold()
    return attribute in {"1", "true", "yes"} or card.select_one(AD_MARKER_SELECTOR) is not None


def _place_name(card: Tag, link: Tag | None) -> str:
    name_node = card.select_one(NAME_SELECTOR)
    if name_node is not None:
        return name_node.get_text(" ", strip=True)
    if link is not None:
        return link.get_text(" ", strip=True)
    return ""


def _optional_text(card: Tag, selector: str) -> str | None:
    node = card.select_one(selector)
    if node is None:
        return None
    value = node.get_text(" ", strip=True)
    return value or None


def _attribute(node: Tag | None, name: str) -> str:
    if node is None:
        return ""
    value = node.get(name)
    return value.strip() if isinstance(value, str) else ""


def _place_id_from_url(detail_url: str) -> str:
    if not detail_url:
        return ""
    parsed = urlparse(detail_url)
    matched = _PATH_PLACE_ID.search(parsed.path)
    if matched:
        return matched.group(1)
    query = parse_qs(parsed.query)
    for key in ("placeId", "place_id", "id"):
        values = query.get(key)
        if values:
            return values[0]
    return ""
