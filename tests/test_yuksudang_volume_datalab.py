import json
from datetime import date
from pathlib import Path

from scripts.yuksudang_volume.datalab import normalize_series


def test_normalize_series_fills_missing_dates_with_zero():
    payload = json.loads(
        Path("tests/fixtures/yuksudang_volume/datalab_search.json").read_text(
            encoding="utf-8"
        )
    )

    result = normalize_series(
        payload,
        ["문래동", "문래역"],
        date(2026, 8, 3),
        date(2026, 8, 5),
    )

    assert list(result["문래동"].values()) == [10.0, 0.0, 20.0]
    assert list(result["문래역"].values()) == [0.0, 0.0, 0.0]


def test_normalize_series_returns_zero_grid_for_missing_group():
    result = normalize_series(
        {"results": []},
        ["없는키워드"],
        date(2026, 8, 3),
        date(2026, 8, 5),
    )

    assert list(result["없는키워드"].values()) == [0.0, 0.0, 0.0]
