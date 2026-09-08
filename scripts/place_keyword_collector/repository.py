from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .models import (
    CollectedKeyword,
    KeywordCollectStatus,
    KeywordSnapshot,
    PreviousVersion,
)


class RepositoryError(RuntimeError):
    """Raised when Place keyword persistence cannot complete safely."""


class FatalRepositoryError(RepositoryError):
    """A connection, authorization, target, or schema failure that stops a run."""


class TaskPersistenceError(RepositoryError):
    """A persistence failure isolated to one Place check."""


SNAPSHOT_INSERT_SQL = """
INSERT INTO dbo.naver_place_keyword_snapshot (
    run_id,
    rank_run_id,
    place_id,
    place_name,
    source_url,
    collect_status,
    collect_method,
    content_hash,
    is_changed,
    effective_snapshot_id,
    keyword_count,
    parser_version,
    collect_msg,
    checked_at
)
OUTPUT INSERTED.snapshot_id
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

RESULT_INSERT_SQL = """
INSERT INTO dbo.naver_place_keyword_result (
    snapshot_id,
    keyword_order,
    raw_keyword,
    normalized_keyword
)
VALUES (%s, %s, %s, %s)
"""

SET_EFFECTIVE_SNAPSHOT_SQL = """
UPDATE dbo.naver_place_keyword_snapshot
SET effective_snapshot_id = %s
WHERE snapshot_id = %s
"""

RESULT_COUNT_SQL = """
SELECT COUNT(*)
FROM dbo.naver_place_keyword_result
WHERE snapshot_id = %s
"""

PREVIOUS_SELECT_SQL = """
SELECT TOP (1)
    latest.effective_snapshot_id,
    effective.content_hash,
    latest.checked_at,
    latest.collect_status
FROM dbo.naver_place_keyword_snapshot AS latest
INNER JOIN dbo.naver_place_keyword_snapshot AS effective
    ON effective.snapshot_id = latest.effective_snapshot_id
   AND effective.place_id = latest.place_id
   AND effective.collect_status IN ('SUCCESS', 'EMPTY')
WHERE latest.place_id = %s
ORDER BY latest.checked_at DESC, latest.snapshot_id DESC
"""

VALIDATE_EFFECTIVE_SNAPSHOT_SQL = """
SELECT COUNT(*)
FROM dbo.naver_place_keyword_snapshot AS effective
WHERE effective.snapshot_id = %s
  AND effective.place_id = %s
  AND effective.collect_status IN ('SUCCESS', 'EMPTY')
"""

SCHEMA_COLUMNS_SQL = """
SELECT
    TABLE_NAME,
    COLUMN_NAME,
    DATA_TYPE,
    CHARACTER_MAXIMUM_LENGTH,
    NUMERIC_PRECISION,
    NUMERIC_SCALE,
    DATETIME_PRECISION,
    IS_NULLABLE,
    CAST(COLUMNPROPERTY(
        OBJECT_ID(QUOTENAME(TABLE_SCHEMA) + '.' + QUOTENAME(TABLE_NAME)),
        COLUMN_NAME,
        'IsIdentity'
    ) AS int) AS is_identity
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dbo'
  AND TABLE_NAME IN ('naver_place_keyword_snapshot', 'naver_place_keyword_result')
ORDER BY TABLE_NAME, COLUMN_NAME
"""

# INFORMATION_SCHEMA reports character lengths in characters, unlike sys.columns.
# Values are: data type, character length, numeric precision, numeric scale,
# datetime precision, nullability, and identity flag.
EXPECTED_SCHEMA_COLUMNS = {
    ("naver_place_keyword_result", "keyword_order"): (
        "smallint", None, 5, 0, None, "NO", 0,
    ),
    ("naver_place_keyword_result", "normalized_keyword"): (
        "nvarchar", 255, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_result", "raw_keyword"): (
        "nvarchar", 255, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_result", "snapshot_id"): (
        "bigint", None, 19, 0, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "checked_at"): (
        "datetime2", None, None, None, 3, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "collect_method"): (
        "varchar", 20, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "collect_msg"): (
        "nvarchar", 1000, None, None, None, "YES", 0,
    ),
    ("naver_place_keyword_snapshot", "collect_status"): (
        "varchar", 30, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "content_hash"): (
        "char", 64, None, None, None, "YES", 0,
    ),
    ("naver_place_keyword_snapshot", "effective_snapshot_id"): (
        "bigint", None, 19, 0, None, "YES", 0,
    ),
    ("naver_place_keyword_snapshot", "is_changed"): (
        "bit", None, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "keyword_count"): (
        "smallint", None, 5, 0, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "parser_version"): (
        "varchar", 30, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "place_id"): (
        "varchar", 50, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "place_name"): (
        "nvarchar", 300, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "rank_run_id"): (
        "uniqueidentifier", None, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "run_id"): (
        "uniqueidentifier", None, None, None, None, "NO", 0,
    ),
    ("naver_place_keyword_snapshot", "snapshot_id"): (
        "bigint", None, 19, 0, None, "NO", 1,
    ),
    ("naver_place_keyword_snapshot", "source_url"): (
        "nvarchar", 2000, None, None, None, "NO", 0,
    ),
}

_VALID_VERSION_STATUSES = frozenset(
    {KeywordCollectStatus.SUCCESS, KeywordCollectStatus.EMPTY}
)
_FATAL_SQL_ERROR_CODES = frozenset(
    {53, 207, 208, 229, 233, 4060, 18456, 20002, 20003, 10054, 10060}
)
_TASK_LOCAL_SQL_ERROR_CODES = frozenset(
    {245, 515, 547, 2601, 2627, 2628, 8114, 8152}
)


class PlaceKeywordRepository:
    def __init__(self, connection: Any):
        self._connection = connection

    def preflight(self, expected_database: str = "naverDB") -> None:
        """Validate the target database and exact Task 2 column contract."""

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
            actual_schema = {
                (str(row[0]), str(row[1])): (
                    str(row[2]).lower(),
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    str(row[7]).upper(),
                    int(row[8] or 0),
                )
                for row in cursor.fetchall()
            }
            if actual_schema != EXPECTED_SCHEMA_COLUMNS:
                raise FatalRepositoryError("Place keyword schema mismatch")
        except FatalRepositoryError:
            raise
        except Exception as exc:
            raise FatalRepositoryError(
                "database target/schema preflight failed"
            ) from None
        finally:
            if cursor is not None:
                cursor.close()

    def get_previous(self, place_id: str) -> PreviousVersion | None:
        cursor = None
        try:
            cursor = self._connection.cursor()
            cursor.execute(PREVIOUS_SELECT_SQL, (place_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            if row[0] is None or row[1] is None:
                raise FatalRepositoryError(
                    "invalid previous version for Place keywords"
                )
            return PreviousVersion(
                effective_snapshot_id=int(row[0]),
                content_hash=str(row[1]),
                checked_at=row[2],
                status=KeywordCollectStatus(str(row[3])),
            )
        except FatalRepositoryError:
            raise
        except Exception as exc:
            raise FatalRepositoryError(
                "failed to load previous version for Place keywords"
            ) from None
        finally:
            if cursor is not None:
                cursor.close()

    def save(
        self,
        snapshot: KeywordSnapshot,
        keywords: Sequence[CollectedKeyword],
    ) -> int:
        cursor = None
        operation = "snapshot"
        try:
            cursor = self._connection.cursor()
            creates_valid_version = (
                snapshot.is_changed and snapshot.status in _VALID_VERSION_STATUSES
            )
            persisted_keywords = tuple(keywords) if creates_valid_version else ()
            if creates_valid_version and snapshot.content_hash is None:
                raise TaskPersistenceError(
                    "content_hash is required for a changed valid Place keyword version"
                )
            required_keyword_count = (
                len(persisted_keywords)
                if snapshot.status is KeywordCollectStatus.SUCCESS
                else 0
            )
            status_keyword_mismatch = (
                snapshot.status is KeywordCollectStatus.SUCCESS
                and not persisted_keywords
            ) or (
                snapshot.status is KeywordCollectStatus.EMPTY
                and bool(persisted_keywords)
            )
            if creates_valid_version and (
                snapshot.keyword_count != required_keyword_count
                or status_keyword_mismatch
            ):
                raise TaskPersistenceError(
                    "keyword_count mismatch for changed valid Place keyword version"
                )
            initial_effective_id = (
                None if creates_valid_version else snapshot.effective_snapshot_id
            )
            if initial_effective_id is not None:
                operation = "effective snapshot validation"
                cursor.execute(
                    VALIDATE_EFFECTIVE_SNAPSHOT_SQL,
                    (initial_effective_id, snapshot.target.place_id),
                )
                valid_row = cursor.fetchone()
                valid_count = int(valid_row[0]) if valid_row is not None else 0
                if valid_count != 1:
                    raise TaskPersistenceError(
                        "effective snapshot must be a valid version for the same Place"
                    )

            operation = "snapshot"
            cursor.execute(
                SNAPSHOT_INSERT_SQL,
                _snapshot_values(snapshot, initial_effective_id),
            )
            identity_row = cursor.fetchone()
            if identity_row is None:
                raise FatalRepositoryError(
                    "Place keyword snapshot insert did not return snapshot_id"
                )
            snapshot_id = int(identity_row[0])

            if persisted_keywords:
                operation = "results"
                cursor.executemany(
                    RESULT_INSERT_SQL,
                    tuple(
                        _keyword_values(snapshot_id, keyword)
                        for keyword in persisted_keywords
                    ),
                )

            if creates_valid_version:
                operation = "effective snapshot"
                cursor.execute(
                    SET_EFFECTIVE_SNAPSHOT_SQL,
                    (snapshot_id, snapshot_id),
                )

            operation = "result count"
            cursor.execute(RESULT_COUNT_SQL, (snapshot_id,))
            count_row = cursor.fetchone()
            inserted_count = int(count_row[0]) if count_row is not None else -1
            if inserted_count != len(persisted_keywords):
                raise TaskPersistenceError(
                    "result row count mismatch before commit: "
                    f"expected {len(persisted_keywords)}, found {inserted_count}"
                )

            self._connection.commit()
            return snapshot_id
        except Exception as exc:
            try:
                self._connection.rollback()
            except Exception as rollback_exc:
                raise FatalRepositoryError(
                    "failed to rollback Place keyword transaction; "
                    "transaction state is uncertain"
                ) from None

            if isinstance(exc, RepositoryError):
                raise
            if operation == "snapshot" and _is_duplicate_key_error(exc):
                raise TaskPersistenceError(
                    "Place keyword snapshot already exists for run_id and place_id"
                ) from None
            if _sql_error_codes(exc) & _TASK_LOCAL_SQL_ERROR_CODES:
                raise TaskPersistenceError(
                    "failed to save task-local Place keyword data"
                ) from None
            raise FatalRepositoryError(
                "failed to save Place keyword snapshot: database connection, "
                "target, schema, or authorization failed"
            ) from None
        finally:
            if cursor is not None:
                cursor.close()

    def close(self) -> None:
        self._connection.close()


def _snapshot_values(
    snapshot: KeywordSnapshot,
    effective_snapshot_id: int | None,
) -> tuple[object, ...]:
    return (
        snapshot.run_id,
        snapshot.rank_run_id,
        snapshot.target.place_id,
        snapshot.target.place_name,
        snapshot.source_url,
        snapshot.status.value,
        "BROWSER",
        snapshot.content_hash,
        snapshot.is_changed,
        effective_snapshot_id,
        snapshot.keyword_count,
        snapshot.parser_version,
        snapshot.collect_msg,
        snapshot.checked_at,
    )


def _keyword_values(
    snapshot_id: int,
    keyword: CollectedKeyword,
) -> tuple[object, ...]:
    return (
        snapshot_id,
        keyword.keyword_order,
        keyword.raw_keyword,
        keyword.normalized_keyword,
    )


def _is_duplicate_key_error(exc: Exception) -> bool:
    return bool(_sql_error_codes(exc) & {2601, 2627})


def _sql_error_codes(exc: Exception) -> set[int]:
    codes: set[int] = set()
    pending = list(exc.args)
    known_codes = _FATAL_SQL_ERROR_CODES | _TASK_LOCAL_SQL_ERROR_CODES
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
            for code in known_codes:
                if str(code) in text:
                    codes.add(code)
    return codes
