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
        "DB_DATABASE": "genericDB",
        "DB_USER": "generic-readonly",
        "DB_PASSWORD": "generic-secret",
        "DB_ENCRYPT": "true",
        "DB_TRUST_SERVER_CERTIFICATE": "false",
        "KEYWORD_DISCOVERY_DB_DATABASE": "naverDB",
        "KEYWORD_DISCOVERY_DB_USER": "collector-writer",
        "KEYWORD_DISCOVERY_DB_PASSWORD": "dedicated-secret",
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


def test_config_repr_and_redacted_output_hide_generic_and_dedicated_passwords(tmp_path: Path):
    config = CollectorConfig.from_env(
        write_env(
            tmp_path,
            DB_PASSWORD="generic-top-secret",
            KEYWORD_DISCOVERY_DB_PASSWORD="dedicated-top-secret",
        )
    )

    rendered = repr(config) + str(config.redacted())

    assert "generic-top-secret" not in rendered
    assert "dedicated-top-secret" not in rendered
    assert config.redacted()["db_password"] == "***"
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

    assert (config.db_server, config.db_port, config.db_database, config.db_user, config.db_password) == (
        "localhost",
        1444,
        "naverDB",
        "collector-writer",
        "dedicated-secret",
    )
    assert (config.db_encrypt, config.db_trust_server_certificate, config.headless) == (False, True, False)
    assert config.timeout_seconds == 45
    assert config.artifact_root == tmp_path / "saved" / "evidence"


def test_config_requires_dedicated_database_even_when_generic_database_exists(tmp_path: Path):
    with pytest.raises(ConfigError, match="KEYWORD_DISCOVERY_DB_DATABASE"):
        CollectorConfig.from_env(
            write_env(
                tmp_path,
                DB_DATABASE="genericDB",
                KEYWORD_DISCOVERY_DB_DATABASE="",
            )
        )


@pytest.mark.parametrize(
    "missing_key",
    ("KEYWORD_DISCOVERY_DB_USER", "KEYWORD_DISCOVERY_DB_PASSWORD"),
)
def test_config_requires_dedicated_credentials_even_when_generic_credentials_exist(
    tmp_path: Path,
    missing_key: str,
):
    with pytest.raises(ConfigError, match=missing_key):
        CollectorConfig.from_env(write_env(tmp_path, **{missing_key: ""}))


def test_process_environment_overrides_dedicated_database_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("KEYWORD_DISCOVERY_DB_DATABASE", "overrideNaverDB")
    monkeypatch.setenv("KEYWORD_DISCOVERY_DB_USER", "override-writer")
    monkeypatch.setenv("KEYWORD_DISCOVERY_DB_PASSWORD", "override-secret")

    config = CollectorConfig.from_env(
        write_env(
            tmp_path,
            DB_DATABASE="genericDB",
            KEYWORD_DISCOVERY_DB_DATABASE="fileNaverDB",
            KEYWORD_DISCOVERY_DB_USER="file-writer",
            KEYWORD_DISCOVERY_DB_PASSWORD="file-secret",
        )
    )

    assert (config.db_database, config.db_user, config.db_password) == (
        "overrideNaverDB",
        "override-writer",
        "override-secret",
    )


def test_env_example_documents_separate_generic_and_collector_database_credentials():
    example = (Path(__file__).parents[1] / ".env.example").read_text(encoding="utf-8")

    assert "DB_DATABASE=\n" in example
    assert "DB_USER=\n" in example
    assert "DB_PASSWORD=\n" in example
    assert "KEYWORD_DISCOVERY_DB_DATABASE=naverDB\n" in example
    assert "KEYWORD_DISCOVERY_DB_USER=\n" in example
    assert "KEYWORD_DISCOVERY_DB_PASSWORD=\n" in example
