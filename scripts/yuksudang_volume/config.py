from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Raised when required local configuration is missing or empty."""


@dataclass(frozen=True, repr=False)
class NaverConfig:
    searchad_customer_id: str
    searchad_api_key: str
    searchad_secret_key: str
    datalab_client_id: str
    datalab_client_secret: str

    @classmethod
    def from_env_file(cls, path: Path) -> "NaverConfig":
        if not path.is_file():
            raise ConfigError(f"environment file not found: {path}")

        values: dict[str, str] = {}
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")

        names = {
            "searchad_customer_id": "NAVER_SEARCHAD_CUSTOMER_ID",
            "searchad_api_key": "NAVER_SEARCHAD_API_KEY",
            "searchad_secret_key": "NAVER_SEARCHAD_SECRET_KEY",
            "datalab_client_id": "NAVER_DATALAB_CLIENT_ID",
            "datalab_client_secret": "NAVER_DATALAB_CLIENT_SECRET",
        }
        missing = [name for name in names.values() if not values.get(name)]
        if missing:
            raise ConfigError("missing environment keys: " + ", ".join(missing))

        return cls(**{field: values[name] for field, name in names.items()})

    def redacted(self) -> dict[str, str]:
        return {
            "searchad_customer_id": self.searchad_customer_id,
            "searchad_api_key": "***",
            "searchad_secret_key": "***",
            "datalab_client_id": "***",
            "datalab_client_secret": "***",
        }

    def __repr__(self) -> str:
        return f"NaverConfig({self.redacted()!r})"
