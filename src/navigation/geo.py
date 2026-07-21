# -*- coding: utf-8 -*-
# =============================================================================
# Геодезические функции для локальной ENU fusion (UTF-8)
# =============================================================================
"""Haversine, ENU offset, преобразование полушарий для NavFusion."""
from __future__ import annotations

import math

WGS84_A = 6378137.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def latlon_to_enu(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Approximate ENU offset in meters from anchor (lat0, lon0)."""
    dlat = math.radians(lat - lat0)
    dlon = math.radians(lon - lon0)
    cos_lat0 = math.cos(math.radians(lat0))
    north = dlat * WGS84_A
    east = dlon * WGS84_A * cos_lat0
    return east, north


def enu_to_latlon(east: float, north: float, lat0: float, lon0: float) -> tuple[float, float]:
    cos_lat0 = math.cos(math.radians(lat0))
    dlat = north / WGS84_A
    dlon = east / (WGS84_A * cos_lat0) if abs(cos_lat0) > 1e-9 else 0.0
    return math.degrees(math.radians(lat0) + dlat), math.degrees(math.radians(lon0) + dlon)


def signed_lat_lon(
    latitude: float, lat_hemi: str, longitude: float, lon_hemi: str
) -> tuple[float, float]:
    lat = abs(latitude) if latitude else 0.0
    lon = abs(longitude) if longitude else 0.0
    if lat_hemi == "S":
        lat = -lat
    if lon_hemi == "W":
        lon = -lon
    return lat, lon


def hemi_from_signed(lat: float, lon: float) -> tuple[float, str, float, str]:
    return abs(lat), "N" if lat >= 0 else "S", abs(lon), "E" if lon >= 0 else "W"
