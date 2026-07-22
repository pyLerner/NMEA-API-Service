# -*- coding: utf-8 -*-
"""Заглушки внешних провайдеров (без публикации координат)."""

from __future__ import annotations

import asyncio
import logging

from sources.hub import PositionHub


class _StubAdapterBase:
    """Общая логика stub: warn при старте, ждать stop, не публиковать."""

    name: str
    _not_implemented_msg: str

    def __init__(
        self,
        hub: PositionHub,
        logger: logging.Logger,
        **_params: object,
    ) -> None:
        self._hub = hub
        self._logger = logger

    async def run(self, stop: asyncio.Event) -> None:
        self._logger.warning(
            "Provider %s enabled but not implemented: %s",
            self.name,
            self._not_implemented_msg,
        )
        await stop.wait()


class ImuStubAdapter(_StubAdapterBase):
    """Заглушка расчёта координат по акселерометру / IMU."""

    name = "imu"
    _not_implemented_msg = "accelerometer / IMU dead-reckoning not implemented"


class TriangulationHttpStubAdapter(_StubAdapterBase):
    """
    Заглушка HTTP-клиента триангуляции оператора.

    Параметры Url / IntervalMs / TimeoutMs читаются из конфига, но запросы
    не выполняются.
    """

    name = "triangulation"

    def __init__(
        self,
        hub: PositionHub,
        logger: logging.Logger,
        *,
        url: str = "",
        interval_ms: int = 1000,
        timeout_ms: int = 500,
        **_params: object,
    ) -> None:
        super().__init__(hub, logger)
        self._url = url
        self._interval_ms = interval_ms
        self._timeout_ms = timeout_ms
        self._not_implemented_msg = (
            f"operator triangulation HTTP client "
            f"(url={url!r}, interval_ms={interval_ms}, timeout_ms={timeout_ms})"
        )
