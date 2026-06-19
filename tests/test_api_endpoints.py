# =============================================================================
# HTTP API: legacy (Bearer) + v2 (/api/ping, /api/navigator/v1/*)
# =============================================================================
from __future__ import annotations

import os
import sys

# Allow running this file directly (e.g. `uv run test_api_endpoints.py` from tests/);
# pytest sets pythonpath via pyproject.toml, but a plain Python run does not.
_proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_src_dir = os.path.join(_proj_root, "src")
if os.path.isdir(_src_dir) and _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import asyncio
import re
from typing import Any

import aiosqlite
from db.cache import Record
from starlette.testclient import TestClient


def _sample_record(**overrides: Any) -> Record:
    base = dict(
        key_id=42,
        datetime="2026-04-10T10:15:00+00:00",
        is_valid="A",
        latitude=46.05123,
        latitude_hemi="N",
        longitude=14.50678,
        longitude_hemi="E",
        speed=0.8,
        direction=176.5,
        mode="A",
        satellites_count=9,
        source="nmea",
    )
    base.update(overrides)
    return Record(**base)


async def _cache_add(cache, record: Record) -> None:
    await cache.add(record)


async def _insert_db_row(db_path: str) -> int:
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            """
            INSERT INTO gnrmc (
                datetime, is_valid, latitude, latitude_hemi, longitude, longitude_hemi,
                speed, direction, mode, satellites_count, delivered, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                "2026-04-09T12:00:00+00:00",
                "A",
                1.0,
                "N",
                2.0,
                "E",
                0.5,
                90.0,
                "A",
                4,
                "nmea",
            ),
        )
        await conn.commit()
        return int(cur.lastrowid)


# --- GET /api/ping ---


def test_get_api_ping_ok(client: TestClient) -> None:
    r = client.get("/api/ping")
    assert r.status_code == 200
    data = r.json()
    assert data["running"] == "OK"
    assert "timestamp-utc" in data
    assert re.search(r"\+\d{2}:\d{2}$", data["timestamp-utc"])


# --- v2: GET /api/navigator/v1/last-coords ---


def test_v2_last_coords_empty_cache(client: TestClient) -> None:
    r = client.get("/api/navigator/v1/last-coords")
    assert r.status_code == 200
    assert r.json() == {"result": False, "error": "no data"}


def test_v2_last_coords_with_record(client: TestClient, cache) -> None:
    asyncio.run(_cache_add(cache, _sample_record(key_id=7)))
    r = client.get("/api/navigator/v1/last-coords")
    assert r.status_code == 200
    body = r.json()
    assert body["result"] is True
    rec = body["record"]
    assert rec["record-id"] == 7
    assert rec["lat-hemisphere"] == "N"
    assert rec["lon-hemisphere"] == "E"
    assert rec["satellites-count"] == 9
    assert rec["source"] == "nmea"


# --- v2: GET /api/navigator/v1/all-coords ---


def test_v2_all_coords_from_cache(client: TestClient, cache) -> None:
    asyncio.run(_cache_add(cache, _sample_record(key_id=1)))
    asyncio.run(_cache_add(cache, _sample_record(key_id=2, latitude=47.0)))
    r = client.get("/api/navigator/v1/all-coords", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["result"] is True
    assert body["count"] == 2
    assert len(body["data"]) == 2
    assert body["data"][0]["record-id"] == 2
    assert body["data"][1]["record-id"] == 1


def test_v2_all_coords_from_db_when_cache_short(
    client: TestClient, app_config, cache
) -> None:
    kid = asyncio.run(_insert_db_row(app_config.database.db_path))
    r = client.get("/api/navigator/v1/all-coords", params={"limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["result"] is True
    assert body["count"] >= 1
    ids = {row["record-id"] for row in body["data"]}
    assert kid in ids
    assert body["data"][0]["source"] == "nmea"


def test_v2_all_coords_limit_validation(client: TestClient) -> None:
    r = client.get("/api/navigator/v1/all-coords", params={"limit": 0})
    assert r.status_code == 422


def test_v2_all_coords_limit_too_large(client: TestClient) -> None:
    r = client.get("/api/navigator/v1/all-coords", params={"limit": 2000})
    assert r.status_code == 422


# --- v2: DELETE /api/navigator/v1/delete-record/{record_id} ---


def test_v2_delete_record_not_found(client: TestClient) -> None:
    r = client.delete("/api/navigator/v1/delete-record/999999")
    assert r.status_code == 200
    body = r.json()
    assert body["result"] is False
    assert "not found" in body["detail"]


def test_v2_delete_record_success(client: TestClient, app_config) -> None:
    kid = asyncio.run(_insert_db_row(app_config.database.db_path))
    r = client.delete(f"/api/navigator/v1/delete-record/{kid}")
    assert r.status_code == 200
    body = r.json()
    assert body["result"] is True
    assert str(kid) in body["detail"]


# --- legacy: Bearer required ---


def test_legacy_last_coords_401_without_auth(client: TestClient) -> None:
    r = client.get("/LastCoords")
    assert r.status_code == 401


def test_legacy_all_coords_401_without_auth(client: TestClient) -> None:
    r = client.get("/AllCoords")
    assert r.status_code == 401


def test_legacy_delete_401_without_auth(client: TestClient) -> None:
    r = client.delete("/DeleteRecord/1")
    assert r.status_code == 401


def test_legacy_401_invalid_token(client: TestClient) -> None:
    r = client.get(
        "/LastCoords",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert r.status_code == 401


def test_legacy_last_coords_empty_with_auth(client: TestClient, auth_headers) -> None:
    r = client.get("/LastCoords", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"result": False, "error": "no data"}


def test_legacy_last_coords_with_data(client: TestClient, cache, auth_headers) -> None:
    asyncio.run(_cache_add(cache, _sample_record(key_id=99)))
    r = client.get("/LastCoords", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["result"] is True
    assert body["record"]["record_id"] == 99
    assert body["record"]["source"] == "nmea"


def test_legacy_all_coords_with_auth(client: TestClient, app_config, auth_headers) -> None:
    asyncio.run(_insert_db_row(app_config.database.db_path))
    r = client.get("/AllCoords", params={"limit": 3}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["result"] is True
    assert body["count"] >= 1
    assert "record_id" in body["data"][0]


def test_legacy_delete_not_found(client: TestClient, auth_headers) -> None:
    r = client.delete("/DeleteRecord/888888", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["result"] is False


def test_legacy_delete_success(client: TestClient, app_config, auth_headers) -> None:
    kid = asyncio.run(_insert_db_row(app_config.database.db_path))
    r = client.delete(f"/DeleteRecord/{kid}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["result"] is True


if __name__ == "__main__":
    # Subprocess avoids PytestAssertRewriteWarning: running pytest.main() in-process
    # after this module imported Starlette/anyio loads anyio before pytest can rewrite it.
    import subprocess

    raise SystemExit(
        subprocess.call([sys.executable, "-m", "pytest", __file__, *sys.argv[1:]])
    )
