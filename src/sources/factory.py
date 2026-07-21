# -*- coding: utf-8 -*-
"""Фабрика адаптеров по SourceProviderConfig."""

from __future__ import annotations

import logging
from typing import Optional

from models.data_models import AppConfig, SourceProviderConfig
from sources.adapter import NavSourceAdapter
from sources.hub import PositionHub
from sources.nmea_adapter import NmeaSerialAdapter
from sources.stubs import ImuStubAdapter, QrGeoStubAdapter, TriangulationHttpStubAdapter


def build_adapters(
    cfg: AppConfig,
    hub: PositionHub,
    logger: logging.Logger,
    nmea_row_logger: Optional[logging.Logger] = None,
) -> list[NavSourceAdapter]:
    """Создать адаптеры для всех Enabled провайдеров."""
    adapters: list[NavSourceAdapter] = []
    for provider in cfg.sources:
        if not provider.enabled:
            continue
        adapter = _build_one(provider, cfg, hub, logger, nmea_row_logger)
        if adapter is not None:
            adapters.append(adapter)
            logger.info(
                "Source provider enabled: name=%s type=%s",
                provider.name,
                provider.type,
            )
        else:
            logger.warning(
                "Unknown source type %r for provider %s — skipped",
                provider.type,
                provider.name,
            )
    if not adapters:
        logger.warning("No enabled navigation source providers")
    return adapters


def _build_one(
    provider: SourceProviderConfig,
    cfg: AppConfig,
    hub: PositionHub,
    logger: logging.Logger,
    nmea_row_logger: Optional[logging.Logger],
) -> NavSourceAdapter | None:
    ptype = provider.type.strip().lower()
    params = provider.params

    if ptype == "serial-nmea":
        return NmeaSerialAdapter(cfg, hub, logger, nmea_row_logger)

    if ptype == "qr-geo":
        return QrGeoStubAdapter(hub, logger, **params)

    if ptype == "imu":
        return ImuStubAdapter(hub, logger, **params)

    if ptype == "triangulation-http":
        return TriangulationHttpStubAdapter(
            hub,
            logger,
            url=str(params.get("Url", params.get("url", ""))),
            interval_ms=int(params.get("IntervalMs", params.get("interval_ms", 1000))),
            timeout_ms=int(params.get("TimeoutMs", params.get("timeout_ms", 500))),
        )

    return None
