from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from scripts.keyword_discovery_rank.models import (
    CollectStatus,
    DeviceType,
    MatchMethod,
    ParsedResult,
    ParsedSearch,
    SearchPage,
    SearchSnapshot,
    SearchTask,
    SourceType,
)


def test_enums_expose_persisted_contract_values():
    assert [member.value for member in DeviceType] == ["MOBILE", "PC"]
    assert [member.value for member in SourceType] == ["EXCEL", "DATABASE"]
    assert [member.value for member in CollectStatus] == [
        "SUCCESS",
        "NO_RESULT",
        "PARTIAL",
        "LOAD_TIMEOUT",
        "QUERY_MISMATCH",
        "PARSER_ERROR",
        "SEARCH_ERROR",
        "VALIDATION_ERROR",
        "LOCATION_RESOLVE_ERROR",
    ]
    assert [member.value for member in MatchMethod] == [
        "PLACE_ID",
        "MANUAL_MAPPING",
        "EXACT_NAME",
        "NORMALIZED_NAME",
        "NONE",
    ]


def test_search_task_defaults_to_mobile():
    task = SearchTask(
        "row-2",
        "선릉역 국밥",
        "S1",
        "육수당 선릉점",
        "선릉점",
        37.5048,
        127.0489,
        SourceType.EXCEL,
        "2",
    )

    assert task.device_type is DeviceType.MOBILE


def test_boundary_models_are_immutable_and_preserve_result_defaults():
    task = SearchTask(
        "row-2",
        "선릉역 국밥",
        "S1",
        "육수당 선릉점",
        "선릉점",
        37.5048,
        127.0489,
        SourceType.EXCEL,
        "2",
    )
    result = ParsedResult(1, 1, "123", "육수당 선릉점", "국밥", False, "https://m.place.naver.com/123", "100m")
    page = SearchPage("https://m.search.naver.com", "<html />", "RESULTS", 1, True)
    parsed = ParsedSearch((result,), 1, True)
    snapshot = SearchSnapshot(
        "run-1",
        "a" * 64,
        task,
        "선릉역 국밥",
        20,
        page.observed_result_count,
        parsed.result_end_reached,
        CollectStatus.SUCCESS,
        None,
        "dom-v1",
        page.final_url,
        datetime(2026, 9, 2, 12, 0, 0),
    )

    assert (result.is_own_store, result.matched_store_id, result.match_method) == (False, None, MatchMethod.NONE)
    assert snapshot.task is task
    with pytest.raises(FrozenInstanceError):
        task.query = "변경"
    with pytest.raises(FrozenInstanceError):
        result.is_ad = True
    with pytest.raises(FrozenInstanceError):
        page.state = "ERROR"
    with pytest.raises(FrozenInstanceError):
        parsed.observed_result_count = 0
    with pytest.raises(FrozenInstanceError):
        snapshot.collect_status = CollectStatus.PARTIAL
