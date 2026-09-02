from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .models import CollectStatus, ParsedResult, SearchSnapshot


class RepositoryError(RuntimeError):
    """Raised when a snapshot transaction cannot be persisted safely."""


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


class SnapshotRepository:
    def __init__(self, connection: Any):
        self._connection = connection

    def save(
        self,
        snapshot: SearchSnapshot,
        results: Sequence[ParsedResult],
    ) -> int:
        cursor = None
        try:
            cursor = self._connection.cursor()
            cursor.execute(SNAPSHOT_INSERT_SQL, _snapshot_values(snapshot))
            identity_row = cursor.fetchone()
            if identity_row is None:
                raise RepositoryError("snapshot insert did not return snapshot_id")
            snapshot_id = int(identity_row[0])

            persisted_results = () if snapshot.collect_status is CollectStatus.NO_RESULT else tuple(results)
            if persisted_results:
                cursor.executemany(
                    RESULT_INSERT_SQL,
                    tuple(_result_values(snapshot_id, result) for result in persisted_results),
                )

            cursor.execute(RESULT_COUNT_SQL, (snapshot_id,))
            count_row = cursor.fetchone()
            inserted_count = int(count_row[0]) if count_row is not None else -1
            if inserted_count != len(persisted_results):
                raise RepositoryError(
                    "result row count mismatch before commit: "
                    f"expected {len(persisted_results)}, found {inserted_count}"
                )

            self._connection.commit()
            return snapshot_id
        except Exception as exc:
            self._connection.rollback()
            if isinstance(exc, RepositoryError):
                raise
            if _is_duplicate_key_error(exc):
                raise RepositoryError("snapshot already exists for run_id and task_key") from exc
            raise RepositoryError("failed to save keyword discovery snapshot") from exc
        finally:
            if cursor is not None:
                cursor.close()

    def ping(self) -> bool:
        cursor = self._connection.cursor()
        try:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            return row is not None and row[0] == 1
        except Exception as exc:
            raise RepositoryError("database connection probe failed") from exc
        finally:
            cursor.close()

    def close(self) -> None:
        self._connection.close()


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
