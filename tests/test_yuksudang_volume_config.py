from pathlib import Path

import pytest

from scripts.yuksudang_volume.config import ConfigError, NaverConfig


def test_loads_required_naver_keys_without_exposing_values(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "NAVER_SEARCHAD_CUSTOMER_ID=123\n"
        "NAVER_SEARCHAD_API_KEY=license-value\n"
        "NAVER_SEARCHAD_SECRET_KEY=search-secret\n"
        "NAVER_DATALAB_CLIENT_ID=client-value\n"
        "NAVER_DATALAB_CLIENT_SECRET=client-secret-value\n",
        encoding="utf-8",
    )

    config = NaverConfig.from_env_file(env)

    rendered = repr(config) + str(config.redacted())
    assert config.searchad_customer_id == "123"
    assert "license-value" not in rendered
    assert "search-secret" not in rendered
    assert "client-value" not in rendered
    assert "client-secret-value" not in rendered


def test_missing_required_key_raises(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("NAVER_SEARCHAD_CUSTOMER_ID=123\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="NAVER_SEARCHAD_API_KEY"):
        NaverConfig.from_env_file(env)
