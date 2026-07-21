# =============================================================================
# SQLite quality column migration
# =============================================================================
from __future__ import annotations

import asyncio
import logging

import aiosqlite
from db.cache import Record
from db.sql import init_db, insert_many


def _null_logger() -> logging.Logger:
    log = logging.getLogger("pytest-sql-quality")
    log.handlers.clear()
    log.addHandler(logging.NullHandler())
    return log


async def _legacy_db_without_quality(path: str) -> None:
    conn = await aiosqlite.connect(path)
    await conn.execute(
        """
        CREATE TABLE gnrmc (
            key_id INTEGER PRIMARY KEY AUTOINCREMENT,
            datetime TEXT,
            is_valid CHAR(1),
            latitude REAL,
            latitude_hemi CHAR(1),
            longitude REAL,
            longitude_hemi CHAR(1),
            speed REAL,
            direction REAL,
            mode CHAR(1),
            satellites_count INTEGER,
            delivered INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'nmea'
        )
        """
    )
    await conn.commit()
    await conn.close()


async def _run_migration_test(db_path: str) -> tuple[bool, str | None]:
    logger = _null_logger()
    conn = await init_db(db_path, logger)
    async with conn.execute("PRAGMA table_info(gnrmc)") as cur:
        cols = {row[1] for row in await cur.fetchall()}
    if "quality" not in cols:
        await conn.close()
        return False, None

    rec = Record(
        key_id=None,
        datetime="2024-01-01T00:00:00+00:00",
        is_valid="A",
        latitude=1.0,
        latitude_hemi="N",
        longitude=2.0,
        longitude_hemi="E",
        speed=0.0,
        direction=0.0,
        mode="A",
        satellites_count=5,
        source="fusion",
        quality="KF_ECEF",
    )
    await insert_many(conn, [rec], logger)
    async with conn.execute(
        "SELECT quality FROM gnrmc ORDER BY key_id DESC LIMIT 1"
    ) as cur:
        row = await cur.fetchone()
    await conn.close()
    return True, row[0] if row else None


def test_quality_column_migrated_on_legacy_db(tmp_path) -> None:
    db_path = str(tmp_path / "legacy.db")
    asyncio.run(_legacy_db_without_quality(db_path))
    ok, quality = asyncio.run(_run_migration_test(db_path))
    assert ok
    assert quality == "KF_ECEF"
