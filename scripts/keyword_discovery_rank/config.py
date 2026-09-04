from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


class ConfigError(ValueError):
    """Raised when required collector configuration is missing or invalid."""


@dataclass(frozen=True, repr=False)
class CollectorConfig:
    db_server: str
    db_port: int
    db_database: str
    db_user: str
    db_password: str
    db_encrypt: bool
    headless: bool
    timeout_seconds: int
    artifact_root: Path
    result_limit: int = 20
    max_retries: int = 2
    failure_limit: int = 5

    def __post_init__(self) -> None:
        if (
            isinstance(self.result_limit, bool)
            or not isinstance(self.result_limit, int)
            or not 1 <= self.result_limit <= 20
        ):
            raise ConfigError("result_limit must be between 1 and 20")

    @classmethod
    def from_env(cls, repo_root: Path) -> "CollectorConfig":
        repo_root = Path(repo_root)
        values = {
            key: value
            for key, value in dotenv_values(repo_root / ".env").items()
            if value is not None
        }
        values.update(
            {
                key: value
                for key, value in os.environ.items()
                if key.startswith("DB_") or key.startswith("KEYWORD_DISCOVERY_")
            }
        )

        required = (
            "DB_SERVER",
            "DB_PORT",
            "KEYWORD_DISCOVERY_DB_DATABASE",
            "KEYWORD_DISCOVERY_DB_USER",
            "KEYWORD_DISCOVERY_DB_PASSWORD",
        )
        missing = [key for key in required if not values.get(key, "").strip()]
        if missing:
            raise ConfigError("missing environment keys: " + ", ".join(missing))

        artifact_root = Path(values.get("KEYWORD_DISCOVERY_ARTIFACT_ROOT", "artifacts/keyword_discovery_rank"))
        if not artifact_root.is_absolute():
            artifact_root = repo_root / artifact_root

        return cls(
            db_server=values["DB_SERVER"].strip(),
            db_port=_parse_positive_int(values["DB_PORT"], "DB_PORT"),
            db_database=values["KEYWORD_DISCOVERY_DB_DATABASE"].strip(),
            db_user=values["KEYWORD_DISCOVERY_DB_USER"].strip(),
            db_password=values["KEYWORD_DISCOVERY_DB_PASSWORD"].strip(),
            db_encrypt=_parse_bool(values.get("DB_ENCRYPT", "true"), "DB_ENCRYPT"),
            headless=_parse_bool(values.get("KEYWORD_DISCOVERY_HEADLESS", "true"), "KEYWORD_DISCOVERY_HEADLESS"),
            timeout_seconds=_parse_positive_int(
                values.get("KEYWORD_DISCOVERY_TIMEOUT_SECONDS", "30"),
                "KEYWORD_DISCOVERY_TIMEOUT_SECONDS",
            ),
            artifact_root=artifact_root,
        )

    def redacted(self) -> dict[str, object]:
        return {
            "db_server": self.db_server,
            "db_port": self.db_port,
            "db_database": self.db_database,
            "db_user": self.db_user,
            "db_password": "***",
            "db_encrypt": self.db_encrypt,
            "headless": self.headless,
            "timeout_seconds": self.timeout_seconds,
            "artifact_root": str(self.artifact_root),
            "result_limit": self.result_limit,
            "max_retries": self.max_retries,
            "failure_limit": self.failure_limit,
        }

    def __repr__(self) -> str:
        return f"CollectorConfig({self.redacted()!r})"


def _parse_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"invalid boolean for {name}: {value!r}")


def _parse_positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"invalid integer for {name}: {value!r}") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return parsed
