# -*- coding: utf-8 -*-
"""Адаптер qr-geo: SSE QR-reader → lookup → PositionHub."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from qr_geo.config import (
    DEFAULT_CONNECT_TIMEOUT_MS,
    DEFAULT_DEDUP_WINDOW_SEC,
    DEFAULT_EVENT_TIME_SOURCE,
    DEFAULT_EVENTS_URL,
    DEFAULT_RECONNECT_MAX_MS,
    DEFAULT_RECONNECT_MIN_MS,
    EVENT_TIME_SOURCE_LOAD_IMAGE,
    normalize_event_time_source,
    qr_geo_param,
)
from qr_geo.lookup import QrGeoLookup
from sources.events import NavPositionEvent
from sources.hub import PositionHub
from sources.source_ids import PROVIDER_QR, SOURCE_QR


class QrGeoAdapter:
    """Подписка на SSE qr-detected и публикация координат source=qr."""

    name = "qr-geo"

    def __init__(
        self,
        hub: PositionHub,
        lookup: QrGeoLookup,
        logger: logging.Logger,
        *,
        events_url: str = DEFAULT_EVENTS_URL,
        connect_timeout_ms: int = DEFAULT_CONNECT_TIMEOUT_MS,
        reconnect_min_ms: int = DEFAULT_RECONNECT_MIN_MS,
        reconnect_max_ms: int = DEFAULT_RECONNECT_MAX_MS,
        dedup_window_sec: float = DEFAULT_DEDUP_WINDOW_SEC,
        event_time_source: str = DEFAULT_EVENT_TIME_SOURCE,
        **_params: object,
    ) -> None:
        self._hub = hub
        self._lookup = lookup
        self._logger = logger
        self._events_url = events_url
        self._connect_timeout = connect_timeout_ms / 1000.0
        self._reconnect_min = max(0.05, reconnect_min_ms / 1000.0)
        self._reconnect_max = max(self._reconnect_min, reconnect_max_ms / 1000.0)
        self._dedup_window = max(0.0, float(dedup_window_sec))
        self._event_time_source = normalize_event_time_source(event_time_source)
        self._last_emit: dict[str, float] = {}

    @classmethod
    def from_params(
        cls,
        hub: PositionHub,
        lookup: QrGeoLookup,
        logger: logging.Logger,
        params: dict[str, Any],
    ) -> QrGeoAdapter:
        return cls(
            hub,
            lookup,
            logger,
            events_url=str(
                qr_geo_param(params, "EventsUrl", "events_url", default=DEFAULT_EVENTS_URL)
            ),
            connect_timeout_ms=int(
                qr_geo_param(
                    params,
                    "ConnectTimeoutMs",
                    "connect_timeout_ms",
                    default=DEFAULT_CONNECT_TIMEOUT_MS,
                )
            ),
            reconnect_min_ms=int(
                qr_geo_param(
                    params,
                    "ReconnectMinMs",
                    "reconnect_min_ms",
                    default=DEFAULT_RECONNECT_MIN_MS,
                )
            ),
            reconnect_max_ms=int(
                qr_geo_param(
                    params,
                    "ReconnectMaxMs",
                    "reconnect_max_ms",
                    default=DEFAULT_RECONNECT_MAX_MS,
                )
            ),
            dedup_window_sec=float(
                qr_geo_param(
                    params,
                    "DedupWindowSec",
                    "dedup_window_sec",
                    default=DEFAULT_DEDUP_WINDOW_SEC,
                )
            ),
            event_time_source=str(
                qr_geo_param(
                    params,
                    "EventTimeSource",
                    "event_time_source",
                    default=DEFAULT_EVENT_TIME_SOURCE,
                )
            ),
        )

    def _pick_event_time(self, payload: dict[str, Any]) -> str | None:
        load_t = payload.get("load-image-time") or payload.get("load_image_time")
        event_t = payload.get("timestamp")
        if self._event_time_source == EVENT_TIME_SOURCE_LOAD_IMAGE:
            chosen = load_t or event_t
        else:
            # event — время публикации/обработки SSE
            chosen = event_t or load_t
        return str(chosen) if chosen else None

    def _dedup_ok(self, qr_value: str) -> bool:
        if self._dedup_window <= 0:
            return True
        now = time.monotonic()
        last = self._last_emit.get(qr_value)
        if last is not None and (now - last) < self._dedup_window:
            return False
        self._last_emit[qr_value] = now
        # prune occasionally
        if len(self._last_emit) > 10_000:
            cutoff = now - self._dedup_window
            self._last_emit = {k: v for k, v in self._last_emit.items() if v >= cutoff}
        return True

    async def _handle_payload(self, payload: dict[str, Any]) -> None:
        result = payload.get("result")
        if not result or not isinstance(result, str):
            return
        point = self._lookup.get(result)
        if point is None:
            self._logger.debug("qr lookup miss result=%s", result)
            return
        if not self._dedup_ok(result):
            self._logger.debug("qr dedup skip result=%s", result)
            return

        dt = self._pick_event_time(payload)

        event = NavPositionEvent(
            provider=PROVIDER_QR,
            source=SOURCE_QR,
            datetime_iso=dt,
            latitude=point.latitude,
            latitude_hemi=point.lat_hemi,
            longitude=point.longitude,
            longitude_hemi=point.lon_hemi,
            speed=0.0,
            direction=0.0,
            is_valid="A",
            mode="M",
            satellites_count=0,
            quality="GOOD",
            extras={
                "qr-value": result,
                "image-id": payload.get("image-id") or payload.get("image_id"),
            },
        )
        await self._hub.publish(event)
        self._logger.info(
            "qr published result=%s lat=%s lon=%s",
            result,
            point.latitude,
            point.longitude,
        )

    async def _consume_sse(self, stop: asyncio.Event) -> None:
        timeout = httpx.Timeout(None, connect=self._connect_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", self._events_url) as response:
                response.raise_for_status()
                event_name: str | None = None
                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if stop.is_set():
                        break
                    if line is None:
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                        continue
                    if line == "":
                        if event_name == "qr-detected" and data_lines:
                            raw = "\n".join(data_lines)
                            try:
                                payload = json.loads(raw)
                            except json.JSONDecodeError:
                                self._logger.warning("qr sse invalid json: %s", raw[:200])
                            else:
                                if isinstance(payload, dict):
                                    await self._handle_payload(payload)
                        event_name = None
                        data_lines = []

    async def run(self, stop: asyncio.Event) -> None:
        delay = self._reconnect_min
        self._logger.info(
            "QrGeoAdapter starting events_url=%s lookup_size=%d",
            self._events_url,
            len(self._lookup),
        )
        while not stop.is_set():
            try:
                await self._consume_sse(stop)
                if stop.is_set():
                    break
                self._logger.warning("qr sse stream ended; reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._logger.warning(
                    "qr sse error: %s; reconnect in %.2fs",
                    exc,
                    delay,
                )
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
                break
            except asyncio.TimeoutError:
                pass
            delay = min(self._reconnect_max, delay * 2)
        self._logger.info("QrGeoAdapter stopped")
