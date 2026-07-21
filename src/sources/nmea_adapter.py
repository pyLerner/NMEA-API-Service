# -*- coding: utf-8 -*-
"""NMEA serial/file/stdin адаптер: reader + fusion tick → PositionHub."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from models.data_models import AppConfig
from navigation.fusion import NavFusion
from runner_task import fusion_tick_task, nmea_reader_task
from sources.hub import PositionHub


class NmeaSerialAdapter:
    """In-process адаптер serial-nmea / file / stdin через NavFusion."""

    name = "nmea"

    def __init__(
        self,
        cfg: AppConfig,
        hub: PositionHub,
        logger: logging.Logger,
        nmea_row_logger: Optional[logging.Logger],
        fusion: Optional[NavFusion] = None,
    ) -> None:
        self._cfg = cfg
        self._hub = hub
        self._logger = logger
        self._nmea_row_logger = nmea_row_logger
        self._fusion = fusion or NavFusion(
            cfg.navigation.profile,
            publish_mode=cfg.navigation.publish_mode,
            logger=logger,
        )

    async def run(self, stop: asyncio.Event) -> None:
        reader_t = asyncio.create_task(
            nmea_reader_task(
                self._cfg,
                self._hub,
                self._logger,
                self._nmea_row_logger,
                self._fusion,
            ),
            name="nmea_reader",
        )
        tick_t = asyncio.create_task(
            fusion_tick_task(self._cfg, self._fusion, self._hub, self._logger),
            name="fusion_tick",
        )
        stopper = asyncio.create_task(stop.wait(), name="nmea_stop_wait")
        try:
            done, pending = await asyncio.wait(
                {reader_t, tick_t, stopper},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for t in done:
                if t is stopper:
                    continue
                exc = t.exception() if not t.cancelled() else None
                if exc is not None:
                    raise exc
        finally:
            for t in (reader_t, tick_t, stopper):
                if not t.done():
                    t.cancel()
            await asyncio.gather(reader_t, tick_t, stopper, return_exceptions=True)
