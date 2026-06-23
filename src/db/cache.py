# =============================================================================
# Кэш и персистентность
# =============================================================================
import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional


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
    source: Optional[str] = "nmea"

    def to_dict(self) -> dict[str, Any]:
        return {
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
        }


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
