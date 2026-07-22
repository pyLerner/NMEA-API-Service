# -*- coding: utf-8 -*-
"""Параметры [Sources.qr-geo] из AppConfig."""

from __future__ import annotations

from models.data_models import AppConfig, SourceProviderConfig

DEFAULT_GEO_DB_PATH = "data/qr_geo.db"
DEFAULT_EVENTS_URL = "http://127.0.0.1:8000/api/qr-reader/v1/events"
DEFAULT_DEDUP_WINDOW_SEC = 5.0
DEFAULT_CONNECT_TIMEOUT_MS = 5000
DEFAULT_RECONNECT_MIN_MS = 500
DEFAULT_RECONNECT_MAX_MS = 30_000


def find_qr_geo_provider(cfg: AppConfig) -> SourceProviderConfig | None:
    for provider in cfg.sources:
        if provider.name == "qr-geo" or provider.type.strip().lower() == "qr-geo":
            return provider
    return None


def qr_geo_param(params: dict, *keys: str, default: object = None) -> object:
    for key in keys:
        if key in params:
            return params[key]
    return default


def geo_db_path_from_config(cfg: AppConfig) -> str:
    provider = find_qr_geo_provider(cfg)
    if provider is None:
        return DEFAULT_GEO_DB_PATH
    path = qr_geo_param(
        provider.params,
        "GeoDbPath",
        "geo_db_path",
        default=DEFAULT_GEO_DB_PATH,
    )
    return str(path)
