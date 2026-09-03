from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


RESOLVER_VERSION = "place-location-v1"
_ALLOWED_HOSTS = {"m.place.naver.com", "place.naver.com"}
_NUMBER = r"-?\d+(?:\.\d+)?"


class PlaceLocationError(RuntimeError):
    """Safe failure while locating a Naver Place."""


@dataclass(frozen=True)
class PlaceLocation:
    place_id: str
    latitude: float
    longitude: float
    resolved_at: datetime
    verified_at: datetime
    resolver_version: str

    @classmethod
    def create(cls, place_id: str, latitude: float, longitude: float) -> "PlaceLocation":
        if not 33 <= latitude <= 39 or not 124 <= longitude <= 132:
            raise PlaceLocationError("coordinates are outside the Korean coordinate range")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return cls(str(place_id).strip(), latitude, longitude, now, now, RESOLVER_VERSION)


class PlaceCoordinateParser:
    def parse(self, html: str, expected_place_id: str) -> tuple[float, float]:
        place_id = re.escape(str(expected_place_id).strip())
        evidence: list[tuple[float, float]] = []
        object_pattern = re.compile(
            rf'"id"\s*:\s*"{place_id}"(?:(?!\{{|\}}).){{0,2000}}?'
            rf'"x"\s*:\s*"?({_NUMBER})"?(?:(?!\{{|\}}).){{0,500}}?'
            rf'"y"\s*:\s*"?({_NUMBER})"?',
            re.DOTALL,
        )
        for match in object_pattern.finditer(html or ""):
            evidence.append((float(match.group(2)), float(match.group(1))))

        soup = BeautifulSoup(html or "", "html.parser")
        for link in soup.select("a[href]"):
            parsed = urlparse(str(link.get("href", "")))
            query = parse_qs(parsed.query)
            if query.get("did", [""])[0] != expected_place_id:
                continue
            if query.get("dlat") and query.get("dlng"):
                evidence.append((float(query["dlat"][0]), float(query["dlng"][0])))

        if not evidence:
            raise PlaceLocationError("matching Place coordinate evidence was not found")
        rounded = {(round(lat, 5), round(lng, 5)) for lat, lng in evidence}
        if len(rounded) != 1:
            raise PlaceLocationError("conflicting Place coordinate evidence")
        latitude, longitude = evidence[0]
        PlaceLocation.create(expected_place_id, latitude, longitude)
        return latitude, longitude


class LocationRepository(Protocol):
    def get(self, place_id: str) -> PlaceLocation | None: ...
    def upsert(self, location: PlaceLocation) -> None: ...


class LocationPageClient(Protocol):
    def fetch(self, place_id: str) -> str: ...


class PlacePageClient:
    def __init__(self, *, timeout_seconds: float = 20) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, place_id: str) -> str:
        url = f"https://m.place.naver.com/restaurant/{str(place_id).strip()}/home"
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14) Mobile"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                if urlparse(response.geturl()).hostname not in _ALLOWED_HOSTS:
                    raise PlaceLocationError("Place page redirected to an unexpected host")
                return response.read().decode("utf-8", errors="replace")
        except PlaceLocationError:
            raise
        except Exception as exc:
            raise PlaceLocationError("Place page could not be loaded") from exc


class PlaceLocationResolver:
    def __init__(self, repository: LocationRepository, client: LocationPageClient) -> None:
        self.repository = repository
        self.client = client
        self.parser = PlaceCoordinateParser()
        self._memory: dict[str, PlaceLocation] = {}

    def resolve(self, place_id: str) -> PlaceLocation:
        normalized = str(place_id).strip()
        if normalized in self._memory:
            return self._memory[normalized]
        cached = self.repository.get(normalized)
        if cached is not None:
            self._memory[normalized] = cached
            return cached
        latitude, longitude = self.parser.parse(self.client.fetch(normalized), normalized)
        location = PlaceLocation.create(normalized, latitude, longitude)
        self.repository.upsert(location)
        self._memory[normalized] = location
        return location
