# =============================================================================
# API server (FastAPI)
# =============================================================================
import logging

import aiosqlite
from db.cache import RecordsCache
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from models.data_models import AppConfig
from starlette.middleware.base import BaseHTTPMiddleware


def create_app(cfg: AppConfig, cache: RecordsCache, logger: logging.Logger) -> FastAPI:
    """
    Create and configure the FastAPI application with bearer token auth
    and endpoints using the in-memory cache for /AllCoords.
    """
    app = FastAPI(title="GNRMC API", version="2.0")

    class AuthMiddleware(BaseHTTPMiddleware):
        """
        Bearer token authorization middleware.
        Requires header: Authorization: Bearer <token>
        """

        async def dispatch(self, request: Request, call_next):
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

    @app.get("/LastCoords")
    async def last_coords() -> JSONResponse:
        """
        Return the latest record from cache.
        If cache is empty, return result=False with no data.
        """
        snapshot = await cache.snapshot()
        if not snapshot:
            return JSONResponse(content={"result": False, "error": "no data"})
        last = snapshot[-1]
        response = {"result": True, "record": last.to_dict()}
        logger.info("Returned last cached record")
        return JSONResponse(content=response)

    @app.get("/AllCoords")
    async def all_coords(limit: int = Query(10, gt=0, le=1000)) -> JSONResponse:
        # Берём данные из кэша
        snapshot = await cache.snapshot()
        cached = list(reversed(snapshot))[:limit]
        out = [r.to_dict() for r in cached]

        if len(out) >= limit:
            return JSONResponse(
                content={"result": True, "count": len(out), "data": out}
            )

        # Если не хватает — добираем из БД
        need = limit - len(out)
        async with aiosqlite.connect(cfg.database.db_path) as conn:
            conn.row_factory = aiosqlite.Row  #  для dict()
            cur = await conn.execute(
                """
                SELECT  key_id AS record_id,  -- совместимость
                        datetime AS time,      -- совместимость
                        is_valid,
                        latitude,
                        latitude_hemi AS lat_hemisphere,  -- совместимость
                        longitude,
                        longitude_hemi AS lon_hemisphere,  -- совместимость
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
        return JSONResponse(content={"result": True, "count": len(data), "data": data})

    @app.delete("/DeleteRecord/{record_id}")
    async def delete_record(record_id: int) -> JSONResponse:
        """
        Delete a record by key_id from DB (note: cache is not affected here).
        """
        # DB deletion remains possible even though /AllCoords uses cache.
        # We open a short-lived connection to execute the delete.
        try:
            async with aiosqlite.connect(cfg.database.db_path) as conn:
                await conn.execute("PRAGMA journal_mode=WAL;")
                await conn.execute("PRAGMA synchronous=NORMAL;")
                cur = await conn.execute(
                    "DELETE FROM gnrmc WHERE key_id = ?", (record_id,)
                )
                await conn.commit()
                if cur.rowcount and cur.rowcount > 0:
                    logger.info("Deleted record %d", record_id)
                    return JSONResponse(
                        content={
                            "result": True,
                            "detail": f"record {record_id} deleted",
                        }
                    )
                else:
                    logger.info("Record %d not found", record_id)
                    return JSONResponse(
                        content={
                            "result": False,
                            "detail": f"record {record_id} not found",
                        }
                    )
        except Exception as e:
            logger.exception("Delete error: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    return app
