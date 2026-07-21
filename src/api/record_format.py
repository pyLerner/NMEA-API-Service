# -*- coding: utf-8 -*-
# =============================================================================
# Нормализация записи для JSON API (UTF-8)
# =============================================================================
"""Округление координат, speed, direction для совместимости с Go-клиентом."""
from __future__ import annotations

from typing import Any


def _int_or_zero(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def _round_coord(value: Any) -> float:
    if value is None:
        return 0.0
    return round(float(value), 7)


def _round1(value: Any) -> float:
    if value is None:
        return 0.0
    return round(float(value), 1)


def format_record_for_api(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize record dict for JSON API (v1 keys, snake_case)."""
    out = dict(record)
    out["record_id"] = _int_or_zero(record.get("record_id"))
    out["latitude"] = _round_coord(record.get("latitude"))
    out["longitude"] = _round_coord(record.get("longitude"))
    out["speed"] = _round1(record.get("speed"))
    out["direction"] = _round1(record.get("direction"))
    out["satellites_count"] = _int_or_zero(record.get("satellites_count"))
    return out
