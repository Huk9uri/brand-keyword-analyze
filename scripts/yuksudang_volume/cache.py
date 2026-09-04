import hashlib
import json
from datetime import datetime
from pathlib import Path


class JsonCache:
    """Small atomic JSON cache that stores only parsed business data."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    @staticmethod
    def key(namespace: str, request_fields: object) -> str:
        encoded = json.dumps(
            request_fields,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        return f"{namespace}-{digest}"

    def load(self, key: str) -> object | None:
        path = self._directory / f"{key}.json"
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("cache_version") != 1 or payload.get("request_key") != key:
            return None
        return payload.get("data")

    def store(self, key: str, data: object) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._directory / f"{key}.json"
        temporary = path.with_suffix(".tmp")
        payload = {
            "cache_version": 1,
            "collected_at": datetime.now().astimezone().isoformat(),
            "request_key": key,
            "data": data,
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
