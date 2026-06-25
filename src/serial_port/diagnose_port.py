# -*- coding: utf-8 -*-
# =============================================================================
# Диагностика одного serial-порта (UTF-8)
# =============================================================================
"""
Утилита командной строки: непрерывное чтение NMEA с заданного порта.

Запуск: ``python -m serial_port.diagnose_port`` (из каталога ``src``).
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from serial.serialutil import SerialException

try:
    import serial_asyncio  # type: ignore
except Exception:
    serial_asyncio = None


async def iter_serial_lines(port: str, baud: int) -> AsyncIterator[str]:
    """
    Async-итератор строк с serial-порта (упрощённый, для диагностики).

    Args:
        port: Путь к устройству.
        baud: Скорость порта, бит/с.

    Yields:
        Строки порта после декодирования ASCII.

    Raises:
        RuntimeError: если не установлен ``pyserial-asyncio``.
    """
    if serial_asyncio is None:
        raise RuntimeError(
            "pyserial-asyncio is not installed. Install via 'uv pip install pyserial-asyncio'."
        )

    reader, _ = await serial_asyncio.open_serial_connection(url=port, baudrate=baud)
    try:
        while True:
            line = await reader.readline()
            if not line:
                await asyncio.sleep(0.05)
                continue
            yield line.decode("ascii", errors="ignore")
    except SerialException as e:
        print(e)
    finally:
        pass


if __name__ == "__main__":

    async def main() -> None:
        """Читать и печатать строки ``$G*`` с ``/dev/ttyS3`` @ 9600."""
        port = "/dev/ttyS3"
        baud = 9600
        while True:
            line_iter = iter_serial_lines(port=port, baud=baud)
            async for raw in line_iter:
                line = raw.strip()
                if not line or not line.startswith("$G"):
                    await asyncio.sleep(0.01)
                    continue
                print(line)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("interrupted")
        raise SystemExit(0) from None
