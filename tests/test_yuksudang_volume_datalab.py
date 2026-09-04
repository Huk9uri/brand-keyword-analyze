import json
from datetime import date
from pathlib import Path

from scripts.yuksudang_volume.datalab import normalize_series
from scripts.yuksudang_volume.config import NaverConfig
from scripts.yuksudang_volume.datalab import DataLabClient


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


def test_datalab_retries_timeout_error(monkeypatch):
    attempts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"results": []}'

    def fake_urlopen(request, timeout):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise TimeoutError("read operation timed out")
        return Response()

    monkeypatch.setattr("scripts.yuksudang_volume.datalab.urlopen", fake_urlopen)
    config = NaverConfig("1", "key", "secret", "client", "client-secret")
    client = DataLabClient(config, sleep=lambda _: None)

    result = client.fetch_daily_ratios(
        ["문래동"],
        date(2026, 8, 3),
        date(2026, 8, 5),
    )

    assert len(attempts) == 2
    assert list(result["문래동"].values()) == [0.0, 0.0, 0.0]
