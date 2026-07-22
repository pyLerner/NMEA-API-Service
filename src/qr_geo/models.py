# -*- coding: utf-8 -*-
"""Модели записей справочника qr_geo."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GeoPoint:
    """Координата из справочника для lookup."""

    latitude: float
    longitude: float
    lat_hemi: str = "N"
    lon_hemi: str = "E"
    label: str | None = None


@dataclass(frozen=True)
class QrGeoEntry:
    """Полная запись справочника (для store)."""

    qr_value: str
    latitude: float
    longitude: float
    lat_hemi: str = "N"
    lon_hemi: str = "E"
    label: str | None = None
    enabled: bool = True

    def to_geo_point(self) -> GeoPoint:
        return GeoPoint(
            latitude=self.latitude,
            longitude=self.longitude,
            lat_hemi=self.lat_hemi,
            lon_hemi=self.lon_hemi,
            label=self.label,
        )
