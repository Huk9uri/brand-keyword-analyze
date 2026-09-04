from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from .models import RefreshPolicy


class ConfigError(ValueError):
    """Raised when Place keyword collector configuration is invalid."""


@dataclass(frozen=True, repr=False)
class PlaceKeywordConfig:
    db_server: str
    db_port: int
    db_database: str
    db_user: str
    db_password: str
    headless: bool
    timeout_seconds: int
    artifact_root: Path
    refresh_policy: RefreshPolicy = RefreshPolicy.MONTHLY
    top_n: int = 10
    max_retries: int = 2
    failure_limit: int = 5

    def __post_init__(self) -> None:
        if isinstance(self.top_n, bool) or not isinstance(self.top_n, int) or not 1 <= self.top_n <= 20:
            raise ConfigError("top_n must be between 1 and 20")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, int) or self.timeout_seconds <= 0:
            raise ConfigError("timeout_seconds must be greater than zero")
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int) or self.max_retries < 0:
            raise ConfigError("max_retries must not be negative")
        if isinstance(self.failure_limit, bool) or not isinstance(self.failure_limit, int) or self.failure_limit <= 0:
            raise ConfigError("failure_limit must be greater than zero")

    @classmethod
    def from_env(cls, repo_root: Path) -> "PlaceKeywordConfig":
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
                if key.startswith("DB_")
                or key.startswith("KEYWORD_DISCOVERY_")
                or key.startswith("PLACE_KEYWORD_")
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

        artifact_root = Path(values.get("PLACE_KEYWORD_ARTIFACT_ROOT", "artifacts/place_keyword_collector"))
        if not artifact_root.is_absolute():
            artifact_root = repo_root / artifact_root

        return cls(
            db_server=values["DB_SERVER"].strip(),
            db_port=_parse_positive_int(values["DB_PORT"], "DB_PORT"),
            db_database=values["KEYWORD_DISCOVERY_DB_DATABASE"].strip(),
            db_user=values["KEYWORD_DISCOVERY_DB_USER"].strip(),
            db_password=values["KEYWORD_DISCOVERY_DB_PASSWORD"].strip(),
            headless=_parse_bool(values.get("PLACE_KEYWORD_HEADLESS", "true"), "PLACE_KEYWORD_HEADLESS"),
            timeout_seconds=_parse_positive_int(
                values.get("PLACE_KEYWORD_TIMEOUT_SECONDS", "30"),
                "PLACE_KEYWORD_TIMEOUT_SECONDS",
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
            "headless": self.headless,
            "timeout_seconds": self.timeout_seconds,
            "artifact_root": str(self.artifact_root),
            "refresh_policy": self.refresh_policy,
            "top_n": self.top_n,
            "max_retries": self.max_retries,
            "failure_limit": self.failure_limit,
        }

    def __repr__(self) -> str:
        return f"PlaceKeywordConfig({self.redacted()!r})"


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
