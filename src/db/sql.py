# ========================================================================
# работа с базой SQLite
# ========================================================================
import logging
from pathlib import Path

import aiosqlite

from .cache import Record


async def _ensure_source_column(
    conn: aiosqlite.Connection, logger: logging.Logger
) -> None:
    async with conn.execute("PRAGMA table_info(gnrmc)") as cur:
        rows = await cur.fetchall()
    columns = {row[1] for row in rows}
    if "source" not in columns:
        await conn.execute(
            "ALTER TABLE gnrmc ADD COLUMN source TEXT NOT NULL DEFAULT 'nmea'"
        )
        await conn.commit()
        logger.info("Added source column to gnrmc")


async def init_db(db_path: str, logger: logging.Logger) -> aiosqlite.Connection:
    """
    Initialize the SQLite database (create table if not exists) and PRAGMAs.

    Schema extension: satellites_count and source columns.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA synchronous=NORMAL;")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gnrmc (
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
    await _ensure_source_column(conn, logger)
    logger.info("DB initialized at %s", db_path)
    return conn


async def insert_many(
    conn: aiosqlite.Connection, records: list[Record], logger: logging.Logger
) -> None:
    """
    Insert multiple records into gnrmc in a single transaction.
    """
    if not records:
        return
    async with conn.execute("BEGIN"):
        await conn.executemany(
            """
            INSERT INTO gnrmc (
                datetime, is_valid, latitude, latitude_hemi, longitude, longitude_hemi,
                speed, direction, mode, satellites_count, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.datetime,
                    r.is_valid,
                    r.latitude,
                    r.latitude_hemi,
                    r.longitude,
                    r.longitude_hemi,
                    r.speed,
                    r.direction,
                    r.mode,
                    r.satellites_count,
                    r.source or "nmea",
                )
                for r in records
            ],
        )
        await conn.commit()
    logger.info("Inserted %d records into DB", len(records))


async def enforce_retention(
    conn: aiosqlite.Connection, max_rows: int, logger: logging.Logger
) -> None:
    """
    Enforce retention (MaxRows) by deleting oldest rows beyond the limit.

    This auditor runs periodically and maintains the table size.
    """
    try:
        async with conn.execute("SELECT COUNT(*) FROM gnrmc") as cur:
            row = await cur.fetchone()
            total = int(row[0]) if row else 0
        if total > max_rows:
            to_keep = max_rows
            logger.warning(
                "Retention: total=%d > max_rows=%d, pruning...", total, max_rows
            )
            await conn.execute(
                """
                DELETE FROM gnrmc
                WHERE key_id NOT IN (
                    SELECT key_id FROM gnrmc
                    ORDER BY key_id DESC
                    LIMIT ?
                )
                """,
                (to_keep,),
            )
            await conn.commit()
            logger.info("Retention completed: kept latest %d rows", to_keep)
        else:
            logger.info("Retention ok: total=%d <= max_rows=%d", total, max_rows)
    except Exception as e:
        logger.exception("Retention error: %s", e)
