# -*- coding: utf-8 -*-
"""SQLite-хранилище справочника qr_geo."""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from qr_geo.models import GeoPoint, QrGeoEntry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS qr_geo (
    qr_value   TEXT PRIMARY KEY,
    latitude   REAL NOT NULL,
    longitude  REAL NOT NULL,
    lat_hemi   TEXT NOT NULL DEFAULT 'N',
    lon_hemi   TEXT NOT NULL DEFAULT 'E',
    label      TEXT,
    enabled    INTEGER NOT NULL DEFAULT 1
)
"""


class QrGeoStore:
    """CRUD/bulk операции над отдельным файлом SQLite."""

    def __init__(self, db_path: str, logger: logging.Logger | None = None) -> None:
        self.db_path = db_path
        self._logger = logger or logging.getLogger(__name__)
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")
        await self._conn.execute(_SCHEMA)
        await self._conn.commit()
        self._logger.info("QrGeoStore initialized at %s", self.db_path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("QrGeoStore is not open")
        return self._conn

    async def load_all_enabled(self) -> dict[str, GeoPoint]:
        conn = self._require_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT qr_value, latitude, longitude, lat_hemi, lon_hemi, label
            FROM qr_geo
            WHERE enabled = 1
            """
        ) as cur:
            rows = await cur.fetchall()
        return {
            str(r["qr_value"]): GeoPoint(
                latitude=float(r["latitude"]),
                longitude=float(r["longitude"]),
                lat_hemi=str(r["lat_hemi"] or "N"),
                lon_hemi=str(r["lon_hemi"] or "E"),
                label=r["label"],
            )
            for r in rows
        }

    async def replace_all(self, entries: list[QrGeoEntry]) -> int:
        conn = self._require_conn()
        await conn.execute("DELETE FROM qr_geo")
        await self._insert_many(conn, entries)
        await conn.commit()
        self._logger.info("qr_geo replace_all count=%d", len(entries))
        return len(entries)

    async def upsert_many(self, entries: list[QrGeoEntry]) -> int:
        conn = self._require_conn()
        await self._insert_many(conn, entries, upsert=True)
        await conn.commit()
        self._logger.info("qr_geo upsert_many count=%d", len(entries))
        return len(entries)

    async def _insert_many(
        self,
        conn: aiosqlite.Connection,
        entries: list[QrGeoEntry],
        *,
        upsert: bool = False,
    ) -> None:
        sql = """
            INSERT INTO qr_geo (
                qr_value, latitude, longitude, lat_hemi, lon_hemi, label, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        if upsert:
            sql = """
                INSERT INTO qr_geo (
                    qr_value, latitude, longitude, lat_hemi, lon_hemi, label, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(qr_value) DO UPDATE SET
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    lat_hemi = excluded.lat_hemi,
                    lon_hemi = excluded.lon_hemi,
                    label = excluded.label,
                    enabled = excluded.enabled
            """
        payload = [
            (
                e.qr_value,
                e.latitude,
                e.longitude,
                e.lat_hemi,
                e.lon_hemi,
                e.label,
                1 if e.enabled else 0,
            )
            for e in entries
        ]
        await conn.executemany(sql, payload)
