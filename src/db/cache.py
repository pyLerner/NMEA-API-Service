# -*- coding: utf-8 -*-
# =============================================================================
# Кэш и персистентность (UTF-8)
# =============================================================================
"""In-memory deque координат; частичный flush в SQLite."""
import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from api.record_format import format_record_for_api


@dataclass
class Record:
    """Запись координат для кэша и SQLite."""

    key_id: Optional[int]
    datetime: Optional[str]
    is_valid: Optional[str]
    latitude: Optional[float]
    latitude_hemi: Optional[str]
    longitude: Optional[float]
    longitude_hemi: Optional[str]
    speed: Optional[float]
    direction: Optional[float]
    mode: Optional[str]
    satellites_count: Optional[int]
    source: Optional[str] = "nmea/rmc"
    quality: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        raw = {
            "record_id": self.key_id,
            "time": self.datetime,
            "is_valid": self.is_valid,
            "latitude": self.latitude,
            "lat_hemisphere": self.latitude_hemi,
            "longitude": self.longitude,
            "lon_hemisphere": self.longitude_hemi,
            "speed": self.speed,
            "direction": self.direction,
            "mode": self.mode,
            "satellites_count": self.satellites_count,
            "source": self.source,
            "quality": self.quality,
        }
        return format_record_for_api(raw)


def _parse_record_time(value: Optional[str]):
    """Parse ISO8601 record time to aware UTC datetime, or None."""
    if not value:
        return None
    from datetime import datetime, timezone

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class RecordsCache:
    """
    In-memory кэш с ограниченным размером и частичным flush в БД.

    Поведение:
    - Записи хранятся в deque с maxlen = cache_records_length.
    - Счётчик новых записей с прошлого flush.
    - При достижении flush_batch (CacheRecords - ResidualCache) снимается
      flush_batch старейших записей для записи в БД; ResidualCache новейших
      остаются в кэше (без дублирования в SQLite на следующем шаге).
    """

    def __init__(
        self,
        cache_records_length: int,
        cache_records_trigger: int,
        residual_cache: int,
        logger: logging.Logger,
    ) -> None:
        self._cache: deque[Record] = deque(maxlen=cache_records_length)
        self._since_last_flush: int = 0
        self._flush_batch = cache_records_trigger - residual_cache
        self._residual = residual_cache
        self._trigger = self._flush_batch
        self._lock = asyncio.Lock()
        self._logger = logger

    async def add(self, rec: Record) -> bool:
        """
        Добавить запись в кэш.

        Returns:
            True, если после добавления нужен flush в БД.
        """
        async with self._lock:
            self._cache.append(rec)
            self._since_last_flush += 1
            should_flush = self._since_last_flush >= self._trigger
            if should_flush:
                self._logger.info(
                    "Cache trigger reached: %d >= %d",
                    self._since_last_flush,
                    self._trigger,
                )
            return should_flush

    async def snapshot(self) -> list[Record]:
        """Снимок текущего содержимого кэша (для API)."""
        async with self._lock:
            return list(self._cache)

    async def last_matching(self, provider: Optional[str] = None) -> Optional[Record]:
        """Последняя (новейшая) запись, подходящая под provider-фильтр."""
        from sources.hub import matches_provider

        async with self._lock:
            for rec in reversed(self._cache):
                if matches_provider(rec.source, provider):
                    return rec
            return None

    async def filter_records(
        self,
        *,
        provider: Optional[str] = None,
        from_dt=None,
        to_dt=None,
        limit: int = 1000,
    ) -> list[Record]:
        """
        Записи из кэша (новее → старее), фильтр provider + time range.

        from_dt / to_dt — aware datetime или None.
        """
        from sources.hub import matches_provider

        async with self._lock:
            newest_first = list(reversed(self._cache))

        out: list[Record] = []
        for rec in newest_first:
            if not matches_provider(rec.source, provider):
                continue
            if from_dt is not None or to_dt is not None:
                rt = _parse_record_time(rec.datetime)
                if rt is None:
                    continue
                if from_dt is not None and rt < from_dt:
                    continue
                if to_dt is not None and rt > to_dt:
                    continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    async def flush_batch(self) -> list[Record]:
        """
        Снять старейшие записи для записи в БД, оставив ResidualCache новейших.

        Returns:
            Список записей для insert_many (может быть пустым).
        """
        async with self._lock:
            n = min(self._flush_batch, len(self._cache) - self._residual)
            if n <= 0:
                self._since_last_flush = 0
                return []

            to_persist = [self._cache.popleft() for _ in range(n)]
            count_before = self._since_last_flush
            self._since_last_flush = 0
            self._logger.info(
                "Flushing %d cached records (counter was %d, %d remain in cache)",
                len(to_persist),
                count_before,
                len(self._cache),
            )
            return to_persist
