# -*- coding: utf-8 -*-
"""Единый контракт навигационного события для PositionHub."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class NavPositionEvent:
    """Нормализованная точка от любого провайдера."""

    provider: str
    source: str
    datetime_iso: Optional[str]
    latitude: Optional[float]
    latitude_hemi: Optional[str]
    longitude: Optional[float]
    longitude_hemi: Optional[str]
    speed: Optional[float] = None
    direction: Optional[float] = None
    is_valid: Optional[str] = None
    mode: Optional[str] = None
    satellites_count: Optional[int] = None
    quality: Optional[str] = None
    extras: dict[str, Any] = field(default_factory=dict)
