from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
import unicodedata

from .models import MatchMethod, ParsedResult


@dataclass(frozen=True)
class OwnStore:
    """Canonical identity for one store owned by the brand."""

    store_id: str
    store_name: str
    place_id: str | None = None


@dataclass(frozen=True)
class MatchDecision:
    is_own_store: bool
    matched_store_id: str | None
    match_method: MatchMethod

    def apply_to(self, result: ParsedResult) -> ParsedResult:
        """Return a matched copy without mutating the parsed card."""

        return replace(
            result,
            is_own_store=self.is_own_store,
            matched_store_id=self.matched_store_id,
            match_method=self.match_method,
        )


class OwnStoreMatcher:
    """Identify owned stores from authoritative IDs before conservative names."""

    def __init__(
        self,
        own_stores: Iterable[OwnStore],
        *,
        manual_place_id_mappings: Mapping[str, str] | None = None,
    ) -> None:
        own_stores = tuple(own_stores)
        stores_by_id = {store.store_id: store for store in own_stores}
        if len(stores_by_id) != len(own_stores):
            raise ValueError("own store IDs must be unique")

        place_id_matches = _index_unique(
            (store.place_id, store.store_id) for store in own_stores if store.place_id
        )
        manual_matches = {
            place_id: store_id
            for place_id, store_id in (manual_place_id_mappings or {}).items()
            if place_id
        }
        unknown_store_ids = set(manual_matches.values()) - set(stores_by_id)
        if unknown_store_ids:
            raise ValueError("manual mappings must reference configured own stores")

        self._place_id_matches = MappingProxyType(place_id_matches)
        self._manual_matches = MappingProxyType(manual_matches)
        self._exact_name_matches = MappingProxyType(
            _index_unique((store.store_name, store.store_id) for store in own_stores)
        )
        self._normalized_name_matches = MappingProxyType(
            _index_unique((_normalize_name(store.store_name), store.store_id) for store in own_stores)
        )

    def match(self, result: ParsedResult) -> MatchDecision:
        place_id = result.place_id
        if place_id in self._place_id_matches:
            return _matched(self._place_id_matches[place_id], MatchMethod.PLACE_ID)
        if place_id in self._manual_matches:
            return _matched(self._manual_matches[place_id], MatchMethod.MANUAL_MAPPING)

        exact_store_id = self._exact_name_matches.get(result.place_name)
        if exact_store_id is not None:
            return _matched(exact_store_id, MatchMethod.EXACT_NAME)

        normalized_store_id = self._normalized_name_matches.get(_normalize_name(result.place_name))
        if normalized_store_id is not None:
            return _matched(normalized_store_id, MatchMethod.NORMALIZED_NAME)
        return MatchDecision(False, None, MatchMethod.NONE)


def _index_unique(entries: Iterable[tuple[str | None, str]]) -> dict[str, str]:
    matches: dict[str, str | None] = {}
    for key, store_id in entries:
        if not key:
            continue
        if key in matches and matches[key] != store_id:
            matches[key] = None
        else:
            matches[key] = store_id
    return {key: store_id for key, store_id in matches.items() if store_id is not None}


def _matched(store_id: str, match_method: MatchMethod) -> MatchDecision:
    return MatchDecision(True, store_id, match_method)


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return "".join(
        character
        for character in normalized
        if not character.isspace() and not unicodedata.category(character).startswith("P")
    )
