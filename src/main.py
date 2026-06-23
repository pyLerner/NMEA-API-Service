"""
Единое асинхронное приложение GNRMC.

Запускает:
- чтение NMEA (RS-232/RS-485 / файл / stdin), парсинг RMC/ECEFPOSVEL и GGA;
- in-memory кэш с частичным flush в SQLite;
- HTTP API (FastAPI) для выдачи координат;
- retention-аудит таблицы SQLite.

Конфигурация: TOML (--config), секции [Log], [Memory], [Database], …
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
from debug_trace import debug_log
from runner_task import db_flusher_task, nmea_reader_task

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
        "CacheLen=%d | FlushBatch=%d | ResidualCache=%d | LogRowNMEA=%s",
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
    )
    # #region agent log
    debug_log(
        "main.py:startup",
        "app starting",
        {
            "db_path": cfg.database.db_path,
            "workers": cfg.api.workers,
            "cache_trigger": cfg.memory.flush_batch,
            "serial_port": cfg.hardware.port,
        },
        hypothesis_id="A,B",
    )
    # #endregion

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

    # Tasks: reader, flusher, api
    reader_t = asyncio.create_task(
        nmea_reader_task(cfg, cache, logger, nmea_row_logger), name="nmea_reader"
    )
    flusher_t = asyncio.create_task(
        db_flusher_task(cfg, cache, db_conn, logger), name="db_flusher"
    )
    api_t = asyncio.create_task(server.serve(), name="api_server")

    async def _heartbeat_task() -> None:
        beat = 0
        while True:
            await asyncio.sleep(5)
            beat += 1
            # #region agent log
            debug_log(
                "main.py:heartbeat",
                "app alive",
                {"beat": beat, "reader_done": reader_t.done(), "api_done": api_t.done()},
                hypothesis_id="A,E",
            )
            # #endregion

    heartbeat_t = asyncio.create_task(_heartbeat_task(), name="heartbeat")

    # Graceful shutdown handling
    shutdown_event = asyncio.Event()

    def _handle_signal(sig: int, frame: Any | None) -> None:
        logger.info("Received signal %s, shutting down...", sig)
        # #region agent log
        debug_log(
            "main.py:signal",
            "shutdown signal received",
            {"signal": sig},
            hypothesis_id="A,E",
        )
        # #endregion
        shutdown_event.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, _handle_signal)
        except Exception:
            # Signals may not be available on some platforms
            pass

    # Wait for shutdown event
    await shutdown_event.wait()

    # #region agent log
    debug_log(
        "main.py:shutdown",
        "shutdown_event set, cancelling tasks",
        {
            "reader_done": reader_t.done(),
            "flusher_done": flusher_t.done(),
            "api_done": api_t.done(),
            "api_exc": str(api_t.exception()) if api_t.done() and api_t.exception() else None,
        },
        hypothesis_id="A,B,E",
    )
    # #endregion

    # Cancel background tasks
    for t in (reader_t, flusher_t, heartbeat_t):
        t.cancel()
    await asyncio.gather(reader_t, flusher_t, heartbeat_t, return_exceptions=True)

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
