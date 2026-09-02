from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DeviceType(str, Enum):
    MOBILE = "MOBILE"
    PC = "PC"


class SourceType(str, Enum):
    EXCEL = "EXCEL"
    DATABASE = "DATABASE"


class CollectStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NO_RESULT = "NO_RESULT"
    PARTIAL = "PARTIAL"
    LOAD_TIMEOUT = "LOAD_TIMEOUT"
    QUERY_MISMATCH = "QUERY_MISMATCH"
    PARSER_ERROR = "PARSER_ERROR"
    SEARCH_ERROR = "SEARCH_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class MatchMethod(str, Enum):
    PLACE_ID = "PLACE_ID"
    MANUAL_MAPPING = "MANUAL_MAPPING"
    EXACT_NAME = "EXACT_NAME"
    NORMALIZED_NAME = "NORMALIZED_NAME"
    NONE = "NONE"


@dataclass(frozen=True)
class SearchTask:
    task_id: str
    query: str
    target_store_id: str
    target_store_name: str
    location_name: str
    latitude: float
    longitude: float
    source_type: SourceType
    source_id: str
    device_type: DeviceType = DeviceType.MOBILE


@dataclass(frozen=True)
class SearchPage:
    final_url: str
    html: str
    state: str
    observed_result_count: int
    result_end_reached: bool


@dataclass(frozen=True)
class ParsedResult:
    raw_position: int
    organic_rank: int | None
    place_id: str
    place_name: str
    category: str | None
    is_ad: bool
    detail_url: str
    distance_text: str | None
    is_own_store: bool = False
    matched_store_id: str | None = None
    match_method: MatchMethod = MatchMethod.NONE


@dataclass(frozen=True)
class ParsedSearch:
    results: tuple[ParsedResult, ...]
    observed_result_count: int
    result_end_reached: bool


@dataclass(frozen=True)
class SearchSnapshot:
    run_id: str
    task_key: str
    task: SearchTask
    normalized_query: str
    requested_result_limit: int
    observed_result_count: int
    result_end_reached: bool
    collect_status: CollectStatus
    collect_msg: str | None
    parser_version: str
    final_url: str
    collected_at: datetime
