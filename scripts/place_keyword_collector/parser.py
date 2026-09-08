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


def _json_values(text: str) -> Iterator[Any]:
    """Yield complete JSON values embedded in a JavaScript payload."""

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
        yield value
        index = max(end, index + 1)


def _decode_structural_quote_entities(text: str) -> str:
    decoded = text
    for entity in ("&quot;", "&#34;", "&#x22;", "&#X22;"):
        decoded = decoded.replace(entity, '"')
    return decoded


def _mappings_from_text(text: str, depth: int) -> Iterator[Mapping[str, Any]]:
    for mapping, _ in _mappings_with_place_context_from_text(
        text,
        depth,
        frozenset(),
    ):
        yield mapping


def _mappings_with_place_context_from_text(
    text: str,
    depth: int,
    containing_cache_keys: frozenset[str],
) -> Iterator[tuple[Mapping[str, Any], frozenset[str]]]:
    mappings = [
        candidate
        for value in _json_values(text)
        for candidate in _walk_structures_with_place_context(
            value,
            depth,
            containing_cache_keys,
        )
    ]
    if mappings:
        yield from mappings

    emitted = list(mappings)
    structural_candidate = _decode_structural_quote_entities(text)
    if structural_candidate != text:
        for value in _json_values(structural_candidate):
            for candidate in _walk_structures_with_place_context(
                value,
                depth,
                containing_cache_keys,
            ):
                if candidate in emitted:
                    continue
                emitted.append(candidate)
                yield candidate


def _walk_structures(value: Any, depth: int = 0) -> Iterator[Mapping[str, Any]]:
    for mapping, _ in _walk_structures_with_place_context(
        value,
        depth,
        frozenset(),
    ):
        yield mapping


def _walk_structures_with_place_context(
    value: Any,
    depth: int,
    containing_cache_keys: frozenset[str],
) -> Iterator[tuple[Mapping[str, Any], frozenset[str]]]:
    if isinstance(value, Mapping):
        local_cache_keys = frozenset(
            key
            for key in value
            if isinstance(key, str) and key.startswith(_APOLLO_PLACE_DETAIL_PREFIX)
        )
        cache_keys = containing_cache_keys | local_cache_keys
        yield value, cache_keys
        for child in value.values():
            yield from _walk_structures_with_place_context(child, depth, cache_keys)
        return
    if isinstance(value, list):
        for child in value:
            yield from _walk_structures_with_place_context(
                child,
                depth,
                containing_cache_keys,
            )
        return
    if isinstance(value, str) and depth < _MAX_SERIALIZED_DEPTH:
        yield from _mappings_with_place_context_from_text(
            value,
            depth + 1,
            containing_cache_keys,
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
            for mapping, containing_cache_keys in _mappings_with_place_context_from_text(
                script,
                depth=0,
                containing_cache_keys=frozenset(),
            ):
                if "keywordList" not in mapping:
                    continue
                candidate_found = True
                internal_id_matches = str(mapping.get("id")) == str(expected_place_id)
                cache_key_matches = expected_cache_key in containing_cache_keys
                if not (internal_id_matches or cache_key_matches):
                    continue
                matching_object_found = True
                keyword_list = mapping["keywordList"]
                if isinstance(keyword_list, list):
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
