from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .models import CollectStatus, ParsedResult, SearchSnapshot
from .place_location import PlaceLocation


LOCATION_SELECT_SQL = """
SELECT place_id, latitude, longitude, resolved_at, verified_at, resolver_version
FROM dbo.naver_place_location
WHERE place_id = %s
"""

LOCATION_UPSERT_SQL = """
MERGE dbo.naver_place_location AS target
USING (SELECT %s AS place_id) AS source
ON target.place_id = source.place_id
WHEN MATCHED THEN UPDATE SET
    latitude = %s, longitude = %s, verified_at = %s, resolver_version = %s
WHEN NOT MATCHED THEN INSERT
    (place_id, latitude, longitude, resolved_at, verified_at, resolver_version)
VALUES (%s, %s, %s, %s, %s, %s);
"""

LOCATION_SCHEMA_COLUMNS_SQL = """
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
       NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'naver_place_location'
ORDER BY COLUMN_NAME
"""

EXPECTED_LOCATION_SCHEMA_COLUMNS = {
    "latitude": ("decimal", None, 10, 7, "NO"),
    "longitude": ("decimal", None, 10, 7, "NO"),
    "place_id": ("varchar", 50, None, None, "NO"),
    "resolved_at": ("datetime2", None, None, None, "NO"),
    "resolver_version": ("varchar", 30, None, None, "NO"),
    "verified_at": ("datetime2", None, None, None, "NO"),
}


class RepositoryError(RuntimeError):
    """Raised when a snapshot transaction cannot be persisted safely."""


class FatalRepositoryError(RepositoryError):
    """A connection, authorization, target, or schema failure that must stop the run."""


class TaskPersistenceError(RepositoryError):
    """A data failure isolated to one final task result."""


SNAPSHOT_INSERT_SQL = """
INSERT INTO dbo.naver_keyword_discovery_snapshot (
    run_id,
    task_key,
    query,
    normalized_query,
    target_store_id,
    target_store_name,
    location_name,
    latitude,
    longitude,
    device_type,
    source_type,
    source_id,
    requested_result_limit,
    observed_result_count,
    result_end_reached,
    collect_status,
    collect_msg,
    parser_version,
    final_url,
    collected_at
)
OUTPUT INSERTED.snapshot_id
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

RESULT_INSERT_SQL = """
INSERT INTO dbo.naver_keyword_discovery_result (
    snapshot_id,
    raw_position,
    organic_rank,
    place_id,
    place_name,
    category,
    is_ad,
    detail_url,
    distance_text,
    is_own_store,
    matched_store_id,
    match_method
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

RESULT_COUNT_SQL = """
SELECT COUNT(*)
FROM dbo.naver_keyword_discovery_result
WHERE snapshot_id = %s
"""

SCHEMA_COLUMNS_SQL = """
SELECT
    TABLE_NAME,
    COLUMN_NAME,
    DATA_TYPE,
    CHARACTER_MAXIMUM_LENGTH,
    NUMERIC_PRECISION,
    NUMERIC_SCALE,
    IS_NULLABLE,
    CAST(COLUMNPROPERTY(
        OBJECT_ID(QUOTENAME(TABLE_SCHEMA) + '.' + QUOTENAME(TABLE_NAME)),
        COLUMN_NAME,
        'IsIdentity'
    ) AS int) AS is_identity
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dbo'
  AND TABLE_NAME IN ('naver_keyword_discovery_snapshot', 'naver_keyword_discovery_result')
ORDER BY TABLE_NAME, COLUMN_NAME
"""

# INFORMATION_SCHEMA reports character lengths in characters (not sys.columns bytes).
# Signatures are: data type, char length, numeric precision, numeric scale, nullable, identity.
EXPECTED_SCHEMA_COLUMNS = {
    ("naver_keyword_discovery_snapshot", "snapshot_id"): ("bigint", None, 19, 0, "NO", 1),
    ("naver_keyword_discovery_snapshot", "run_id"): ("uniqueidentifier", None, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "task_key"): ("char", 64, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "query"): ("nvarchar", 255, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "normalized_query"): ("nvarchar", 255, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "target_store_id"): ("nvarchar", 100, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "target_store_name"): ("nvarchar", 200, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "location_name"): ("nvarchar", 200, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "latitude"): ("decimal", None, 10, 7, "YES", 0),
    ("naver_keyword_discovery_snapshot", "longitude"): ("decimal", None, 10, 7, "YES", 0),
    ("naver_keyword_discovery_snapshot", "device_type"): ("varchar", 10, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "source_type"): ("varchar", 20, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "source_id"): ("nvarchar", 100, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "requested_result_limit"): ("smallint", None, 5, 0, "NO", 0),
    ("naver_keyword_discovery_snapshot", "observed_result_count"): ("smallint", None, 5, 0, "NO", 0),
    ("naver_keyword_discovery_snapshot", "result_end_reached"): ("bit", None, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "collect_status"): ("varchar", 30, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "collect_msg"): ("nvarchar", 1000, None, None, "YES", 0),
    ("naver_keyword_discovery_snapshot", "parser_version"): ("varchar", 30, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "final_url"): ("nvarchar", 2000, None, None, "NO", 0),
    ("naver_keyword_discovery_snapshot", "collected_at"): ("datetime2", None, None, None, "NO", 0),
    ("naver_keyword_discovery_result", "snapshot_id"): ("bigint", None, 19, 0, "NO", 0),
    ("naver_keyword_discovery_result", "raw_position"): ("smallint", None, 5, 0, "NO", 0),
    ("naver_keyword_discovery_result", "organic_rank"): ("smallint", None, 5, 0, "YES", 0),
    ("naver_keyword_discovery_result", "place_id"): ("varchar", 50, None, None, "NO", 0),
    ("naver_keyword_discovery_result", "place_name"): ("nvarchar", 300, None, None, "NO", 0),
    ("naver_keyword_discovery_result", "category"): ("nvarchar", 300, None, None, "YES", 0),
    ("naver_keyword_discovery_result", "is_ad"): ("bit", None, None, None, "NO", 0),
    ("naver_keyword_discovery_result", "detail_url"): ("nvarchar", 2000, None, None, "NO", 0),
    ("naver_keyword_discovery_result", "distance_text"): ("nvarchar", 100, None, None, "YES", 0),
    ("naver_keyword_discovery_result", "is_own_store"): ("bit", None, None, None, "NO", 0),
    ("naver_keyword_discovery_result", "matched_store_id"): ("nvarchar", 100, None, None, "YES", 0),
    ("naver_keyword_discovery_result", "match_method"): ("varchar", 30, None, None, "NO", 0),
}

_FATAL_SQL_ERROR_CODES = frozenset(
    {53, 207, 208, 229, 233, 4060, 18456, 20002, 20003, 10054, 10060}
)
_TASK_LOCAL_SQL_ERROR_CODES = frozenset({245, 515, 547, 2601, 2627, 2628, 8114, 8152})


class SnapshotRepository:
    def __init__(self, connection: Any):
        self._connection = connection

    def save(
        self,
        snapshot: SearchSnapshot,
        results: Sequence[ParsedResult],
    ) -> int:
        cursor = None
        operation = "snapshot"
        try:
            cursor = self._connection.cursor()
            cursor.execute(SNAPSHOT_INSERT_SQL, _snapshot_values(snapshot))
            identity_row = cursor.fetchone()
            if identity_row is None:
                raise FatalRepositoryError("snapshot insert did not return snapshot_id")
            snapshot_id = int(identity_row[0])

            persisted_results = () if snapshot.collect_status is CollectStatus.NO_RESULT else tuple(results)
            if persisted_results:
                operation = "results"
                cursor.executemany(
                    RESULT_INSERT_SQL,
                    tuple(_result_values(snapshot_id, result) for result in persisted_results),
                )

            cursor.execute(RESULT_COUNT_SQL, (snapshot_id,))
            count_row = cursor.fetchone()
            inserted_count = int(count_row[0]) if count_row is not None else -1
            if inserted_count != len(persisted_results):
                raise TaskPersistenceError(
                    "result row count mismatch before commit: "
                    f"expected {len(persisted_results)}, found {inserted_count}"
                )

            self._connection.commit()
            return snapshot_id
        except Exception as exc:
            try:
                self._connection.rollback()
            except Exception as rollback_exc:
                raise FatalRepositoryError(
                    "failed to rollback keyword discovery snapshot transaction; "
                    "transaction state is uncertain"
                ) from rollback_exc
            if isinstance(exc, RepositoryError):
                raise
            if operation == "snapshot" and _is_duplicate_key_error(exc):
                raise TaskPersistenceError("snapshot already exists for run_id and task_key") from exc
            error_codes = _sql_error_codes(exc)
            if error_codes & _TASK_LOCAL_SQL_ERROR_CODES:
                raise TaskPersistenceError("failed to save task-local keyword discovery data") from exc
            raise FatalRepositoryError(
                "failed to save keyword discovery snapshot: "
                "database connection, target, schema, or authorization failed"
            ) from exc
        finally:
            if cursor is not None:
                cursor.close()

    def ping(self) -> bool:
        cursor = None
        try:
            cursor = self._connection.cursor()
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            return row is not None and row[0] == 1
        except Exception as exc:
            raise RepositoryError("database connection probe failed") from exc
        finally:
            if cursor is not None:
                cursor.close()

    def preflight(self, *, expected_database: str = "naverDB") -> None:
        """Validate the read-only target and complete approved column contract."""

        cursor = None
        try:
            cursor = self._connection.cursor()
            cursor.execute("SELECT DB_NAME()")
            database_row = cursor.fetchone()
            actual_database = str(database_row[0]) if database_row else ""
            if actual_database.casefold() != expected_database.casefold():
                raise FatalRepositoryError(
                    f"database target mismatch: expected {expected_database}"
                )

            cursor.execute(SCHEMA_COLUMNS_SQL)
            rows = cursor.fetchall()
            actual = {
                (str(row[0]), str(row[1])): (
                    str(row[2]).lower(),
                    row[3],
                    row[4],
                    row[5],
                    str(row[6]).upper(),
                    int(row[7] or 0),
                )
                for row in rows
            }
            if actual != EXPECTED_SCHEMA_COLUMNS:
                raise FatalRepositoryError("keyword discovery schema mismatch")
        except FatalRepositoryError:
            raise
        except Exception as exc:
            raise FatalRepositoryError("database target/schema preflight failed") from exc
        finally:
            if cursor is not None:
                cursor.close()

    def close(self) -> None:
        self._connection.close()


class PlaceLocationRepository:
    def __init__(self, connection: Any):
        self._connection = connection

    def get(self, place_id: str) -> PlaceLocation | None:
        cursor = self._connection.cursor()
        try:
            cursor.execute(LOCATION_SELECT_SQL, (place_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return PlaceLocation(str(row[0]), float(row[1]), float(row[2]), row[3], row[4], str(row[5]))
        finally:
            cursor.close()

    def upsert(self, location: PlaceLocation) -> None:
        cursor = self._connection.cursor()
        try:
            cursor.execute(
                LOCATION_UPSERT_SQL,
                (
                    location.place_id,
                    location.latitude, location.longitude, location.verified_at, location.resolver_version,
                    location.place_id, location.latitude, location.longitude,
                    location.resolved_at, location.verified_at, location.resolver_version,
                ),
            )
            self._connection.commit()
        except Exception as exc:
            try:
                self._connection.rollback()
            except Exception as rollback_exc:
                raise FatalRepositoryError("failed to rollback Place location transaction") from rollback_exc
            raise FatalRepositoryError("failed to save Place location") from exc
        finally:
            cursor.close()

    def preflight(self, *, expected_database: str = "naverDB") -> None:
        cursor = self._connection.cursor()
        try:
            cursor.execute("SELECT DB_NAME()")
            row = cursor.fetchone()
            actual_database = str(row[0]) if row else ""
            if actual_database.casefold() != expected_database.casefold():
                raise FatalRepositoryError(
                    f"database target mismatch: expected {expected_database}"
                )
            cursor.execute(LOCATION_SCHEMA_COLUMNS_SQL)
            actual = {
                str(row[0]): (
                    str(row[1]).lower(), row[2], row[3], row[4], str(row[5]).upper()
                )
                for row in cursor.fetchall()
            }
            if actual != EXPECTED_LOCATION_SCHEMA_COLUMNS:
                raise FatalRepositoryError("Place location schema mismatch")
        except FatalRepositoryError:
            raise
        except Exception as exc:
            raise FatalRepositoryError("Place location target/schema preflight failed") from exc
        finally:
            cursor.close()


def _snapshot_values(snapshot: SearchSnapshot) -> tuple[object, ...]:
    task = snapshot.task
    return (
        snapshot.run_id,
        snapshot.task_key,
        task.query,
        snapshot.normalized_query,
        task.target_store_id,
        task.target_store_name,
        task.location_name,
        task.latitude,
        task.longitude,
        task.device_type.value,
        task.source_type.value,
        task.source_id,
        snapshot.requested_result_limit,
        snapshot.observed_result_count,
        snapshot.result_end_reached,
        snapshot.collect_status.value,
        snapshot.collect_msg,
        snapshot.parser_version,
        snapshot.final_url,
        snapshot.collected_at,
    )


def _result_values(snapshot_id: int, result: ParsedResult) -> tuple[object, ...]:
    return (
        snapshot_id,
        result.raw_position,
        result.organic_rank,
        result.place_id,
        result.place_name,
        result.category,
        result.is_ad,
        result.detail_url,
        result.distance_text,
        result.is_own_store,
        result.matched_store_id,
        result.match_method.value,
    )


def _is_duplicate_key_error(exc: Exception) -> bool:
    details = " ".join(str(part) for part in exc.args).lower()
    return "2627" in details or "2601" in details


def _sql_error_codes(exc: Exception) -> set[int]:
    codes: set[int] = set()
    pending = list(exc.args)
    while pending:
        part = pending.pop()
        if isinstance(part, bool):
            continue
        if isinstance(part, int):
            codes.add(part)
        elif isinstance(part, (tuple, list)):
            pending.extend(part)
        else:
            text = str(part)
            for code in _FATAL_SQL_ERROR_CODES | _TASK_LOCAL_SQL_ERROR_CODES:
                if str(code) in text:
                    codes.add(code)
    return codes
