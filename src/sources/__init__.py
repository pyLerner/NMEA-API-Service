# -*- coding: utf-8 -*-
"""Multi-source navigation providers and PositionHub."""

from sources.adapter import NavSourceAdapter
from sources.events import NavPositionEvent
from sources.hub import PositionHub, matches_provider, provider_id_from_source
from sources.source_ids import (
    PROVIDER_IMU,
    PROVIDER_NMEA,
    PROVIDER_QR,
    PROVIDER_TRIANGULATION,
    SOURCE_IMU,
    SOURCE_NMEA_ECEF,
    SOURCE_NMEA_FUSION,
    SOURCE_NMEA_RMC,
    SOURCE_QR,
    SOURCE_TRIANGULATION,
)

__all__ = [
    "NavPositionEvent",
    "NavSourceAdapter",
    "PositionHub",
    "matches_provider",
    "provider_id_from_source",
    "PROVIDER_IMU",
    "PROVIDER_NMEA",
    "PROVIDER_QR",
    "PROVIDER_TRIANGULATION",
    "SOURCE_IMU",
    "SOURCE_NMEA_ECEF",
    "SOURCE_NMEA_FUSION",
    "SOURCE_NMEA_RMC",
    "SOURCE_QR",
    "SOURCE_TRIANGULATION",
]
