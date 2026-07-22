# -*- coding: utf-8 -*-
"""In-memory словарь QR → GeoPoint."""

from __future__ import annotations

import asyncio
import logging

from qr_geo.models import GeoPoint, QrGeoEntry
from qr_geo.store import QrGeoStore


class QrGeoLookup:
    """Горячий кэш справочника; обновляется только через Store под lock."""

    def __init__(
        self,
        store: QrGeoStore,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._logger = logger or logging.getLogger(__name__)
        self._points: dict[str, GeoPoint] = {}
        self._lock = asyncio.Lock()

    @property
    def store(self) -> QrGeoStore:
        return self._store

    def get(self, qr_value: str) -> GeoPoint | None:
        return self._points.get(qr_value)

    def __len__(self) -> int:
        return len(self._points)

    async def _reload_unlocked(self) -> int:
        self._points = await self._store.load_all_enabled()
        self._logger.info("QrGeoLookup reloaded count=%d", len(self._points))
        return len(self._points)

    async def reload(self) -> int:
        async with self._lock:
            return await self._reload_unlocked()

    async def replace_catalog(self, entries: list[QrGeoEntry]) -> int:
        async with self._lock:
            count = await self._store.replace_all(entries)
            await self._reload_unlocked()
            return count

    async def append_catalog(self, entries: list[QrGeoEntry]) -> int:
        async with self._lock:
            count = await self._store.upsert_many(entries)
            await self._reload_unlocked()
            return count
