from datetime import datetime
from pathlib import Path

import pytest

from scripts.keyword_discovery_rank.place_location import (
    PlaceCoordinateParser,
    PlaceLocation,
    PlaceLocationError,
    PlaceLocationResolver,
)


FIXTURES = Path(__file__).parent / "fixtures" / "keyword_discovery_rank"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["place_location_object.html", "place_location_route.html"])
def test_parser_extracts_only_place_bound_coordinate_evidence(name: str):
    assert PlaceCoordinateParser().parse(fixture(name), "31076466") == (37.5042, 127.0531)


def test_parser_rejects_photo_url_as_coordinate_evidence():
    html = '<a href="https://m.place.naver.com/restaurant/31076466/photo?x=127.1&y=37.5">사진</a>'
    with pytest.raises(PlaceLocationError, match="coordinate evidence"):
        PlaceCoordinateParser().parse(html, "31076466")


def test_parser_rejects_wrong_place_id_and_conflicting_evidence():
    wrong = '<a href="https://nmap.place.naver.com/launchApp/route?did=999&dlat=37.5&dlng=127.1">길찾기</a>'
    with pytest.raises(PlaceLocationError, match="coordinate evidence"):
        PlaceCoordinateParser().parse(wrong, "31076466")

    conflicting = fixture("place_location_object.html") + (
        '<a href="https://nmap.place.naver.com/launchApp/route?did=31076466&dlat=37.6&dlng=127.2">길찾기</a>'
    )
    with pytest.raises(PlaceLocationError, match="conflicting"):
        PlaceCoordinateParser().parse(conflicting, "31076466")


@pytest.mark.parametrize("latitude,longitude", [(40.0, 127.0), (37.0, 133.0)])
def test_place_location_rejects_coordinates_outside_korea(latitude: float, longitude: float):
    with pytest.raises(PlaceLocationError, match="Korean coordinate range"):
        PlaceLocation.create("31076466", latitude, longitude)


class FakeRepository:
    def __init__(self, cached: PlaceLocation | None = None):
        self.cached = cached
        self.get_calls = 0
        self.saved: list[PlaceLocation] = []

    def get(self, place_id: str):
        self.get_calls += 1
        return self.cached

    def upsert(self, location: PlaceLocation):
        self.saved.append(location)
        self.cached = location


class FakeClient:
    def __init__(self, html: str):
        self.html = html
        self.calls = 0

    def fetch(self, place_id: str):
        self.calls += 1
        return self.html


def test_resolver_uses_cache_without_http():
    cached = PlaceLocation("31076466", 37.5042, 127.0531, datetime(2026, 9, 3), datetime(2026, 9, 3), "place-location-v1")
    repository = FakeRepository(cached)
    client = FakeClient("")

    assert PlaceLocationResolver(repository, client).resolve("31076466") == cached
    assert client.calls == 0


def test_resolver_fetches_and_saves_once_per_place_id():
    repository = FakeRepository()
    client = FakeClient(fixture("place_location_object.html"))
    resolver = PlaceLocationResolver(repository, client)

    first = resolver.resolve("31076466")
    second = resolver.resolve("31076466")

    assert first == second
    assert (first.latitude, first.longitude) == (37.5042, 127.0531)
    assert client.calls == 1
    assert len(repository.saved) == 1
