# -*- coding: utf-8 -*-
"""Тесты QrGeoAdapter и совместной публикации nmea+qr."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from db.cache import Record, RecordsCache
from qr_geo.lookup import QrGeoLookup
from qr_geo.models import QrGeoEntry
from qr_geo.store import QrGeoStore
from sources.hub import PositionHub
from sources.qr_adapter import QrGeoAdapter
from sources.source_ids import SOURCE_NMEA_RMC, SOURCE_QR


def _logger() -> logging.Logger:
    log = logging.getLogger("test-qr-adapter")
    log.handlers.clear()
    log.addHandler(logging.NullHandler())
    return log


@pytest.fixture
async def hub_lookup(tmp_path: Path):
    log = _logger()
    cache = RecordsCache(100, 50, 5, log)
    hub = PositionHub(cache, log)
    store = QrGeoStore(str(tmp_path / "qr.db"), log)
    await store.open()
    lookup = QrGeoLookup(store, log)
    await lookup.replace_catalog(
        [QrGeoEntry("KNOWN", 46.1, 14.2, label="stop")]
    )
    yield hub, lookup, cache
    await store.close()


@pytest.mark.asyncio
async def test_adapter_publishes_on_hit(hub_lookup) -> None:
    hub, lookup, cache = hub_lookup
    adapter = QrGeoAdapter(hub, lookup, _logger(), dedup_window_sec=0)
    await adapter._handle_payload(
        {
            "result": "KNOWN",
            "image-id": "img-1",
            "load-image-time": "2026-07-22T10:00:00+00:00",
        }
    )
    snap = await cache.snapshot()
    assert len(snap) == 1
    assert snap[0].source == SOURCE_QR
    assert snap[0].latitude == 46.1
    assert snap[0].quality == "GOOD"
    assert snap[0].mode == "M"


@pytest.mark.asyncio
async def test_adapter_drops_miss(hub_lookup) -> None:
    hub, lookup, cache = hub_lookup
    adapter = QrGeoAdapter(hub, lookup, _logger(), dedup_window_sec=0)
    await adapter._handle_payload({"result": "UNKNOWN", "image-id": "x"})
    assert await cache.snapshot() == []


@pytest.mark.asyncio
async def test_adapter_dedup(hub_lookup) -> None:
    hub, lookup, cache = hub_lookup
    adapter = QrGeoAdapter(hub, lookup, _logger(), dedup_window_sec=60)
    payload = {
        "result": "KNOWN",
        "load-image-time": "2026-07-22T10:00:00+00:00",
    }
    await adapter._handle_payload(payload)
    await adapter._handle_payload(payload)
    assert len(await cache.snapshot()) == 1


@pytest.mark.asyncio
async def test_two_providers_in_cache(hub_lookup) -> None:
    hub, lookup, cache = hub_lookup
    await hub.publish_record(
        Record(
            key_id=None,
            datetime="2026-07-22T09:59:00+00:00",
            is_valid="A",
            latitude=46.0,
            latitude_hemi="N",
            longitude=14.0,
            longitude_hemi="E",
            speed=1.0,
            direction=90.0,
            mode="A",
            satellites_count=8,
            source=SOURCE_NMEA_RMC,
            quality="GOOD",
        )
    )
    adapter = QrGeoAdapter(hub, lookup, _logger(), dedup_window_sec=0)
    await adapter._handle_payload(
        {
            "result": "KNOWN",
            "load-image-time": "2026-07-22T10:00:00+00:00",
        }
    )
    snap = await cache.snapshot()
    sources = {r.source for r in snap}
    assert SOURCE_NMEA_RMC in sources
    assert SOURCE_QR in sources
    last_qr = await cache.last_matching("qr")
    assert last_qr is not None
    assert last_qr.source == SOURCE_QR
    last_nmea = await cache.last_matching("nmea")
    assert last_nmea is not None
    assert last_nmea.source == SOURCE_NMEA_RMC
