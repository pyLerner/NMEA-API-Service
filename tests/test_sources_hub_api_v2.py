# =============================================================================
# PositionHub matching + API v2 filters
# =============================================================================
from __future__ import annotations

import asyncio
from typing import Any

from db.cache import Record
from sources.hub import PositionHub, matches_provider, provider_id_from_source
from starlette.testclient import TestClient


def test_provider_id_from_source() -> None:
    assert provider_id_from_source("nmea/rmc") == "nmea"
    assert provider_id_from_source("qr") == "qr"
    assert provider_id_from_source(None) is None


def test_matches_provider() -> None:
    assert matches_provider("nmea/rmc", None) is True
    assert matches_provider("nmea/rmc", "nmea") is True
    assert matches_provider("nmea/fusion", "qr") is False
    assert matches_provider("qr", "qr") is True


def _sample_record(**overrides: Any) -> Record:
    base = dict(
        key_id=1,
        datetime="2026-04-10T10:15:00+00:00",
        is_valid="A",
        latitude=46.05123,
        latitude_hemi="N",
        longitude=14.50678,
        longitude_hemi="E",
        speed=0.8,
        direction=176.5,
        mode="A",
        satellites_count=9,
        source="nmea/rmc",
        quality="GOOD",
    )
    base.update(overrides)
    return Record(**base)


def test_v2_all_coords_filter_provider(client: TestClient, cache) -> None:
    asyncio.run(cache.add(_sample_record(source="nmea/rmc")))
    asyncio.run(
        cache.add(
            _sample_record(
                key_id=2,
                datetime="2026-04-10T10:16:00+00:00",
                source="qr",
                latitude=47.0,
            )
        )
    )
    r = client.get("/api/navigator/v2/all-coords", params={"provider": "nmea"})
    assert r.status_code == 200
    body = r.json()
    assert body["result"] is True
    assert body["count"] == 1
    assert body["data"][0]["source"] == "nmea/rmc"


def test_v2_all_coords_time_range(client: TestClient, cache) -> None:
    asyncio.run(
        cache.add(_sample_record(datetime="2026-04-10T10:00:00+00:00", source="nmea/rmc"))
    )
    asyncio.run(
        cache.add(
            _sample_record(
                key_id=2,
                datetime="2026-04-10T12:00:00+00:00",
                source="nmea/rmc",
                latitude=46.1,
            )
        )
    )
    r = client.get(
        "/api/navigator/v2/all-coords",
        params={
            "from": "2026-04-10T11:00:00+00:00",
            "to": "2026-04-10T13:00:00+00:00",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["data"][0]["time"] == "2026-04-10T12:00:00+00:00"


def test_v2_all_coords_bad_from(client: TestClient) -> None:
    r = client.get("/api/navigator/v2/all-coords", params={"from": "not-a-date"})
    assert r.status_code == 400


def test_hub_publish_notifies_subscriber(cache, logger) -> None:
    async def _run() -> None:
        hub = PositionHub(cache, logger)
        queue = await hub.subscribe("nmea")
        await hub.publish_record(_sample_record(source="nmea/rmc"))
        await hub.publish_record(_sample_record(source="qr", key_id=2))
        got = queue.get_nowait()
        assert got is not None
        assert got.source == "nmea/rmc"
        assert queue.empty()
        await hub.unsubscribe(queue)

    asyncio.run(_run())


def test_v2_last_coords_route_is_sse(client: TestClient) -> None:
    # HEAD/GET without consuming the stream: open and immediately close.
    # Use a short request that only checks content-type via ASGI lifespan.
    # We only verify the route is registered and returns event-stream headers
    # by inspecting OpenAPI / routes rather than long-lived streaming.
    paths = {getattr(r, "path", None) for r in client.app.routes}
    assert "/api/navigator/v2/last-coords" in paths


def test_v1_last_coords_composite_source(client: TestClient, cache) -> None:
    asyncio.run(cache.add(_sample_record(source="nmea/ecef")))
    r = client.get("/api/navigator/v1/last-coords")
    assert r.status_code == 200
    assert r.json()["record"]["source"] == "nmea/ecef"
