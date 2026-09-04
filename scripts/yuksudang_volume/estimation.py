from datetime import date
from math import floor

from .models import DailyEstimate


class NoRatioSignalError(ValueError):
    """Raised when a DataLab series has no positive allocation weight."""


def allocate_integer_total(total: int, weights: list[float]) -> list[int]:
    if total < 0:
        raise ValueError("total must be non-negative")
    if any(weight < 0 for weight in weights):
        raise ValueError("weights must be non-negative")
    weight_sum = sum(weights)
    if weight_sum <= 0:
        raise NoRatioSignalError("ratio sum is zero")

    raw = [total * weight / weight_sum for weight in weights]
    allocated = [floor(value) for value in raw]
    remainder = total - sum(allocated)
    order = sorted(
        range(len(raw)),
        key=lambda index: (-(raw[index] - allocated[index]), index),
    )
    for index in order[:remainder]:
        allocated[index] += 1
    return allocated


def estimate_daily(
    monthly_pc: int,
    monthly_mobile: int,
    ratios: dict[date, float],
) -> list[DailyEstimate]:
    ordered = sorted(ratios.items())
    weights = [ratio for _, ratio in ordered]
    pc_values = allocate_integer_total(monthly_pc, weights)
    mobile_values = allocate_integer_total(monthly_mobile, weights)

    return [
        DailyEstimate(
            search_date=day,
            ratio=ratio,
            estimated_pc=pc_value,
            estimated_mobile=mobile_value,
            estimated_total=pc_value + mobile_value,
        )
        for (day, ratio), pc_value, mobile_value in zip(
            ordered,
            pc_values,
            mobile_values,
        )
    ]
