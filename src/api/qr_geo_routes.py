# -*- coding: utf-8 -*-
"""HTTP API управления справочником qr_geo."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from qr_geo.lookup import QrGeoLookup
from qr_geo.parse import ParseError, parse_catalog, validation_response
from qr_geo.validate import validate_all

router = APIRouter(prefix="/api/qr-geo/v1", tags=["qr-geo"])


async def _read_upload(request: Request) -> tuple[bytes, str | None, str | None]:
    ctype = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in ctype:
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise ParseError("multipart field 'file' is required", status_code=400)
        if not isinstance(upload, UploadFile):
            raise ParseError("multipart field 'file' must be a file", status_code=400)
        data = await upload.read()
        return data, upload.filename, upload.content_type
    if "application/json" in ctype or ctype.endswith("+json"):
        return await request.body(), "catalog.json", ctype
    # raw body with filename hint unsupported — require explicit type
    raise ParseError(
        "Content-Type must be multipart/form-data (file=) or application/json",
        status_code=415,
    )


async def _ingest(request: Request, *, mode: str) -> JSONResponse:
    lookup: QrGeoLookup | None = getattr(request.app.state, "qr_geo_lookup", None)
    if lookup is None:
        return JSONResponse(
            status_code=503,
            content={"result": False, "error": "qr-geo catalog not initialized"},
        )

    try:
        data, filename, content_type = await _read_upload(request)
        rows, row_offset, fmt = parse_catalog(
            data, filename=filename, content_type=content_type
        )
    except ParseError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"result": False, "error": exc.message},
        )

    if mode == "replace" and len(rows) == 0:
        return JSONResponse(
            status_code=422,
            content={
                "result": False,
                "error": "validation failed",
                "errors": [
                    {
                        "row": 0,
                        "field": "file",
                        "message": "empty catalog not allowed for replace",
                    }
                ],
            },
        )

    entries, errors = validate_all(rows, row_offset=row_offset)
    if errors:
        return JSONResponse(status_code=422, content=validation_response(errors))

    if mode == "replace":
        count = await lookup.replace_catalog(entries)
    else:
        count = await lookup.append_catalog(entries)

    return JSONResponse(
        content={"result": True, "count": count, "format": fmt, "mode": mode}
    )


@router.post("/catalog:replace")
async def catalog_replace(request: Request) -> JSONResponse:
    """Полная перезапись справочника из CSV/JSON."""
    return await _ingest(request, mode="replace")


@router.post("/catalog:append")
async def catalog_append(request: Request) -> JSONResponse:
    """Upsert записей из CSV/JSON к существующему справочнику."""
    return await _ingest(request, mode="append")
