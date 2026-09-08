from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
from uuid import UUID


_NAVER_PLACE_ID = re.compile(r"[0-9]+")


def normalize_place_id(value: object) -> str:
    place_id = str(value).strip() if value is not None else ""
    if _NAVER_PLACE_ID.fullmatch(place_id) is None:
        raise ValueError("place_id must be a numeric Naver Place ID")
    return place_id


def normalize_uuid(value: object, field_name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"{field_name} must be a UUID") from None


class RefreshPolicy(str, Enum):
    MONTHLY = "MONTHLY"
    WEEKLY = "WEEKLY"


class KeywordCollectStatus(str, Enum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    BLOCKED = "BLOCKED"
    LOAD_TIMEOUT = "LOAD_TIMEOUT"
    PLACE_MISMATCH = "PLACE_MISMATCH"
    PARSE_ERROR = "PARSE_ERROR"


@dataclass(frozen=True)
class RankPlaceTarget:
    place_id: str
    place_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "place_id", normalize_place_id(self.place_id))


@dataclass(frozen=True)
class CollectedKeyword:
    keyword_order: int
    raw_keyword: str
    normalized_keyword: str


@dataclass(frozen=True)
class ParsedKeywordList:
    place_id: str
    keywords: tuple[CollectedKeyword, ...]


@dataclass(frozen=True)
class PreviousVersion:
    effective_snapshot_id: int
    content_hash: str
    checked_at: datetime
    status: KeywordCollectStatus


@dataclass(frozen=True)
class KeywordSnapshot:
    snapshot_id: int
    run_id: str
    rank_run_id: str
    target: RankPlaceTarget
    source_url: str
    status: KeywordCollectStatus
    content_hash: str | None
    is_changed: bool
    effective_snapshot_id: int | None
    keyword_count: int
    parser_version: str
    collect_msg: str | None
    checked_at: datetime


@dataclass(frozen=True)
class CollectionSummary:
    run_id: str
    rank_run_id: str
    target_count: int
    success_count: int
    empty_count: int
    failed_count: int
