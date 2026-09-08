import os
from pathlib import Path

import pytest

from scripts.place_keyword_collector.config import ConfigError, PlaceKeywordConfig
from scripts.place_keyword_collector.models import RefreshPolicy


@pytest.fixture(autouse=True)
def clear_collector_environment(monkeypatch: pytest.MonkeyPatch):
    for name in tuple(os.environ):
        if name.startswith("DB_") or name.startswith("KEYWORD_DISCOVERY_") or name.startswith("PLACE_KEYWORD_"):
            monkeypatch.delenv(name)


def write_env(repo_root: Path, **overrides: str) -> Path:
    values = {
        "DB_SERVER": "localhost",
        "DB_PORT": "1433",
        "KEYWORD_DISCOVERY_DB_DATABASE": "naverDB",
        "KEYWORD_DISCOVERY_DB_USER": "collector-writer",
        "KEYWORD_DISCOVERY_DB_PASSWORD": "secret",
        "PLACE_KEYWORD_HEADLESS": "true",
        "PLACE_KEYWORD_TIMEOUT_SECONDS": "30",
        "PLACE_KEYWORD_ARTIFACT_ROOT": "artifacts/place_keyword_collector",
    }
    values.update(overrides)
    (repo_root / ".env").write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    return repo_root


@pytest.fixture
def valid_config(tmp_path: Path) -> PlaceKeywordConfig:
    return PlaceKeywordConfig.from_env(write_env(tmp_path))


def test_config_defaults_to_monthly_and_top_ten(tmp_path: Path):
    config = PlaceKeywordConfig.from_env(write_env(tmp_path))

    assert config.refresh_policy is RefreshPolicy.MONTHLY
    assert config.top_n == 10
    assert config.max_retries == 2
    assert config.failure_limit == 5


def test_config_repr_redacts_password(valid_config: PlaceKeywordConfig):
    assert "secret" not in repr(valid_config)


def test_config_reads_place_keyword_settings_and_process_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PLACE_KEYWORD_HEADLESS", "false")
    monkeypatch.setenv("PLACE_KEYWORD_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("PLACE_KEYWORD_ARTIFACT_ROOT", "saved/evidence")

    config = PlaceKeywordConfig.from_env(write_env(tmp_path))

    assert (config.db_server, config.db_port, config.db_database, config.db_user) == (
        "localhost",
        1433,
        "naverDB",
        "collector-writer",
    )
    assert config.headless is False
    assert config.timeout_seconds == 45
    assert config.artifact_root == tmp_path / "saved" / "evidence"


@pytest.mark.parametrize("top_n", [0, 21])
def test_config_rejects_top_n_outside_naver_card_boundary(valid_config: PlaceKeywordConfig, top_n: int):
    with pytest.raises(ConfigError, match="top_n must be between 1 and 20"):
        valid_config.__class__(
            db_server=valid_config.db_server,
            db_port=valid_config.db_port,
            db_database=valid_config.db_database,
            db_user=valid_config.db_user,
            db_password=valid_config.db_password,
            headless=valid_config.headless,
            timeout_seconds=valid_config.timeout_seconds,
            artifact_root=valid_config.artifact_root,
            top_n=top_n,
        )


@pytest.mark.parametrize(
    ("field_name", "replacement", "message"),
    [
        ("timeout_seconds", 0, "timeout_seconds must be greater than zero"),
        ("max_retries", -1, "max_retries must not be negative"),
        ("failure_limit", 0, "failure_limit must be greater than zero"),
    ],
)
def test_config_rejects_invalid_runtime_limits(
    valid_config: PlaceKeywordConfig,
    field_name: str,
    replacement: int,
    message: str,
):
    values = {
        "db_server": valid_config.db_server,
        "db_port": valid_config.db_port,
        "db_database": valid_config.db_database,
        "db_user": valid_config.db_user,
        "db_password": valid_config.db_password,
        "headless": valid_config.headless,
        "timeout_seconds": valid_config.timeout_seconds,
        "artifact_root": valid_config.artifact_root,
    }
    values[field_name] = replacement

    with pytest.raises(ConfigError, match=message):
        valid_config.__class__(**values)
