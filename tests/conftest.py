# =============================================================================
# Shared fixtures for API tests (PYTHONPATH=src via pyproject pytest config)
# =============================================================================
from __future__ import annotations

import asyncio
import logging
from collections.abc import Generator
from pathlib import Path

import pytest
from api_server import create_app
from db.cache import RecordsCache
from db.sql import init_db
from models.data_models import (
    ApiConfig,
    AppConfig,
    DatabaseConfig,
    HardwareConfig,
    MemoryConfig,
    SystemConfig,
)
from starlette.testclient import TestClient

TEST_TOKEN = "test-bearer-token-for-api-tests"


def _make_cfg(db_path: Path) -> AppConfig:
    return AppConfig(
        database=DatabaseConfig(db_path=str(db_path), max_rows=10_000),
        hardware=HardwareConfig(port="/dev/null", baud=9600),
        api=ApiConfig(host="127.0.0.1", port=7000, workers=1, token=TEST_TOKEN),
        system=SystemConfig(
            program_directory="/tmp",
            input_path="",
            stdin=False,
            log_dir="logs",
        ),
        memory=MemoryConfig(cache_records_length=500, cache_records_trigger=100),
    )


def _null_logger() -> logging.Logger:
    log = logging.getLogger("pytest-nmea-api")
    log.handlers.clear()
    log.addHandler(logging.NullHandler())
    log.setLevel(logging.DEBUG)
    return log


async def _init_db_once(db_path: str, logger: logging.Logger) -> None:
    conn = await init_db(db_path, logger)
    await conn.close()


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_gnrmc.sqlite"


@pytest.fixture
def app_config(tmp_db_path: Path) -> AppConfig:
    return _make_cfg(tmp_db_path)


@pytest.fixture
def logger() -> logging.Logger:
    return _null_logger()


@pytest.fixture
def cache(app_config: AppConfig, logger: logging.Logger) -> RecordsCache:
    return RecordsCache(
        app_config.memory.cache_records_length,
        app_config.memory.cache_records_trigger,
        logger,
    )


@pytest.fixture
def app(app_config: AppConfig, cache: RecordsCache, logger: logging.Logger):
    asyncio.run(_init_db_once(app_config.database.db_path, logger))
    return create_app(app_config, cache, logger)


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}
