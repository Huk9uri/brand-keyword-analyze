from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterator, Mapping
from html.parser import HTMLParser
from typing import Any

from .models import CollectedKeyword, ParsedKeywordList


_MAX_SERIALIZED_DEPTH = 4
_APOLLO_PLACE_DETAIL_PREFIX = "PlaceDetailBase:"


class KeywordListParseError(ValueError):
    pass


class PlaceMismatchError(KeywordListParseError):
    pass


def normalize_keyword(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_script = False
        self._parts: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "script":
            self._in_script = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._in_script:
            self.scripts.append("".join(self._parts))
            self._in_script = False
            self._parts = []


def _json_value_candidates(text: str) -> Iterator[tuple[Any, int]]:
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        if text[index] not in '{["-0123456789tfn':
            index += 1
            continue
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index += 1
            continue
        yield value, index
        index = max(end, index + 1)


def _json_values(text: str) -> Iterator[Any]:
    """Yield complete JSON values embedded in a JavaScript payload."""

    for value, _ in _json_value_candidates(text):
        yield value


def _is_logical_root_start(text: str, index: int) -> bool:
    prefix = text[:index].rstrip()
    return not prefix or prefix[-1] in "=;("


def _decode_structural_quote_entities(text: str) -> str:
    decoded = text
    for entity in ("&quot;", "&#34;", "&#x22;", "&#X22;"):
        decoded = decoded.replace(entity, '"')
    return decoded


def _mappings_from_text(text: str, depth: int) -> Iterator[Mapping[str, Any]]:
    for mapping, _ in _mappings_with_place_context_from_text(
        text,
        depth,
        inherited_cache_key=None,
        may_establish_cache_context=True,
    ):
        yield mapping


def _single_top_level_place_detail_cache_key(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None

    cache_keys = tuple(
        key
        for key in value
        if isinstance(key, str) and key.startswith(_APOLLO_PLACE_DETAIL_PREFIX)
    )
    if len(cache_keys) != 1:
        return None
    return cache_keys[0]


def _mappings_with_place_context_from_text(
    text: str,
    depth: int,
    inherited_cache_key: str | None,
    may_establish_cache_context: bool,
) -> Iterator[tuple[Mapping[str, Any], str | None]]:
    mappings = [
        candidate
        for value, index in _json_value_candidates(text)
        for can_establish_cache_context in (
            may_establish_cache_context and _is_logical_root_start(text, index),
        )
        for candidate in _walk_structures_with_place_context(
            value,
            depth,
            (
                _single_top_level_place_detail_cache_key(value)
                if can_establish_cache_context and isinstance(value, Mapping)
                else inherited_cache_key
            ),
            can_establish_cache_context,
        )
    ]
    if mappings:
        yield from mappings

    emitted = list(mappings)
    structural_candidate = _decode_structural_quote_entities(text)
    if structural_candidate != text:
        for value, index in _json_value_candidates(structural_candidate):
            can_establish_cache_context = (
                may_establish_cache_context
                and _is_logical_root_start(structural_candidate, index)
            )
            for candidate in _walk_structures_with_place_context(
                value,
                depth,
                (
                    _single_top_level_place_detail_cache_key(value)
                    if can_establish_cache_context and isinstance(value, Mapping)
                    else inherited_cache_key
                ),
                can_establish_cache_context,
            ):
                if candidate in emitted:
                    continue
                emitted.append(candidate)
                yield candidate


def _walk_structures(value: Any, depth: int = 0) -> Iterator[Mapping[str, Any]]:
    for mapping, _ in _walk_structures_with_place_context(
        value,
        depth,
        cache_key=None,
        may_establish_cache_context=False,
    ):
        yield mapping


def _walk_structures_with_place_context(
    value: Any,
    depth: int,
    cache_key: str | None,
    may_establish_cache_context: bool,
) -> Iterator[tuple[Mapping[str, Any], str | None]]:
    if isinstance(value, Mapping):
        yield value, cache_key
        for child in value.values():
            yield from _walk_structures_with_place_context(
                child,
                depth,
                cache_key,
                may_establish_cache_context=False,
            )
        return
    if isinstance(value, list):
        for child in value:
            yield from _walk_structures_with_place_context(
                child,
                depth,
                cache_key,
                may_establish_cache_context=False,
            )
        return
    if isinstance(value, str) and depth < _MAX_SERIALIZED_DEPTH:
        yield from _mappings_with_place_context_from_text(
            value,
            depth + 1,
            inherited_cache_key=cache_key,
            may_establish_cache_context=may_establish_cache_context,
        )


def _keyword_rows(values: list[Any]) -> tuple[CollectedKeyword, ...]:
    if not all(isinstance(value, str) for value in values):
        raise KeywordListParseError("keywordList must contain only strings")

    rows: list[CollectedKeyword] = []
    seen: set[str] = set()
    for keyword_order, raw_keyword in enumerate(values, start=1):
        normalized_keyword = normalize_keyword(raw_keyword)
        if not normalized_keyword or normalized_keyword in seen:
            continue
        seen.add(normalized_keyword)
        rows.append(
            CollectedKeyword(
                keyword_order=keyword_order,
                raw_keyword=raw_keyword,
                normalized_keyword=normalized_keyword,
            )
        )
    return tuple(rows)


class KeywordListParser:
    def parse(self, html: str, expected_place_id: str) -> ParsedKeywordList:
        collector = _ScriptCollector()
        collector.feed(html)

        candidate_found = False
        matching_object_found = False
        matching_arrays: list[list[Any]] = []
        expected_cache_key = f"{_APOLLO_PLACE_DETAIL_PREFIX}{expected_place_id}"
        for script in collector.scripts:
            for mapping, cache_key in _mappings_with_place_context_from_text(
                script,
                depth=0,
                inherited_cache_key=None,
                may_establish_cache_context=True,
            ):
                if "keywordList" not in mapping:
                    continue
                candidate_found = True
                internal_id_matches = str(mapping.get("id")) == str(expected_place_id)
                cache_key_matches = cache_key == expected_cache_key
                if not (internal_id_matches or cache_key_matches):
                    continue
                matching_object_found = True
                keyword_list = mapping["keywordList"]
                if keyword_list is None:
                    matching_arrays.append([])
                elif isinstance(keyword_list, list):
                    matching_arrays.append(keyword_list)

        if not matching_arrays:
            if matching_object_found:
                raise KeywordListParseError("matching place has no keywordList array")
            if candidate_found:
                raise PlaceMismatchError(
                    f"keywordList candidates do not match place {expected_place_id}"
                )
            raise KeywordListParseError("no definitive keywordList array found")

        first = matching_arrays[0]
        if any(candidate != first for candidate in matching_arrays[1:]):
            raise KeywordListParseError("matching place has conflicting keywordList arrays")

        return ParsedKeywordList(
            place_id=str(expected_place_id),
            keywords=_keyword_rows(first),
        )
