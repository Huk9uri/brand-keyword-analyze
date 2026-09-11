from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from .models import CollectStatus, ParsedResult, ParsedSearch


_PATH_PLACE_ID = re.compile(r"/(?:restaurant|place|hospital|hairshop|nailshop)/([^/?#]+)")


@dataclass(frozen=True)
class ValidationOutcome:
    status: CollectStatus
    results: tuple[ParsedResult, ...]
    message: str | None
    observed_result_count: int


class ResultValidator:
    """Validate the persistable visible prefix and classify its collection status."""

    def __init__(self, *, organic_limit: bool = False):
        self.organic_limit = organic_limit

    def validate(self, parsed: ParsedSearch, requested_limit: int) -> ValidationOutcome:
        if isinstance(requested_limit, bool) or not isinstance(requested_limit, int) or requested_limit <= 0:
            raise ValueError("requested_limit must be a positive integer")

        observed = parsed.observed_result_count
        if observed < 0:
            return self._error(observed, "observed_result_count must not be negative")
        if len(parsed.results) > observed:
            return self._error(
                observed,
                "parsed result count exceeds observed_result_count",
            )

        prefix_length = requested_limit
        if self.organic_limit:
            prefix_length = len(parsed.results)
            organic_count = 0
            for index, row in enumerate(parsed.results):
                organic_count += not row.is_ad
                if organic_count >= requested_limit:
                    prefix_length = index + 1
                    break
        visible_results = parsed.results[:prefix_length]
        invariant_error = _find_invariant_error(visible_results)
        if invariant_error is not None:
            return self._error(observed, invariant_error)

        if observed == 0 and not visible_results:
            if parsed.result_end_reached:
                return ValidationOutcome(CollectStatus.NO_RESULT, (), None, observed)
            return ValidationOutcome(
                CollectStatus.PARTIAL,
                (),
                "empty results were not confirmed by an end marker",
                observed,
            )

        valid_results = tuple(row for row in visible_results if _has_required_fields(row))
        messages: list[str] = []
        malformed_count = len(visible_results) - len(valid_results)
        if malformed_count:
            messages.append(f"{malformed_count} malformed required card(s)")

        expected_visible_count = min(observed, requested_limit)
        unparsed_count = (max(0, observed - len(parsed.results)) if self.organic_limit
                          else max(0, expected_visible_count - len(visible_results)))
        if unparsed_count:
            messages.append(f"{unparsed_count} rendered card(s) were not parsed")

        reached_requested_limit = (sum(not row.is_ad for row in valid_results) >= requested_limit
                                   if self.organic_limit else observed >= requested_limit)
        if not reached_requested_limit and not parsed.result_end_reached:
            messages.append("short results were not confirmed by an end marker")

        status = CollectStatus.PARTIAL if messages else CollectStatus.SUCCESS
        return ValidationOutcome(
            status=status,
            results=valid_results,
            message="; ".join(messages) or None,
            observed_result_count=observed,
        )

    @staticmethod
    def _error(observed: int, message: str) -> ValidationOutcome:
        return ValidationOutcome(CollectStatus.VALIDATION_ERROR, (), message, observed)


def _find_invariant_error(results: tuple[ParsedResult, ...]) -> str | None:
    raw_positions = [row.raw_position for row in results]
    expected_positions = list(range(1, len(results) + 1))
    if raw_positions != expected_positions:
        return f"raw_position must be continuous from 1; got {raw_positions}"

    for row in results:
        if row.is_ad and row.organic_rank is not None:
            return f"advertisement at raw_position {row.raw_position} must not have organic_rank"

    organic_ranks = [row.organic_rank for row in results if not row.is_ad]
    non_null_ranks = [rank for rank in organic_ranks if rank is not None]
    if len(non_null_ranks) != len(set(non_null_ranks)):
        return f"duplicate organic_rank in {non_null_ranks}"
    expected_ranks = list(range(1, len(organic_ranks) + 1))
    if organic_ranks != expected_ranks:
        return f"organic_rank must be continuous from 1; got {organic_ranks}"

    for row in results:
        if not row.place_id.strip() or not row.detail_url.strip():
            continue
        url_place_id = _place_id_from_url(row.detail_url)
        if url_place_id != row.place_id.strip():
            return (
                f"URL place ID mismatch at raw_position {row.raw_position}: "
                f"card={row.place_id.strip()!r}, url={url_place_id!r}"
            )
    return None


def _has_required_fields(row: ParsedResult) -> bool:
    return bool(row.place_id.strip() and row.place_name.strip() and row.detail_url.strip())


def _place_id_from_url(detail_url: str) -> str:
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
