# -*- coding: utf-8 -*-
"""PositionHub: fan-in адаптеров в RecordsCache + fan-out SSE."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from db.cache import Record, RecordsCache
from sources.events import NavPositionEvent


def provider_id_from_source(source: Optional[str]) -> Optional[str]:
    """Сегмент source до '/' или весь source, если слэша нет."""
    if source is None:
        return None
    if "/" in source:
        return source.split("/", 1)[0]
    return source


def matches_provider(source: Optional[str], provider_filter: Optional[str]) -> bool:
    """True, если фильтр пуст или source принадлежит provider."""
    if not provider_filter:
        return True
    return provider_id_from_source(source) == provider_filter


class PositionHub:
    """
    Общий поток координат: publish → cache + подписчики SSE.

    Подписчик получает Record (или None при shutdown очереди).
    """

    def __init__(
        self,
        cache: RecordsCache,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._cache = cache
        self._logger = logger or logging.getLogger(__name__)
        self._subscribers: list[tuple[Optional[str], asyncio.Queue[Record | None]]] = []
        self._lock = asyncio.Lock()

    @property
    def cache(self) -> RecordsCache:
        return self._cache

    async def publish_record(self, rec: Record) -> None:
        """Добавить Record в кэш и разослать подходящим SSE-подписчикам."""
        await self._cache.add(rec)
        async with self._lock:
            targets = list(self._subscribers)
        for provider_filter, queue in targets:
            if matches_provider(rec.source, provider_filter):
                try:
                    queue.put_nowait(rec)
                except asyncio.QueueFull:
                    try:
                        _ = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        queue.put_nowait(rec)
                    except asyncio.QueueFull:
                        self._logger.warning(
                            "SSE subscriber queue full; dropped update source=%s",
                            rec.source,
                        )

    async def publish(self, event: NavPositionEvent) -> None:
        """Конвертировать NavPositionEvent → Record и опубликовать."""
        rec = Record(
            key_id=None,
            datetime=event.datetime_iso,
            is_valid=event.is_valid,
            latitude=event.latitude,
            latitude_hemi=event.latitude_hemi,
            longitude=event.longitude,
            longitude_hemi=event.longitude_hemi,
            speed=event.speed,
            direction=event.direction,
            mode=event.mode,
            satellites_count=event.satellites_count,
            source=event.source,
            quality=event.quality,
        )
        await self.publish_record(rec)

    async def subscribe(
        self, provider_filter: Optional[str] = None
    ) -> asyncio.Queue[Record | None]:
        """Зарегистрировать SSE-подписчика (фильтр provider опционален)."""
        queue: asyncio.Queue[Record | None] = asyncio.Queue(maxsize=64)
        async with self._lock:
            self._subscribers.append((provider_filter, queue))
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[Record | None]) -> None:
        async with self._lock:
            self._subscribers = [
                (filt, q) for filt, q in self._subscribers if q is not queue
            ]
