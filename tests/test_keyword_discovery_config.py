import os
from pathlib import Path

import pytest

from scripts.keyword_discovery_rank.config import CollectorConfig, ConfigError


@pytest.fixture(autouse=True)
def clear_collector_environment(monkeypatch: pytest.MonkeyPatch):
    for name in tuple(os.environ):
        if name.startswith("DB_") or name.startswith("KEYWORD_DISCOVERY_"):
            monkeypatch.delenv(name)


def write_env(repo_root: Path, **overrides: str) -> Path:
    values = {
        "DB_SERVER": "localhost",
        "DB_PORT": "1433",
        "DB_DATABASE": "naverDB",
        "DB_USER": "collector",
        "DB_PASSWORD": "secret",
        "DB_ENCRYPT": "true",
        "DB_TRUST_SERVER_CERTIFICATE": "false",
        "KEYWORD_DISCOVERY_HEADLESS": "true",
        "KEYWORD_DISCOVERY_TIMEOUT_SECONDS": "30",
        "KEYWORD_DISCOVERY_ARTIFACT_ROOT": "artifacts/keyword_discovery_rank",
    }
    values.update(overrides)
    (repo_root / ".env").write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    return repo_root


def test_config_repr_redacts_password_and_uses_collector_defaults(tmp_path: Path):
    config = CollectorConfig.from_env(write_env(tmp_path, DB_PASSWORD="top-secret"))

    assert "top-secret" not in repr(config)
    assert (config.result_limit, config.max_retries, config.failure_limit) == (20, 2, 5)
    assert config.artifact_root == tmp_path / "artifacts" / "keyword_discovery_rank"


def test_config_reads_db_and_collector_settings(tmp_path: Path):
    config = CollectorConfig.from_env(
        write_env(
            tmp_path,
            DB_PORT="1444",
            DB_ENCRYPT="false",
            DB_TRUST_SERVER_CERTIFICATE="true",
            KEYWORD_DISCOVERY_HEADLESS="false",
            KEYWORD_DISCOVERY_TIMEOUT_SECONDS="45",
            KEYWORD_DISCOVERY_ARTIFACT_ROOT="saved/evidence",
        )
    )

    assert (config.db_server, config.db_port, config.db_database, config.db_user) == (
        "localhost",
        1444,
        "naverDB",
        "collector",
    )
    assert (config.db_encrypt, config.db_trust_server_certificate, config.headless) == (False, True, False)
    assert config.timeout_seconds == 45
    assert config.artifact_root == tmp_path / "saved" / "evidence"


def test_config_reports_missing_database_keys(tmp_path: Path):
    with pytest.raises(ConfigError, match="DB_PASSWORD"):
        CollectorConfig.from_env(write_env(tmp_path, DB_PASSWORD=""))
