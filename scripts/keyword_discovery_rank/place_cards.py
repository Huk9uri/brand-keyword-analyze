from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag


_PATH_PLACE_ID = re.compile(r"/(restaurant|place|hospital|hairshop|nailshop)/([^/?#]+)")
_PLACE_HOSTS = {"m.place.naver.com", "place.naver.com"}


def destination_url(href: str) -> str:
    parsed = urlparse(href or "")
    if parsed.netloc.casefold() == "ader.naver.com":
        destinations = parse_qs(parsed.query).get("fu", ())
        return destinations[0] if destinations else ""
    return href or ""


def place_id_from_url(href: str) -> str:
    candidate = destination_url(href)
    parsed = urlparse(candidate)
    if parsed.netloc.casefold() not in _PLACE_HOSTS:
        return ""
    matched = _PATH_PLACE_ID.search(parsed.path)
    return matched.group(2) if matched else ""


def canonical_place_url(href: str, place_id: str = "") -> str:
    candidate = destination_url(href)
    parsed = urlparse(candidate)
    matched = _PATH_PLACE_ID.search(parsed.path)
    if parsed.scheme.casefold() == "https" and parsed.netloc.casefold() in _PLACE_HOSTS and matched:
        return f"https://m.place.naver.com/{matched.group(1)}/{matched.group(2)}"
    return f"https://m.place.naver.com/restaurant/{place_id}" if place_id else ""


def semantic_place_cards(soup: BeautifulSoup) -> list[Tag]:
    cards: list[Tag] = []
    seen: set[int] = set()
    for link in soup.select("a[href]"):
        href = link.get("href")
        if not isinstance(href, str) or not place_id_from_url(href):
            continue
        card = link.find_parent("li")
        if card is None or not _inside_place_section(card) or id(card) in seen:
            continue
        seen.add(id(card))
        cards.append(card)
    return cards


def _inside_place_section(card: Tag) -> bool:
    for depth, ancestor in enumerate(card.parents):
        if depth >= 8 or not isinstance(ancestor, Tag):
            break
        for heading in ancestor.find_all(("h1", "h2", "h3"), recursive=False):
            if heading.get_text(" ", strip=True).startswith("플레이스"):
                return True
    return False


def is_ad_url(href: str) -> bool:
    return urlparse(href or "").netloc.casefold() == "ader.naver.com"
