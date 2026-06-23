# =============================================================================
# nmea_reader_task: RMC priority and ECEFPOSVEL fallback
# =============================================================================
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from db.cache import RecordsCache
from models.data_models import (
    ApiConfig,
    AppConfig,
    DatabaseConfig,
    HardwareConfig,
    LogConfig,
    MemoryConfig,
    SystemConfig,
)
from runner_task import nmea_reader_task

REVKECEF = (
    "$ECEFPOSVEL,124015.000,3985352.629186,-54462.755461,"
    "4962832.255023,-0.008022,0.003776,0.022063*28\n"
)
SAMPLE_RMC = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\n"


def _make_cfg(input_path: str) -> AppConfig:
    return AppConfig(
        database=DatabaseConfig(db_path="/tmp/unused.db", max_rows=1000),
        hardware=HardwareConfig(port="/dev/null", baud=9600),
        api=ApiConfig(host="127.0.0.1", port=7000, workers=1, token="t"),
        system=SystemConfig(
            program_directory="/tmp",
            input_path=input_path,
            stdin=False,
        ),
        log=LogConfig(
            log_dir=str(Path(input_path).parent / "logs"),
            log_name="gnrmc.log",
            log_level=logging.INFO,
            max_logs=5,
            max_size_bytes=5_242_880,
            log_row_nmea=False,
            row_nmea_name="nmea-row.log",
        ),
        memory=MemoryConfig(
            cache_records_length=100,
            cache_records_trigger=1000,
            residual_cache=10,
        ),
    )


def _null_logger() -> logging.Logger:
    log = logging.getLogger("pytest-runner-task")
    log.handlers.clear()
    log.addHandler(logging.NullHandler())
    return log


async def _run_reader(cfg: AppConfig, cache: RecordsCache, logger: logging.Logger) -> None:
    await nmea_reader_task(cfg, cache, logger)


def test_reader_ecef_only_populates_cache(tmp_path: Path) -> None:
    nmea_file = tmp_path / "ecef.nmea"
    nmea_file.write_text(REVKECEF, encoding="utf-8")
    cache = RecordsCache(100, 1000, 10, _null_logger())
    cfg = _make_cfg(str(nmea_file))

    asyncio.run(_run_reader(cfg, cache, _null_logger()))

    snapshot = asyncio.run(cache.snapshot())
    assert len(snapshot) == 1
    assert snapshot[0].source == "ecef"
    assert snapshot[0].is_valid == "A"


def test_reader_rmc_blocks_ecef_fallback(tmp_path: Path) -> None:
    nmea_file = tmp_path / "mixed.nmea"
    nmea_file.write_text(SAMPLE_RMC + REVKECEF, encoding="utf-8")
    cache = RecordsCache(100, 1000, 10, _null_logger())
    cfg = _make_cfg(str(nmea_file))

    asyncio.run(_run_reader(cfg, cache, _null_logger()))

    snapshot = asyncio.run(cache.snapshot())
    assert len(snapshot) == 1
    assert snapshot[0].source == "nmea"
