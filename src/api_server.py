# -*- coding: utf-8 -*-
# =============================================================================
# API server (FastAPI), UTF-8
# =============================================================================
"""HTTP API для выдачи координат из RecordsCache и SQLite."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

import aiosqlite
from api.qr_geo_routes import router as qr_geo_router
from api.record_format import format_record_for_api
from db.cache import RecordsCache, _parse_record_time
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from models.data_models import AppConfig
from sources.hub import PositionHub, matches_provider
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from qr_geo.lookup import QrGeoLookup


def _json_keys_to_kebab(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k.replace("_", "-"): _json_keys_to_kebab(v) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_json_keys_to_kebab(i) for i in obj]
    return obj


def _is_public_api_path(path: str) -> bool:
    if path == "/api/ping":
        return True
    return path.startswith("/api/navigator/v1/") or path.startswith(
        "/api/navigator/v2/"
    )


def _parse_query_time(value: Optional[str], field_name: str) -> Optional[datetime]:
    if value is None or value == "":
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name}: expected ISO8601 UTC timestamp",
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def create_app(
    cfg: AppConfig,
    cache: RecordsCache,
    logger: logging.Logger,
    hub: Optional[PositionHub] = None,
    qr_geo_lookup: Optional["QrGeoLookup"] = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application with bearer token auth
    for legacy paths and /api/qr-geo/*; navigator v1/v2 and GET /api/ping are public.
    """
    app = FastAPI(title="GNRMC API", version="2.0")
    if hub is None:
        hub = PositionHub(cache, logger)
    app.state.qr_geo_lookup = qr_geo_lookup

    class AuthMiddleware(BaseHTTPMiddleware):
        """
        Bearer token authorization for legacy and /api/qr-geo/*.
        Public: GET /api/ping and /api/navigator/v1|v2/*
        """

        async def dispatch(self, request: Request, call_next):
            if _is_public_api_path(request.url.path):
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
                logger.warning("Unauthorized access with invalid Bearer token")
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

            return await call_next(request)

    app.add_middleware(AuthMiddleware)

    async def _last_coords_body(
        provider: Optional[str] = None,
    ) -> dict[str, Any]:
        if provider:
            last = await cache.last_matching(provider)
            if last is None:
                return {"result": False, "error": "no data"}
            return {"result": True, "record": last.to_dict()}
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
                        satellites_count,
                        source,
                        quality
                FROM gnrmc
                ORDER BY key_id DESC
                LIMIT ? OFFSET ?
                """,
                (need, len(out)),
            )
            rows = await cur.fetchall()
            db_records = [format_record_for_api(dict(r)) for r in rows]

        data = out + db_records
        return {"result": True, "count": len(data), "data": data}

    async def _all_coords_v2_body(
        provider: Optional[str],
        from_dt: Optional[datetime],
        to_dt: Optional[datetime],
        limit: int = 1000,
    ) -> dict[str, Any]:
        cached = await cache.filter_records(
            provider=provider,
            from_dt=from_dt,
            to_dt=to_dt,
            limit=limit,
        )
        out = [r.to_dict() for r in cached]
        if len(out) >= limit:
            return {"result": True, "count": len(out), "data": out}

        need = limit - len(out)
        clauses: list[str] = []
        params: list[Any] = []
        if provider:
            clauses.append("(source = ? OR source LIKE ?)")
            params.extend([provider, f"{provider}/%"])
        if from_dt is not None:
            clauses.append("datetime >= ?")
            params.append(from_dt.isoformat())
        if to_dt is not None:
            clauses.append("datetime <= ?")
            params.append(to_dt.isoformat())

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        # Skip rows already covered by in-memory cache (by time+source fingerprint).
        cached_keys = {
            (r.get("time"), r.get("source"), r.get("latitude"), r.get("longitude"))
            for r in out
        }

        async with aiosqlite.connect(cfg.database.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                f"""
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
                        satellites_count,
                        source,
                        quality
                FROM gnrmc
                {where}
                ORDER BY datetime DESC, key_id DESC
                LIMIT ?
                """,
                (*params, need + len(out)),
            )
            rows = await cur.fetchall()

        for row in rows:
            formatted = format_record_for_api(dict(row))
            key = (
                formatted.get("time"),
                formatted.get("source"),
                formatted.get("latitude"),
                formatted.get("longitude"),
            )
            if key in cached_keys:
                continue
            # Re-check time bounds with parsed times (string compare is usually ok for ISO).
            if from_dt is not None or to_dt is not None:
                rt = _parse_record_time(formatted.get("time"))
                if rt is None:
                    continue
                if from_dt is not None and rt < from_dt:
                    continue
                if to_dt is not None and rt > to_dt:
                    continue
            if not matches_provider(formatted.get("source"), provider):
                continue
            out.append(formatted)
            if len(out) >= limit:
                break

        return {"result": True, "count": len(out), "data": out}

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
    async def last_coords_v1() -> JSONResponse:
        body = await _last_coords_body()
        if body.get("result"):
            logger.info("Returned last cached record (v1)")
        return JSONResponse(content=_json_keys_to_kebab(body))

    @app.get("/AllCoords")
    async def all_coords(limit: int = Query(10, gt=0, le=1000)) -> JSONResponse:
        body = await _all_coords_body(limit)
        return JSONResponse(content=body)

    @app.get("/api/navigator/v1/all-coords")
    async def all_coords_v1(limit: int = Query(10, gt=0, le=1000)) -> JSONResponse:
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
    async def delete_record_v1(record_id: int) -> JSONResponse:
        try:
            body = await _delete_record_body(record_id)
            return JSONResponse(content=_json_keys_to_kebab(body))
        except Exception as e:
            logger.exception("Delete error: %s", e)
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.get("/api/navigator/v2/all-coords")
    async def all_coords_v2(
        provider: Optional[str] = Query(None),
        from_: Optional[str] = Query(None, alias="from"),
        to: Optional[str] = Query(None),
    ) -> JSONResponse:
        from_dt = _parse_query_time(from_, "from")
        to_dt = _parse_query_time(to, "to")
        if from_dt is not None and to_dt is not None and from_dt > to_dt:
            raise HTTPException(
                status_code=400, detail="'from' must be <= 'to'"
            )
        body = await _all_coords_v2_body(provider, from_dt, to_dt, limit=1000)
        return JSONResponse(content=_json_keys_to_kebab(body))

    async def _sse_last_coords_stream(
        request: Request,
        provider: Optional[str],
    ) -> AsyncIterator[str]:
        queue = await hub.subscribe(provider)
        keepalive = cfg.api.sse_keepalive_sec
        try:
            initial = await _last_coords_body(provider)
            yield f"data: {json.dumps(_json_keys_to_kebab(initial), ensure_ascii=False)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    rec = await asyncio.wait_for(queue.get(), timeout=keepalive)
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                if rec is None:
                    break
                body = {"result": True, "record": rec.to_dict()}
                yield f"data: {json.dumps(_json_keys_to_kebab(body), ensure_ascii=False)}\n\n"
        finally:
            await hub.unsubscribe(queue)

    @app.get("/api/navigator/v2/last-coords")
    async def last_coords_v2_sse(
        request: Request,
        provider: Optional[str] = Query(None),
    ) -> StreamingResponse:
        return StreamingResponse(
            _sse_last_coords_stream(request, provider),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    app.include_router(qr_geo_router)
    return app
