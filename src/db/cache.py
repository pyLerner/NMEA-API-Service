# =============================================================================
# Cache and persistence
# =============================================================================
import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Record:
    """Typed record to store in cache and persist to DB."""

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

    def to_dict(self) -> dict[str, Any]:
        return {
            # "datetime": self.datetime,
            # "is_valid": self.is_valid,
            # "latitude": self.latitude,
            # "latitude_hemi": self.latitude_hemi,
            # "longitude": self.longitude,
            # "longitude_hemi": self.longitude_hemi,
            # "speed": self.speed,
            # "direction": self.direction,
            # "mode": self.mode,
            # "satellites_count": self.satellites_count,
            # Совместимость с предыдущей версией:
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
        }


class RecordsCache:
    """
    In-memory cache with a bounded size and a flush trigger counter.

    Behavior:
    - Append records to a deque with maxlen = cache_records_length.
    - Track count of new records since last DB flush.
    - When count reaches cache_records_trigger, flush ALL records currently in cache.
      After a successful flush, clear the cache and reset the counter.

    Thread-safety:
    - Designed for asyncio; use the provided async lock to coordinate access.
    """

    def __init__(
        self,
        cache_records_length: int,
        cache_records_trigger: int,
        logger: logging.Logger,
    ) -> None:
        self._cache: deque[Record] = deque(maxlen=cache_records_length)
        self._since_last_flush: int = 0
        self._trigger: int = cache_records_trigger
        self._lock = asyncio.Lock()
        self._logger = logger

    async def add(self, rec: Record) -> bool:
        """
        Add a record to cache.

        Returns:
            True if a flush should be triggered after this addition.
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
        """
        Return a snapshot list of records currently in cache.

        Use for API responses (/AllCoords).
        """
        async with self._lock:
            return list(self._cache)

    async def flush_all(self) -> list[Record]:
        """
        Return all records and clear cache, resetting the counter.

        Returns:
            A list of records to persist.
        """
        async with self._lock:
            data = list(self._cache)
            self._cache.clear()
            count_before = self._since_last_flush
            self._since_last_flush = 0
            self._logger.info(
                "Flushing %d cached records (counter was %d)", len(data), count_before
            )
            return data
