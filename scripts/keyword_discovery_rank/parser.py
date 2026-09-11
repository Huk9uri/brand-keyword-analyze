from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from .models import ParsedResult, ParsedSearch, SearchPage
from .place_cards import canonical_place_url, is_ad_url, place_id_from_url, semantic_place_cards


PARSER_VERSION = "dom-v5"

RESULT_CARD_SELECTOR = (
    "li[data-nmb_res-doc-id], li[data-nmb_rese-doc-id], "
    "[data-naver-place-card], li.place-result-card, li.VLTHu"
)
DIRECT_PLACE_SELECTOR = "[data-laim-exp-id^='nmb_lpa']"
DETAIL_LINK_SELECTOR = (
    ".SgjqM a[href], a[data-place-name], a[data-place-detail], "
    "a[href*='place.naver.com'], a[href*='ader.naver.com']"
)
NAME_SELECTOR = "[data-place-name], .place-name, .YwYLL, .TYaxT, .IY7ZX"
CATEGORY_SELECTOR = (
    "[data-place-category], .place-category, .category, .YzBgS, .KCMnt, "
    ".HzOD8 > a.dtDQt"
)
DISTANCE_SELECTOR = "[data-place-distance], .place-distance, .distance"
AD_MARKER_SELECTOR = "[data-place-ad], .place-ad, .ad-badge"

_PATH_PLACE_ID = re.compile(r"/(restaurant|place|hospital|hairshop|nailshop)/([^/?#]+)")
_DOC_PLACE_ID = re.compile(r"^(\d+)")


class DomResultParser:
    """Parse rendered Naver Place cards without applying acceptance policy."""

    def parse(self, page: SearchPage) -> ParsedSearch:
        soup = BeautifulSoup(page.html or "", "html.parser")
        from .place_list import list_cards
        cards = list_cards(soup) or soup.select(RESULT_CARD_SELECTOR) or semantic_place_cards(soup)
        if not cards:
            direct_place = soup.select_one(DIRECT_PLACE_SELECTOR)
            cards = [direct_place] if direct_place is not None else []
        results: list[ParsedResult] = []
        next_organic_rank = 1

        for raw_position, card in enumerate(cards, start=1):
            is_ad = _is_ad(card)
            organic_rank = None if is_ad else next_organic_rank
            if not is_ad:
                next_organic_rank += 1

            link = _detail_link(card)
            raw_detail_url = _attribute(link, "href")
            place_id = _place_id_from_card(card) or _place_id_from_url(raw_detail_url)
            detail_url = _canonical_detail_url(raw_detail_url, place_id)
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
    doc_id = _doc_id(card).casefold()
    blind_labels = (
        node.get_text(" ", strip=True).casefold()
        for node in card.select(".place_blind")
    )
    return (
        attribute in {"1", "true", "yes"}
        or any(is_ad_url(_attribute(link, "href")) for link in card.select("a[href]"))
        or "_nad-" in doc_id
        or any(label == "광고" for label in blind_labels)
        or card.select_one(AD_MARKER_SELECTOR) is not None
    )


def _place_name(card: Tag, link: Tag | None) -> str:
    name_node = card.select_one(NAME_SELECTOR)
    if name_node is not None:
        return name_node.get_text(" ", strip=True)
    if link is not None:
        return link.get_text(" ", strip=True)
    return ""


def _detail_link(card: Tag) -> Tag | None:
    candidates = card.select(DETAIL_LINK_SELECTOR)
    for candidate in candidates:
        if _place_id_from_url(_attribute(candidate, "href")):
            return candidate
    return next((candidate for candidate in candidates if _attribute(candidate, "href")), None)


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
    return place_id_from_url(detail_url)


def _doc_id(card: Tag) -> str:
    return _attribute(card, "data-nmb_res-doc-id") or _attribute(
        card, "data-nmb_rese-doc-id"
    )


def _place_id_from_card(card: Tag) -> str:
    explicit = _attribute(card, "data-place-id")
    if explicit:
        return explicit
    matched = _DOC_PLACE_ID.match(_doc_id(card))
    return matched.group(1) if matched else ""


def _canonical_detail_url(detail_url: str, place_id: str) -> str:
    return canonical_place_url(detail_url, place_id)
