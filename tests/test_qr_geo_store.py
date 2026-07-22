# -*- coding: utf-8 -*-
"""Тесты QrGeoStore / QrGeoLookup."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from qr_geo.lookup import QrGeoLookup
from qr_geo.models import QrGeoEntry
from qr_geo.store import QrGeoStore


@pytest.fixture
async def lookup(tmp_path: Path) -> QrGeoLookup:
    log = logging.getLogger("test-qr-store")
    log.addHandler(logging.NullHandler())
    store = QrGeoStore(str(tmp_path / "qr_geo.db"), log)
    await store.open()
    lu = QrGeoLookup(store, log)
    await lu.reload()
    yield lu
    await store.close()


@pytest.mark.asyncio
async def test_replace_and_lookup(lookup: QrGeoLookup) -> None:
    entries = [
        QrGeoEntry("A", 46.0, 14.0),
        QrGeoEntry("B", 47.0, 15.0, enabled=False),
    ]
    count = await lookup.replace_catalog(entries)
    assert count == 2
    assert lookup.get("A") is not None
    assert lookup.get("A").latitude == 46.0
    assert lookup.get("B") is None  # disabled not in RAM
    assert len(lookup) == 1


@pytest.mark.asyncio
async def test_append_upsert(lookup: QrGeoLookup) -> None:
    await lookup.replace_catalog([QrGeoEntry("A", 46.0, 14.0)])
    await lookup.append_catalog([QrGeoEntry("A", 46.5, 14.5), QrGeoEntry("C", 1.0, 2.0)])
    assert lookup.get("A").latitude == 46.5
    assert lookup.get("C") is not None
    assert len(lookup) == 2
