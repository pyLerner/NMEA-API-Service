# -*- coding: utf-8 -*-
# =============================================================================
# Перечисления слоя навигационного fusion (UTF-8)
# =============================================================================
"""Строковые enum для PublishMode, качества навигации и источника точки."""

from __future__ import annotations

from enum import Enum


class PublishMode(str, Enum):
    """
    Политика публикации координат в кэш и API.

    MEASUREMENT — только при accept RMC/ECEF (рекомендуется для RMC-only).
    TIMER — predict + publish на частоте OutputRateHz.
    HYBRID — measurement при GOOD; timer в паузах RMC.
    """

    MEASUREMENT = "measurement"
    TIMER = "timer"
    HYBRID = "hybrid"


class NavQuality(str, Enum):
    """
    Режим достоверности навигации (поле API: nav-quality).

    GOOD — позиция от принятого GNRMC.
    KF_ECEF — пауза RMC, обновление из ECEFPOSVEL.
    COAST — только predict / отвергнутое измерение.
    DEGRADED — долго без RMC или серия reject.
    LOST — нет принятых измерений дольше TLostSec; публикация прекращается.
    """

    GOOD = "GOOD"
    KF_ECEF = "KF_ECEF"
    COAST = "COAST"
    DEGRADED = "DEGRADED"
    LOST = "LOST"


class NavSource(str, Enum):
    """
    Составной source последнего измерения (семейство nmea).

    Значения совпадают с API: nmea/rmc, nmea/ecef, nmea/fusion.
    """

    NMEA = "nmea/rmc"
    ECEF = "nmea/ecef"
    FUSION = "nmea/fusion"
