# -*- coding: utf-8 -*-
# =============================================================================
# Фоновые задачи: NMEA reader, fusion tick, DB flusher (UTF-8)
# =============================================================================
"""
Асинхронные задачи ingestion и публикации координат.

- nmea_reader_task — чтение NMEA, вызов NavFusion.ingest_*;
- fusion_tick_task — внутренний predict и публикация по PublishMode;
- db_flusher_task — сброс кэша в SQLite и retention.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import aiosqlite

from db.cache import Record, RecordsCache
from db.sql import enforce_retention, insert_many
from models.data_models import AppConfig
from navigation.fusion import FusionOutput, NavFusion
from nmea.parsing import (
    ECEFPOSVEL_RE,
    GGA_RE,
    GNRMC_RE,
    parse_ecefposvel,
    parse_gga_satellites,
    parse_rmc,
)
from serial_port.line_iterators import (
    iter_file_lines,
    iter_reopenable_serial_lines,
    iter_stdin_lines,
)


def fusion_output_to_record(out: FusionOutput) -> Record:
    return Record(
        key_id=None,
        datetime=out.datetime_iso,
        is_valid=out.is_valid,
        latitude=out.latitude,
        latitude_hemi=out.latitude_hemi,
        longitude=out.longitude,
        longitude_hemi=out.longitude_hemi,
        speed=out.speed,
        direction=out.direction,
        mode=out.mode,
        satellites_count=out.satellites_count,
        source=out.source,
        quality=out.quality,
    )


async def _cache_fusion_output(cache: RecordsCache, out: FusionOutput) -> None:
    await cache.add(fusion_output_to_record(out))


async def fusion_tick_task(
    cfg: AppConfig,
    fusion: NavFusion,
    cache: RecordsCache,
    logger: logging.Logger,
) -> None:
    """
    Периодический predict Kalman на частоте OutputRateHz.

    При PublishMode timer/hybrid и should_publish_timer() — запись в кэш.
    """
    interval = 1.0 / cfg.navigation.output_rate_hz
    logger.info(
        "Fusion tick: %.1f Hz predict, publish_mode=%s",
        cfg.navigation.output_rate_hz,
        cfg.navigation.publish_mode.value,
    )
    try:
        while True:
            await asyncio.sleep(interval)
            fusion.predict_internal_only(interval)
            if fusion.should_publish_timer():
                out = fusion.build_publish_output()
                if out is not None:
                    await _cache_fusion_output(cache, out)
    except asyncio.CancelledError:
        logger.info("Fusion tick task cancelled")
        raise


# Backward-compatible alias
fusion_output_task = fusion_tick_task


async def nmea_reader_task(
    cfg: AppConfig,
    cache: RecordsCache,
    logger: logging.Logger,
    nmea_row_logger: Optional[logging.Logger],
    fusion: NavFusion,
) -> None:
    """
    Читать NMEA (serial / файл / stdin), логировать сырьё, кормить NavFusion.

    При ненулевом FusionOutput от ingest — запись в RecordsCache.
    """
    latest_satellites: Optional[int] = None
    serial_restart_done = False

    async def _process_line(line: str) -> None:
        nonlocal latest_satellites, serial_restart_done
        s = line.strip()
        if not s:
            return

        if nmea_row_logger is not None:
            nmea_row_logger.info(s)

        if GGA_RE.match(s):
            sat = parse_gga_satellites(s)
            if sat is not None:
                latest_satellites = sat
            return

        out: Optional[FusionOutput] = None
        if GNRMC_RE.match(s):
            rec = parse_rmc(s, latest_satellites)
            if rec:
                out = fusion.ingest_rmc(rec)
                serial_restart_done = False
        elif ECEFPOSVEL_RE.match(s):
            rec = parse_ecefposvel(s)
            if rec:
                out = fusion.ingest_ecef(rec)

        if out is not None:
            await _cache_fusion_output(cache, out)

    if cfg.system.stdin:
        async for line in iter_stdin_lines():
            await _process_line(line)
        return

    if cfg.system.input_path:
        async for line in iter_file_lines(cfg.system.input_path):
            await _process_line(line)
        return

    serial = await iter_reopenable_serial_lines(cfg.hardware.port, cfg.hardware.baud)
    async for line in serial:
        await _process_line(line)
        if not serial_restart_done and cfg.navigation.serial_restart_on_rmc_loss:
            if fusion.last_rmc_mono > 0:
                elapsed = time.monotonic() - fusion.last_rmc_mono
                if elapsed >= cfg.navigation.serial_restart_after_sec:
                    logger.warning(
                        "No GNRMC for %.0fs — reopening serial port %s",
                        elapsed,
                        cfg.hardware.port,
                    )
                    await serial.reopen()
                    serial_restart_done = True


async def db_flusher_task(
    cfg: AppConfig,
    cache: RecordsCache,
    db_conn: aiosqlite.Connection,
    logger: logging.Logger,
) -> None:
    """
    Periodically flush cache to DB and enforce retention.
    """
    try:
        while True:
            await asyncio.sleep(1.0)
            batch = await cache.flush_batch()
            if batch:
                await insert_many(db_conn, batch, logger)
            await enforce_retention(db_conn, cfg.database.max_rows, logger)
    except asyncio.CancelledError:
        logger.info("DB flusher task cancelled")
        raise
