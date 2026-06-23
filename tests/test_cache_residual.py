# =============================================================================
# Тесты частичного flush кэша (ResidualCache)
# =============================================================================
from __future__ import annotations

import asyncio
import logging

from db.cache import Record, RecordsCache


def _null_logger() -> logging.Logger:
    log = logging.getLogger("pytest-cache-residual")
    log.handlers.clear()
    log.addHandler(logging.NullHandler())
    return log


def _record(tag: str) -> Record:
    return Record(
        key_id=None,
        datetime=tag,
        is_valid="A",
        latitude=1.0,
        latitude_hemi="N",
        longitude=1.0,
        longitude_hemi="E",
        speed=0.0,
        direction=0.0,
        mode="A",
        satellites_count=0,
        source="nmea",
    )


async def _add_many(cache: RecordsCache, count: int, prefix: str) -> None:
    for i in range(count):
        await cache.add(_record(f"{prefix}-{i}"))


def test_flush_batch_keeps_residual() -> None:
    cache = RecordsCache(
        cache_records_length=500,
        cache_records_trigger=100,
        residual_cache=10,
        logger=_null_logger(),
    )

    asyncio.run(_add_many(cache, 90, "a"))
    flushed = asyncio.run(cache.flush_batch())

    assert len(flushed) == 80
    snapshot = asyncio.run(cache.snapshot())
    assert len(snapshot) == 10
    assert snapshot[-1].datetime == "a-89"


def test_two_flushes_no_duplicate_datetimes_in_db_batches() -> None:
    cache = RecordsCache(500, 100, 10, _null_logger())

    asyncio.run(_add_many(cache, 90, "b"))
    first = asyncio.run(cache.flush_batch())
    asyncio.run(_add_many(cache, 90, "c"))
    second = asyncio.run(cache.flush_batch())

    first_times = {r.datetime for r in first}
    second_times = {r.datetime for r in second}
    assert not first_times.intersection(second_times)

    snapshot = asyncio.run(cache.snapshot())
    assert len(snapshot) == 10
    assert snapshot[-1].datetime == "c-89"


def test_flush_empty_when_cache_smaller_than_residual() -> None:
    cache = RecordsCache(500, 100, 10, _null_logger())
    asyncio.run(_add_many(cache, 5, "d"))
    flushed = asyncio.run(cache.flush_batch())
    assert flushed == []
    assert len(asyncio.run(cache.snapshot())) == 5
