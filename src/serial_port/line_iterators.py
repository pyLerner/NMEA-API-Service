# -*- coding: utf-8 -*-
# =============================================================================
# Асинхронные итераторы строк: serial, файл, stdin (UTF-8)
# =============================================================================
"""
Источники NMEA-строк для ``runner_task``.

- ``iter_reopenable_serial_lines`` — serial с методом ``reopen()`` для восстановления порта;
- ``iter_serial_lines`` — простой async-итератор serial;
- ``iter_file_lines`` / ``iter_stdin_lines`` — режимы replay и отладки.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

try:
    import serial_asyncio  # type: ignore
except Exception:
    serial_asyncio = None  # fallback на file/stdin без pyserial-asyncio


async def iter_reopenable_serial_lines(port: str, baud: int) -> Any:
    """
    Создать async-итератор serial-строк с возможностью ``reopen()``.

    Используется основным циклом чтения: при длительном отсутствии GNRMC
    порт закрывается и открывается заново без перезапуска процесса.

    Args:
        port: Путь к устройству (например ``/dev/ttyS3``).
        baud: Скорость порта, бит/с.

    Returns:
        Экземпляр ``ReopenableSerial`` (async iterable).

    Raises:
        RuntimeError: если не установлен ``pyserial-asyncio``.
    """
    if serial_asyncio is None:
        raise RuntimeError(
            "pyserial-asyncio is not installed. Install via 'uv pip install pyserial-asyncio'."
        )

    class ReopenableSerial:
        """Serial-порт с переоткрытием и фильтром NMEA-строк."""

        def __init__(self, port_: str, baud_: int) -> None:
            self._port = port_
            self._baud = baud_
            self._reader: Any = None
            self._transport: Any = None

        async def _open(self) -> None:
            """Открыть async-соединение с serial."""
            self._reader, self._transport = await serial_asyncio.open_serial_connection(
                url=self._port,
                baudrate=self._baud,
                limit=256 * 1024,
            )

        async def reopen(self) -> None:
            """Закрыть порт, подождать и открыть снова."""
            if self._transport is not None:
                self._transport.close()
            self._reader = None
            self._transport = None
            await asyncio.sleep(0.5)
            await self._open()

        def __aiter__(self) -> AsyncIterator[str]:
            return self._iter_lines()

        async def _iter_lines(self) -> AsyncIterator[str]:
            """Читать строки; отдавать только предложения, начинающиеся с ``$`` или ``!``."""
            await self._open()
            while True:
                try:
                    line = await self._reader.readline()
                    if not line:
                        await asyncio.sleep(0.05)
                        continue
                    decoded = line.decode("ascii", errors="ignore").strip()
                    if decoded.startswith(("$", "!")):
                        yield decoded
                except ValueError as e:
                    if "chunk exceed the limit" in str(e):
                        await self._reader.read(1024)
                        continue
                    raise

    return ReopenableSerial(port, baud)


async def iter_serial_lines(port: str, baud: int) -> AsyncIterator[str]:
    """
    Async-итератор строк с serial-порта (без переоткрытия).

    Буфер увеличен до 256 КБ; шум без ``\\n`` сбрасывается чтением 1 КБ.
    В yield попадают только строки, начинающиеся с ``$`` или ``!``.

    Args:
        port: Путь к устройству.
        baud: Скорость порта, бит/с.

    Yields:
        Декодированные NMEA-строки (ASCII, без хвостового ``\\r\\n``).

    Raises:
        RuntimeError: если не установлен ``pyserial-asyncio``.
    """
    if serial_asyncio is None:
        raise RuntimeError(
            "pyserial-asyncio is not installed. Install via 'uv pip install pyserial-asyncio'."
        )

    reader, _ = await serial_asyncio.open_serial_connection(
        url=port,
        baudrate=baud,
        limit=256 * 1024,
    )

    try:
        while True:
            try:
                line = await reader.readline()
                if not line:
                    await asyncio.sleep(0.05)
                    continue

                decoded = line.decode("ascii", errors="ignore").strip()

                if decoded.startswith(("$", "!")):
                    yield decoded

            except ValueError as e:
                if "chunk exceed the limit" in str(e):
                    await reader.read(1024)
                    continue
                raise e
    finally:
        pass


async def iter_file_lines(path: str) -> AsyncIterator[str]:
    """
    Async-итератор строк из файла NMEA (replay).

    Чтение выполняется в ``run_in_executor``, чтобы не блокировать event loop.

    Args:
        path: Путь к файлу лога NMEA.

    Yields:
        Строки файла как есть (с ``\\n``).

    Raises:
        FileNotFoundError: если файл не существует.
    """
    loop = asyncio.get_running_loop()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    def _read_all() -> list[str]:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.readlines()

    lines = await loop.run_in_executor(None, _read_all)
    for ln in lines:
        yield ln


async def iter_stdin_lines() -> AsyncIterator[str]:
    """
    Async-итератор строк из stdin (режим ``[System].Stdin``).

    Yields:
        Строки стандартного ввода.
    """
    loop = asyncio.get_running_loop()

    def _stdin_iter() -> list[str]:
        import sys as _sys

        return list(_sys.stdin)

    lines = await loop.run_in_executor(None, _stdin_iter)
    for ln in lines:
        yield ln
