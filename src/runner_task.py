# =============================================================================
# Runner tasks
# =============================================================================
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
from db.cache import Record, RecordsCache
from db.sql import enforce_retention, insert_many

# Config from Toml
from models.data_models import AppConfig
from nmea.parsing import (
    GGA_RE,
    GNRMC_RE,
    parse_gga_satellites,
    parse_rmc,
)

# Serial port and file line iterators
from serial_port.line_iterators import (
    iter_file_lines,
    iter_serial_lines,
    iter_stdin_lines,
)


async def nmea_reader_task(
    cfg: AppConfig,
    cache: RecordsCache,
    logger: logging.Logger,
) -> None:
    """
    Continuously read NMEA sentences, update satellites hint from GGA,
    parse RMC records, add them to cache, and trigger DB flush via an event.

    This task signals the flusher by setting an asyncio.Event when needed.
    """
    satellites_hint: Optional[int] = None

    # Choose input source
    if cfg.system.input_path:
        line_iter = iter_file_lines(cfg.system.input_path)
        logger.info("Reading NMEA from file: %s", cfg.system.input_path)
    elif cfg.system.stdin:
        line_iter = iter_stdin_lines()
        logger.info("Reading NMEA from stdin")
    else:
        line_iter = iter_serial_lines(cfg.hardware.port, cfg.hardware.baud)
        logger.info(
            "Reading NMEA from serial: %s (baud=%d)",
            cfg.hardware.port,
            cfg.hardware.baud,
        )

    # Local event to notify flusher (shared by reference)
    # We'll store it globally in app state for the flusher to wait on.
    from_context = asyncio.get_running_loop()

    while True:
        try:
            async for raw in line_iter:
                line = raw.strip()
                if not line or not line.startswith("$G"):
                    await asyncio.sleep(0.01)
                    continue

                # Update satellites hint from GGA
                if GGA_RE.match(line):
                    sat = parse_gga_satellites(line)
                    if isinstance(sat, int):
                        satellites_hint = sat
                    continue

                # Parse and cache RMC
                if not GNRMC_RE.match(line):
                    continue
                parsed = parse_rmc(line, satellites_hint)
                if not parsed:
                    logger.warning("RMC parse or checksum error: %s", line)
                    continue
                
                rec = Record(
                    #TODO: задать значения по умолчанию
                    # Если записи нет в БД, record_id == 0
                    key_id=parsed.get("key_id", 0),  # совместимость со старой версией
                    datetime=parsed.get(
                        "datetime", 
                        datetime
                         .now(timezone.utc)
                         .replace(microsecond=0)
                         .isoformat()  
                    ),
                    is_valid=parsed.get("is_valid"),
                    latitude=parsed.get("latitude", 0.0),
                    latitude_hemi=parsed.get("latitude_hemi", "N"),
                    longitude=parsed.get("longitude", 0.0),
                    longitude_hemi=parsed.get("longitude_hemi", "E"),
                    speed=parsed.get("speed", 0.0),
                    direction=parsed.get("direction", 0.0),
                    mode=parsed.get("mode"),
                    satellites_count=parsed.get("satellites_count", 0),
                )

                should_flush = await cache.add(rec)
                if should_flush:
                    # Set a global event so the flusher wakes up
                    flush_event: asyncio.Event = from_context._flush_event  # type: ignore[attr-defined]
                    flush_event.set()

                # Log compactly
                logger.info(
                    "Cached datetime=%s valid=%s lat=%s%s lon=%s%s speed=%s dir=%s sat=%s",
                    rec.datetime,
                    rec.is_valid,
                    f"{rec.latitude:.6f}" if rec.latitude is not None else "",
                    rec.latitude_hemi or "",
                    f"{rec.longitude:.6f}" if rec.longitude is not None else "",
                    rec.longitude_hemi or "",
                    rec.speed,
                    rec.direction,
                    rec.satellites_count,
                )

            # If file/stdin iterators finish, sleep a bit and exit loop
            logger.info("Input iterator finished")
            await asyncio.sleep(0.5)
            break

        except asyncio.CancelledError:
            logger.info("NMEA reader task cancelled")
            break
        except Exception as e:
            logger.exception("NMEA reader error: %s", e)
            await asyncio.sleep(1.0)


async def db_flusher_task(
    cfg: AppConfig,
    cache: RecordsCache,
    db_conn: aiosqlite.Connection,
    logger: logging.Logger,
) -> None:
    """
    Wait on a flush event; when triggered, flush all cached records to DB
    and then enforce retention.

    The event is cleared after each flush.
    """
    loop = asyncio.get_running_loop()
    # Create a flush event on the loop context so reader can trigger it
    if not hasattr(loop, "_flush_event"):
        loop._flush_event = asyncio.Event()  # type: ignore[attr-defined]

    flush_event: asyncio.Event = loop._flush_event  # type: ignore[attr-defined]

    while True:
        try:
            await flush_event.wait()
            # Clear the event immediately to allow new triggers during flush
            flush_event.clear()

            # Flush all records from cache and persist
            to_persist = await cache.flush_all()
            if to_persist:
                await insert_many(db_conn, to_persist, logger)
                # Retention (auditor role)
                await enforce_retention(db_conn, cfg.database.max_rows, logger)
            else:
                logger.info("Flush triggered but cache was empty")

        except asyncio.CancelledError:
            logger.info("DB flusher task cancelled")
            break
        except Exception as e:
            logger.exception("DB flusher error: %s", e)
            await asyncio.sleep(1.0)

