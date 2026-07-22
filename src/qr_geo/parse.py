# -*- coding: utf-8 -*-
"""Парсинг CSV/JSON каталога qr_geo."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from qr_geo.validate import MAX_FILE_BYTES, FieldError


class ParseError(Exception):
    """Ошибка разбора файла до валидации полей."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _normalize_header(name: str) -> str:
    return name.strip().lstrip("\ufeff").replace("_", "-").lower()


def parse_csv_bytes(data: bytes) -> tuple[list[dict[str, Any]], int]:
    """
    Разобрать CSV.

    Returns:
        (rows, row_offset) — row_offset=2 значит первая data-строка = 2 в файле.
    """
    if len(data) > MAX_FILE_BYTES:
        raise ParseError(f"file too large: {len(data)} > {MAX_FILE_BYTES}", status_code=413)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError("file must be UTF-8") from exc

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ParseError("CSV missing header row")

    headers = [_normalize_header(h) for h in reader.fieldnames]
    required = {"qr-value", "latitude", "longitude"}
    missing = required - set(headers)
    if missing:
        raise ParseError(f"CSV missing required columns: {sorted(missing)}")

    rows: list[dict[str, Any]] = []
    for raw in reader:
        row = {_normalize_header(k): v for k, v in raw.items() if k is not None}
        rows.append(row)
    return rows, 2  # header is line 1; first data row is 2


def parse_json_bytes(data: bytes) -> tuple[list[dict[str, Any]], int]:
    """Разобрать JSON-массив или ``{\"entries\": [...]}``."""
    if len(data) > MAX_FILE_BYTES:
        raise ParseError(f"file too large: {len(data)} > {MAX_FILE_BYTES}", status_code=413)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError("file must be UTF-8") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON: {exc}") from exc

    if isinstance(payload, dict) and "entries" in payload:
        payload = payload["entries"]
    if not isinstance(payload, list):
        raise ParseError("JSON must be an array or {\"entries\": [...]}")

    rows: list[dict[str, Any]] = []
    for i, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ParseError(f"JSON entry at index {i} is not an object")
        # keep both styles; validator accepts both
        rows.append(item)
    return rows, 0


def detect_format(filename: str | None, content_type: str | None) -> str:
    """Вернуть ``csv`` или ``json``."""
    name = (filename or "").lower()
    ctype = (content_type or "").lower()
    if name.endswith(".csv") or "csv" in ctype:
        return "csv"
    if name.endswith(".json") or "json" in ctype:
        return "json"
    raise ParseError(
        "unsupported format: use .csv or .json (Content-Type or filename)",
        status_code=415,
    )


def parse_catalog(
    data: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
    fmt: str | None = None,
) -> tuple[list[dict[str, Any]], int, str]:
    """
    Разобрать каталог.

    Returns:
        rows, row_offset, format_name
    """
    chosen = fmt or detect_format(filename, content_type)
    if chosen == "csv":
        rows, offset = parse_csv_bytes(data)
        return rows, offset, "csv"
    if chosen == "json":
        rows, offset = parse_json_bytes(data)
        return rows, offset, "json"
    raise ParseError(f"unsupported format: {chosen!r}", status_code=415)


def validation_response(errors: list[FieldError]) -> dict[str, Any]:
    return {
        "result": False,
        "error": "validation failed",
        "errors": [e.to_dict() for e in errors],
    }
