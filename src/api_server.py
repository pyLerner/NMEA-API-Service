# =============================================================================
# API server (FastAPI)
# =============================================================================
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from db.cache import RecordsCache
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from models.data_models import AppConfig
from starlette.middleware.base import BaseHTTPMiddleware


def _json_keys_to_kebab(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k.replace("_", "-"): _json_keys_to_kebab(v) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_json_keys_to_kebab(i) for i in obj]
    return obj


def _is_public_v2_path(path: str) -> bool:
    if path == "/api/ping":
        return True
    return path.startswith("/api/navigator/v1/")


def create_app(cfg: AppConfig, cache: RecordsCache, logger: logging.Logger) -> FastAPI:
    """
    Create and configure the FastAPI application with bearer token auth
    for legacy paths; v2 paths under /api/navigator/v1/ and GET /api/ping are public.
    """
    app = FastAPI(title="GNRMC API", version="2.0")

    class AuthMiddleware(BaseHTTPMiddleware):
        """
        Bearer token authorization middleware for legacy endpoints only.
        Public: GET /api/ping and /api/navigator/v1/*
        """

        async def dispatch(self, request: Request, call_next):
            if _is_public_v2_path(request.url.path):
                return await call_next(request)

            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                logger.warning("Access attempt without Bearer token")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authorization header missing or invalid"},
                )

            token = auth_header.removeprefix("Bearer ").strip()
            if token != str(cfg.api.token):
                logger.warning("Unauthorized access with invalid token: %s", token)
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

            return await call_next(request)

    app.add_middleware(AuthMiddleware)

    async def _last_coords_body() -> dict[str, Any]:
        snapshot = await cache.snapshot()
        if not snapshot:
            return {"result": False, "error": "no data"}
        last = snapshot[-1]
        return {"result": True, "record": last.to_dict()}

    async def _all_coords_body(limit: int) -> dict[str, Any]:
        snapshot = await cache.snapshot()
        cached = list(reversed(snapshot))[:limit]
        out = [r.to_dict() for r in cached]

        if len(out) >= limit:
            return {"result": True, "count": len(out), "data": out}

        need = limit - len(out)
        async with aiosqlite.connect(cfg.database.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                """
                SELECT  key_id AS record_id,
                        datetime AS time,
                        is_valid,
                        latitude,
                        latitude_hemi AS lat_hemisphere,
                        longitude,
                        longitude_hemi AS lon_hemisphere,
                        speed,
                        direction,
                        mode,
                        satellites_count
                FROM gnrmc
                ORDER BY key_id DESC
                LIMIT ? OFFSET ?
                """,
                (need, len(out)),
            )
            rows = await cur.fetchall()
            db_records = [dict(r) for r in rows]

        data = out + db_records
        return {"result": True, "count": len(data), "data": data}

    async def _delete_record_body(record_id: int) -> dict[str, Any]:
        async with aiosqlite.connect(cfg.database.db_path) as conn:
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA synchronous=NORMAL;")
            cur = await conn.execute(
                "DELETE FROM gnrmc WHERE key_id = ?", (record_id,)
            )
            await conn.commit()
            if cur.rowcount and cur.rowcount > 0:
                logger.info("Deleted record %d", record_id)
                return {
                    "result": True,
                    "detail": f"record {record_id} deleted",
                }
            logger.info("Record %d not found", record_id)
            return {
                "result": False,
                "detail": f"record {record_id} not found",
            }

    @app.get("/api/ping")
    async def ping() -> JSONResponse:
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        return JSONResponse(
            content={"running": "OK", "timestamp-utc": ts},
        )

    @app.get("/LastCoords")
    async def last_coords() -> JSONResponse:
        """
        Return the latest record from cache.
        If cache is empty, return result=False with no data.
        """
        body = await _last_coords_body()
        if body.get("result"):
            logger.info("Returned last cached record")
        return JSONResponse(content=body)

    @app.get("/api/navigator/v1/last-coords")
    async def last_coords_v2() -> JSONResponse:
        body = await _last_coords_body()
        if body.get("result"):
            logger.info("Returned last cached record (v2)")
        return JSONResponse(content=_json_keys_to_kebab(body))

    @app.get("/AllCoords")
    async def all_coords(limit: int = Query(10, gt=0, le=1000)) -> JSONResponse:
        body = await _all_coords_body(limit)
        return JSONResponse(content=body)

    @app.get("/api/navigator/v1/all-coords")
    async def all_coords_v2(limit: int = Query(10, gt=0, le=1000)) -> JSONResponse:
        body = await _all_coords_body(limit)
        return JSONResponse(content=_json_keys_to_kebab(body))

    @app.delete("/DeleteRecord/{record_id}")
    async def delete_record(record_id: int) -> JSONResponse:
        """
        Delete a record by key_id from DB (note: cache is not affected here).
        """
        try:
            body = await _delete_record_body(record_id)
            return JSONResponse(content=body)
        except Exception as e:
            logger.exception("Delete error: %s", e)
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.delete("/api/navigator/v1/delete-record/{record_id}")
    async def delete_record_v2(record_id: int) -> JSONResponse:
        try:
            body = await _delete_record_body(record_id)
            return JSONResponse(content=_json_keys_to_kebab(body))
        except Exception as e:
            logger.exception("Delete error: %s", e)
            raise HTTPException(status_code=500, detail=str(e)) from e

    return app
