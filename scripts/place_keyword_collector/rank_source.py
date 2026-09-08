from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Any

from .models import PreviousVersion, RankPlaceTarget, RefreshPolicy, normalize_place_id


RANK_PLACE_TARGETS_SQL = """
WITH ranked_places AS (
    SELECT
        LTRIM(RTRIM(result.place_id)) AS place_id,
        result.place_name,
        result.organic_rank,
        ROW_NUMBER() OVER (
            PARTITION BY LTRIM(RTRIM(result.place_id))
            ORDER BY result.organic_rank, result.place_name
        ) AS place_row_number
    FROM dbo.naver_keyword_discovery_result AS result
    INNER JOIN dbo.naver_keyword_discovery_snapshot AS snapshot
        ON snapshot.snapshot_id = result.snapshot_id
    WHERE snapshot.run_id = %s
      AND snapshot.collect_status IN ('SUCCESS', 'PARTIAL')
      AND result.place_id IS NOT NULL
      AND NULLIF(LTRIM(RTRIM(result.place_id)), '') IS NOT NULL
      AND result.organic_rank IS NOT NULL
      AND result.is_ad = 0
      AND result.organic_rank <= %s
)
SELECT place_id, place_name
FROM ranked_places
WHERE place_row_number = 1
ORDER BY organic_rank, place_name, place_id
"""


class RankResultSource:
    """Load unique organic Place targets from one keyword-discovery run."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def load(self, rank_run_id: str, top_n: int = 10) -> tuple[RankPlaceTarget, ...]:
        self._cursor.execute(RANK_PLACE_TARGETS_SQL, (rank_run_id, top_n))
        targets: list[RankPlaceTarget] = []
        for row in self._cursor.fetchall():
            try:
                place_id = normalize_place_id(row[0])
            except ValueError:
                raise ValueError("invalid Naver Place ID from rank result") from None
            targets.append(RankPlaceTarget(place_id=place_id, place_name=str(row[1])))
        return tuple(targets)


def is_refresh_due(
    previous: PreviousVersion | None,
    policy: RefreshPolicy,
    now: datetime,
    force: bool,
) -> bool:
    if force or previous is None:
        return True
    if policy is RefreshPolicy.WEEKLY:
        return now >= previous.checked_at + timedelta(days=7)
    return now >= _add_calendar_month(previous.checked_at)


def _add_calendar_month(value: datetime) -> datetime:
    next_year, next_month = divmod(value.month, 12)
    year = value.year + next_year
    month = next_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)
