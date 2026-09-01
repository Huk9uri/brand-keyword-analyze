from datetime import date, timedelta

import pytest

from scripts.yuksudang_volume.estimation import (
    NoRatioSignalError,
    allocate_integer_total,
    estimate_daily,
)


def test_allocate_integer_total_preserves_total():
    assert allocate_integer_total(10, [1.0, 1.0, 1.0]) == [4, 3, 3]


def test_estimate_daily_preserves_pc_mobile_and_total():
    start = date(2026, 8, 3)
    ratios = {start + timedelta(days=i): float(i + 1) for i in range(30)}

    rows = estimate_daily(2_000, 8_000, ratios)

    assert len(rows) == 30
    assert sum(row.estimated_pc for row in rows) == 2_000
    assert sum(row.estimated_mobile for row in rows) == 8_000
    assert sum(row.estimated_total for row in rows) == 10_000
    assert all(
        row.estimated_total == row.estimated_pc + row.estimated_mobile
        for row in rows
    )


def test_estimate_daily_rejects_zero_ratio_sum():
    ratios = {
        date(2026, 8, 3) + timedelta(days=i): 0.0
        for i in range(30)
    }

    with pytest.raises(NoRatioSignalError):
        estimate_daily(100, 200, ratios)
