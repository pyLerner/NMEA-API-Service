# -*- coding: utf-8 -*-
"""Параметры [Sources.qr-geo] из AppConfig."""

from __future__ import annotations

from models.data_models import AppConfig, SourceProviderConfig

DEFAULT_GEO_DB_PATH = "data/qr_geo.db"
DEFAULT_EVENTS_URL = "http://127.0.0.1:7140/api/qr-reader/v1/events"
DEFAULT_DEDUP_WINDOW_SEC = 5.0
DEFAULT_CONNECT_TIMEOUT_MS = 5000
DEFAULT_RECONNECT_MIN_MS = 500
DEFAULT_RECONNECT_MAX_MS = 30_000

# Какое время из SSE qr-detected писать в record.time
EVENT_TIME_SOURCE_LOAD_IMAGE = "load-image"
EVENT_TIME_SOURCE_EVENT = "event"
DEFAULT_EVENT_TIME_SOURCE = EVENT_TIME_SOURCE_EVENT
_VALID_EVENT_TIME_SOURCES = frozenset(
    {EVENT_TIME_SOURCE_LOAD_IMAGE, EVENT_TIME_SOURCE_EVENT}
)


def normalize_event_time_source(value: object) -> str:
    """
    Разобрать EventTimeSource: ``load-image`` | ``event``.

    Raises:
        ValueError: неизвестное значение.
    """
    text = str(value if value is not None else DEFAULT_EVENT_TIME_SOURCE).strip().lower()
    if text in ("load_image", "load-image-time", "image"):
        text = EVENT_TIME_SOURCE_LOAD_IMAGE
    if text in ("publish", "processed", "timestamp"):
        text = EVENT_TIME_SOURCE_EVENT
    if text not in _VALID_EVENT_TIME_SOURCES:
        raise ValueError(
            f"Invalid EventTimeSource: {value!r} "
            f"(expected {EVENT_TIME_SOURCE_LOAD_IMAGE!r} or {EVENT_TIME_SOURCE_EVENT!r})"
        )
    return text


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
