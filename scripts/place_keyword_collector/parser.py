from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterator, Mapping
from html.parser import HTMLParser
from typing import Any

from .models import CollectedKeyword, ParsedKeywordList


_MAX_SERIALIZED_DEPTH = 4


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
    mappings = [
        mapping
        for value in _json_values(text)
        for mapping in _walk_structures(value, depth)
    ]
    if mappings:
        yield from mappings

    emitted = list(mappings)
    structural_candidate = _decode_structural_quote_entities(text)
    if structural_candidate != text:
        for value in _json_values(structural_candidate):
            for mapping in _walk_structures(value, depth):
                if mapping in emitted:
                    continue
                emitted.append(mapping)
                yield mapping


def _walk_structures(value: Any, depth: int = 0) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_structures(child, depth)
        return
    if isinstance(value, list):
        for child in value:
            yield from _walk_structures(child, depth)
        return
    if isinstance(value, str) and depth < _MAX_SERIALIZED_DEPTH:
        yield from _mappings_from_text(value, depth + 1)


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
        for script in collector.scripts:
            for mapping in _mappings_from_text(script, depth=0):
                if "keywordList" not in mapping:
                    continue
                candidate_found = True
                if str(mapping.get("id")) != str(expected_place_id):
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
