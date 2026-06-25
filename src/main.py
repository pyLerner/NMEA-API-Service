# -*- coding: utf-8 -*-
"""
Единое асинхронное приложение GNRMC / NavFusion v2 (UTF-8).

Оркестрация: NMEA reader, fusion tick, DB flusher, HTTP API в одном процессе.
Конфигурация: TOML (--config), см. plan/KALMAN-ECEF-FUSION-v2.md.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path
from typing import Any

# FastAPI app
from api_server import create_app

# ---- Local imports
# Cache settings and SQL management
from db.cache import RecordsCache
from db.sql import init_db

# --- Local logger utility (kept from original project interface) ---
from log_config.log_config import setup_logger

# Config from Toml
from models.data_models import load_config

# Task Runner
from runner_task import db_flusher_task, fusion_tick_task, nmea_reader_task
from navigation.fusion import NavFusion

# =============================================================================
# Entry point and orchestration
# =============================================================================


async def main_async(args: argparse.Namespace) -> None:
    """
    Main async orchestrator:
    - Load config and set up logger
    - Initialize DB
    - Create cache
    - Launch tasks: NMEA reader, DB flusher, API server
    - Handle graceful shutdown on SIGINT/SIGTERM
    """
    config_path = Path(args.config)
    cfg = load_config(config_path)

    logger, nmea_row_logger = setup_logger(cfg.log)

    logger.info("=== GNRMC Unified App starting ===")
    logger.info(
        "Config: %s | DB=%s | MaxRows=%d | Host=%s:%d | Workers=%d | "
        "CacheLen=%d | FlushBatch=%d | ResidualCache=%d | LogRowNMEA=%s | "
        "Profile=%s | PublishMode=%s | OutputHz=%d | APIWorkers=%d",
        config_path,
        cfg.database.db_path,
        cfg.database.max_rows,
        cfg.api.host,
        cfg.api.port,
        cfg.api.workers,
        cfg.memory.cache_records_length,
        cfg.memory.flush_batch,
        cfg.memory.residual_cache,
        cfg.log.log_row_nmea,
        cfg.navigation.profile_name,
        cfg.navigation.publish_mode.value,
        cfg.navigation.output_rate_hz,
        cfg.api.workers,
    )

    if cfg.api.workers > 1:
        logger.warning(
            "API Workers=%d: in-memory cache is not shared across uvicorn "
            "worker processes; set [API] Workers = 1 for consistent last-coords",
            cfg.api.workers,
        )

    # DB
    db_conn = await init_db(cfg.database.db_path, logger)

    # Cache
    cache = RecordsCache(
        cfg.memory.cache_records_length,
        cfg.memory.cache_records_trigger,
        cfg.memory.residual_cache,
        logger,
    )

    # Create API
    app = create_app(cfg, cache, logger)

    # Create background tasks
    loop = asyncio.get_running_loop()

    # Prepare UVicorn server programmatically
    import uvicorn

    config = uvicorn.Config(
        app=app,
        host=cfg.api.host,
        port=cfg.api.port,
        workers=cfg.api.workers,
        log_level=logging.getLevelName(cfg.log.log_level).lower(),
        loop="asyncio",
    )
    server = uvicorn.Server(config=config)

    fusion = NavFusion(
        cfg.navigation.profile,
        publish_mode=cfg.navigation.publish_mode,
        logger=logger,
    )

    # Tasks: reader, fusion tick, flusher, api
    reader_t = asyncio.create_task(
        nmea_reader_task(cfg, cache, logger, nmea_row_logger, fusion),
        name="nmea_reader",
    )
    fusion_t = asyncio.create_task(
        fusion_tick_task(cfg, fusion, cache, logger), name="fusion_tick"
    )
    flusher_t = asyncio.create_task(
        db_flusher_task(cfg, cache, db_conn, logger), name="db_flusher"
    )
    api_t = asyncio.create_task(server.serve(), name="api_server")

    # Graceful shutdown handling
    shutdown_event = asyncio.Event()

    def _handle_signal(sig: int, frame: Any | None) -> None:
        logger.info("Received signal %s, shutting down...", sig)
        shutdown_event.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, _handle_signal)
        except Exception:
            # Signals may not be available on some platforms
            pass

    # Wait for shutdown event
    await shutdown_event.wait()

    # Cancel background tasks
    for t in (reader_t, fusion_t, flusher_t):
        t.cancel()
    await asyncio.gather(reader_t, fusion_t, flusher_t, return_exceptions=True)

    # Stop API server if running
    if server:
        await server.shutdown()

    await db_conn.close()
    logger.info("=== GNRMC Unified App stopped ===")


def parse_args() -> argparse.Namespace:
    """
    Parse CLI arguments for unified runner.
    """
    prog = "gnrmc"
    ap = argparse.ArgumentParser(
        description="Unified async GNRMC app (driver + API + auditor)"
    )
    ap.add_argument(
        "--config",
        type=Path,
        default=f"/usr/local/etc/{prog}.toml",
        help="Path to TOML configuration file",
    )
    return ap.parse_args()


def main() -> None:
    """
    Synchronous entry point: collects args and runs async main.
    """
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
