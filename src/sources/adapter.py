# -*- coding: utf-8 -*-
"""Protocol адаптера источника навигационных данных."""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable


@runtime_checkable
class NavSourceAdapter(Protocol):
    """Адаптер провайдера: пишет в Hub, пока не установлен stop."""

    name: str

    async def run(self, stop: asyncio.Event) -> None:
        """Крутить ingestion до stop.set() или CancelledError."""
        ...
