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
from starlette.testclient import TestClient
from models.data_models import (
    ApiConfig,
    AppConfig,
    DatabaseConfig,
    HardwareConfig,
    LogConfig,
    MemoryConfig,
    NavigationConfig,
    SourceProviderConfig,
    SystemConfig,
    _load_navigation_config,
)
from qr_geo.lookup import QrGeoLookup
from qr_geo.store import QrGeoStore

TEST_TOKEN = "test-bearer-token-for-api-tests"
PROJECT_ETC = Path(__file__).resolve().parent.parent / "etc"


def _default_navigation() -> NavigationConfig:
    return _load_navigation_config(
        {
            "Navigation": {
                "Profile": "tram",
                "VehicleProfilesPath": "VehicleProfiles.toml",
                "PublishMode": "measurement",
                "OutputRateHz": 1,
                "SerialRestartOnRmcLoss": "no",
                "SerialRestartAfterSec": 90,
            }
        },
        PROJECT_ETC,
    )


def _make_cfg(db_path: Path, qr_db_path: Path) -> AppConfig:
    return AppConfig(
        database=DatabaseConfig(db_path=str(db_path), max_rows=10_000),
        hardware=HardwareConfig(port="/dev/null", baud=9600),
        api=ApiConfig(host="127.0.0.1", port=7000, workers=1, token=TEST_TOKEN),
        system=SystemConfig(
            program_directory="/tmp",
            input_path="",
            stdin=False,
        ),
        log=LogConfig(
            log_dir="logs",
            log_name="gnrmc.log",
            log_level=logging.INFO,
            max_logs=5,
            max_size_bytes=5_242_880,
            log_row_nmea=False,
            row_nmea_name="nmea-row.log",
        ),
        memory=MemoryConfig(
            cache_records_length=500,
            cache_records_trigger=100,
            residual_cache=10,
        ),
        navigation=_default_navigation(),
        sources=(
            SourceProviderConfig(
                name="nmea",
                enabled=True,
                type="serial-nmea",
                params={"HardwarePort": "/dev/null", "Baud": 9600},
            ),
            SourceProviderConfig(
                name="qr-geo",
                enabled=False,
                type="qr-geo",
                params={"GeoDbPath": str(qr_db_path)},
            ),
        ),
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


async def _open_qr_lookup(qr_db: Path, logger: logging.Logger) -> QrGeoLookup:
    store = QrGeoStore(str(qr_db), logger)
    await store.open()
    lookup = QrGeoLookup(store, logger)
    await lookup.reload()
    return lookup


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_gnrmc.sqlite"


@pytest.fixture
def tmp_qr_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_qr_geo.sqlite"


@pytest.fixture
def app_config(tmp_db_path: Path, tmp_qr_db_path: Path) -> AppConfig:
    return _make_cfg(tmp_db_path, tmp_qr_db_path)


@pytest.fixture
def logger() -> logging.Logger:
    return _null_logger()


@pytest.fixture
def cache(app_config: AppConfig, logger: logging.Logger) -> RecordsCache:
    return RecordsCache(
        app_config.memory.cache_records_length,
        app_config.memory.cache_records_trigger,
        app_config.memory.residual_cache,
        logger,
    )


@pytest.fixture
def qr_geo_lookup(tmp_qr_db_path: Path, logger: logging.Logger) -> QrGeoLookup:
    return asyncio.run(_open_qr_lookup(tmp_qr_db_path, logger))


@pytest.fixture
def app(
    app_config: AppConfig,
    cache: RecordsCache,
    logger: logging.Logger,
    qr_geo_lookup: QrGeoLookup,
):
    asyncio.run(_init_db_once(app_config.database.db_path, logger))
    return create_app(app_config, cache, logger, qr_geo_lookup=qr_geo_lookup)


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}
