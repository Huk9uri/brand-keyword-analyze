from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .models import DeviceType, SearchTask, SourceType


EXCEL_HEADERS = (
    "검색어",
    "기준매장ID",
    "기준매장명",
    "조회위치명",
    "위도",
    "경도",
    "기기",
    "소스ID",
)
REQUIRED_EXCEL_HEADERS = EXCEL_HEADERS[:6]


class InputValidationError(ValueError):
    """Raised when one or more input rows cannot become search tasks."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("input validation failed:\n" + "\n".join(self.errors))


class TaskSource(ABC):
    @abstractmethod
    def load(self) -> list[SearchTask]:
        """Load, validate, and deduplicate search tasks."""


class ExcelTaskSource(TaskSource):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> list[SearchTask]:
        workbook = load_workbook(self.path, read_only=True, data_only=True)
        try:
            worksheet = workbook["검색작업"] if "검색작업" in workbook.sheetnames else workbook.active
            rows = worksheet.iter_rows(values_only=True)
            try:
                header_row = next(rows)
            except StopIteration as exc:
                raise InputValidationError(["row 1: header row is required"]) from exc

            headers = {str(value).strip(): index for index, value in enumerate(header_row) if value is not None}
            missing_headers = [header for header in REQUIRED_EXCEL_HEADERS if header not in headers]
            if missing_headers:
                raise InputValidationError(["row 1: missing required headers: " + ", ".join(missing_headers)])

            tasks: list[SearchTask] = []
            errors: list[str] = []
            seen_task_keys: set[str] = set()
            for row_number, row in enumerate(rows, start=2):
                values = {header: _value_at(row, headers.get(header)) for header in EXCEL_HEADERS}
                if not any(value is not None and str(value).strip() for value in values.values()):
                    continue
                source_id = _text(values["소스ID"]) or f"excel-row-{row_number}"
                task, row_errors = _build_task(
                    values={
                        "query": values["검색어"],
                        "target_store_id": values["기준매장ID"],
                        "target_store_name": values["기준매장명"],
                        "location_name": values["조회위치명"],
                        "latitude": values["위도"],
                        "longitude": values["경도"],
                        "device_type": values["기기"],
                    },
                    task_id=source_id,
                    source_type=SourceType.EXCEL,
                    source_id=source_id,
                )
                if row_errors:
                    errors.extend(f"row {row_number}: {error}" for error in row_errors)
                    continue
                assert task is not None
                task_key = build_task_key(task)
                if task_key not in seen_task_keys:
                    seen_task_keys.add(task_key)
                    tasks.append(task)

            if errors:
                raise InputValidationError(errors)
            return tasks
        finally:
            workbook.close()


class DatabaseTaskSource(TaskSource):
    """Adapt database candidate records without exposing their column names downstream."""

    def __init__(self, cursor: Any, query: str) -> None:
        self.cursor = cursor
        self.query = query

    def load(self) -> list[SearchTask]:
        self.cursor.execute(self.query)
        rows = self.cursor.fetchall()
        columns = _cursor_columns(self.cursor)
        tasks: list[SearchTask] = []
        errors: list[str] = []
        seen_task_keys: set[str] = set()
        for row_number, row in enumerate(rows, start=1):
            record = _row_mapping(row, columns)
            source_id = _text(record.get("candidate_id")) or f"database-row-{row_number}"
            task, row_errors = _build_task(
                values={
                    "query": record.get("candidate_keyword"),
                    "target_store_id": record.get("store_code"),
                    "target_store_name": record.get("store_display_name"),
                    "location_name": record.get("search_location"),
                    "latitude": record.get("search_latitude"),
                    "longitude": record.get("search_longitude"),
                    "device_type": record.get("device_code"),
                },
                task_id=f"database-{source_id}",
                source_type=SourceType.DATABASE,
                source_id=source_id,
            )
            if row_errors:
                errors.extend(f"database row {row_number}: {error}" for error in row_errors)
                continue
            assert task is not None
            task_key = build_task_key(task)
            if task_key not in seen_task_keys:
                seen_task_keys.add(task_key)
                tasks.append(task)

        if errors:
            raise InputValidationError(errors)
        return tasks


def normalize_query(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def build_task_key(task: SearchTask) -> str:
    key = "|".join(
        (
            normalize_query(task.query),
            task.target_store_id,
            f"{task.latitude:.7f}",
            f"{task.longitude:.7f}",
            task.device_type.value,
        )
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _build_task(
    values: Mapping[str, object],
    *,
    task_id: str,
    source_type: SourceType,
    source_id: str,
) -> tuple[SearchTask | None, list[str]]:
    query = normalize_query(_text(values.get("query")))
    target_store_id = _text(values.get("target_store_id"))
    target_store_name = _text(values.get("target_store_name"))
    location_name = _text(values.get("location_name"))
    latitude, latitude_error = _coordinate(values.get("latitude"), "latitude", -90, 90)
    longitude, longitude_error = _coordinate(values.get("longitude"), "longitude", -180, 180)
    device_type, device_error = _device_type(values.get("device_type"))

    errors = []
    for value, name in (
        (query, "query"),
        (target_store_id, "target_store_id"),
        (target_store_name, "target_store_name"),
        (location_name, "location_name"),
    ):
        if not value:
            errors.append(f"{name} is required")
    if latitude_error:
        errors.append(latitude_error)
    if longitude_error:
        errors.append(longitude_error)
    if device_error:
        errors.append(device_error)
    if errors:
        return None, errors

    assert latitude is not None and longitude is not None and device_type is not None
    return (
        SearchTask(
            task_id=task_id,
            query=query,
            target_store_id=target_store_id,
            target_store_name=target_store_name,
            location_name=location_name,
            latitude=latitude,
            longitude=longitude,
            source_type=source_type,
            source_id=source_id,
            device_type=device_type,
        ),
        [],
    )


def _coordinate(value: object, name: str, lower: float, upper: float) -> tuple[float | None, str | None]:
    try:
        if isinstance(value, bool) or value is None or _text(value) == "":
            raise ValueError
        coordinate = float(value)
    except (TypeError, ValueError):
        return None, f"{name} must be a number"
    if not math.isfinite(coordinate) or not lower <= coordinate <= upper:
        return None, f"{name} must be between {lower:g} and {upper:g}"
    return coordinate, None


def _device_type(value: object) -> tuple[DeviceType | None, str | None]:
    normalized = _text(value).upper()
    if not normalized:
        return DeviceType.MOBILE, None
    try:
        return DeviceType(normalized), None
    except ValueError:
        return None, "device must be MOBILE or PC"


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _value_at(row: tuple[object, ...], index: int | None) -> object | None:
    return row[index] if index is not None and index < len(row) else None


def _cursor_columns(cursor: Any) -> tuple[str, ...] | None:
    description = getattr(cursor, "description", None)
    if not description:
        return None
    return tuple(column[0] for column in description)


def _row_mapping(row: object, columns: tuple[str, ...] | None) -> Mapping[str, object]:
    if isinstance(row, Mapping):
        return row
    if columns is None:
        raise TypeError("database cursor rows must be mappings or expose cursor.description")
    return dict(zip(columns, row, strict=True))
