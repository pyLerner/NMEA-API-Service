# ==========================================================================
# Line Iterators for Working with Serial Port, file and stdin
# =============================================================================
import asyncio
from pathlib import Path
from typing import AsyncIterator

# Optional: pyserial-asyncio for async serial
try:
    import serial_asyncio  # type: ignore
except Exception:
    serial_asyncio = None  # graceful fallback to file/stdin


async def iter_reopenable_serial_lines(port: str, baud: int):
    """
    Async iterator over serial lines with ``reopen()`` for port recovery.
    """
    if serial_asyncio is None:
        raise RuntimeError(
            "pyserial-asyncio is not installed. Install via 'uv pip install pyserial-asyncio'."
        )

    class ReopenableSerial:
        def __init__(self, port_: str, baud_: int) -> None:
            self._port = port_
            self._baud = baud_
            self._reader = None
            self._transport = None

        async def _open(self) -> None:
            self._reader, self._transport = await serial_asyncio.open_serial_connection(
                url=self._port,
                baudrate=self._baud,
                limit=256 * 1024,
            )

        async def reopen(self) -> None:
            if self._transport is not None:
                self._transport.close()
            self._reader = None
            self._transport = None
            await asyncio.sleep(0.5)
            await self._open()

        def __aiter__(self):
            return self._iter_lines()

        async def _iter_lines(self):
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
    Async iterator over lines from a serial port.

    Requires pyserial-asyncio. If unavailable, this raises RuntimeError.
    """
    if serial_asyncio is None:
        raise RuntimeError(
            "pyserial-asyncio is not installed. Install via 'uv pip install pyserial-asyncio'."
        )

    # reader, _ = await serial_asyncio.open_serial_connection(url=port, baudrate=baud)
    # try:
    #     while True:
    #         line = await reader.readline()
    #         if not line:
    #             await asyncio.sleep(0.05)
    #             continue
    #         yield line.decode("ascii", errors="ignore")
    # finally:
    #     # writer is not returned by open_serial_connection; port closes with GC.
    #     pass

    # 1. Увеличиваем лимит (например, до 256 КБ), чтобы шум не переполнял буфер мгновенно
    reader, _ = await serial_asyncio.open_serial_connection(
        url=port, 
        baudrate=baud, 
        limit=256 * 1024
    )

    try:
        while True:
            try:
                line = await reader.readline()
                if not line:
                    await asyncio.sleep(0.05)
                    continue
                
                decoded = line.decode("ascii", errors="ignore").strip()
                
                # 2. Фильтр шума: NMEA строки всегда начинаются с '$' или '!'
                if decoded.startswith(('$', '!')):
                    yield decoded

            except ValueError as e:
                # 3. Обработка "Limit exceeded": если буфер забился шумом без \n
                if "chunk exceed the limit" in str(e):
                    # Читаем один кусок, чтобы очистить забитый буфер и продолжить
                    await reader.read(1024)
                    continue
                raise e
    finally:
        pass



async def iter_file_lines(path: str) -> AsyncIterator[str]:
    """
    Async iterator over lines from a file (non-blocking via loop.run_in_executor).
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
    Async iterator over stdin lines (non-blocking via loop.run_in_executor).
    """
    loop = asyncio.get_running_loop()

    def _stdin_iter() -> list[str]:
        import sys as _sys

        return list(_sys.stdin)

    lines = await loop.run_in_executor(None, _stdin_iter)
    for ln in lines:
        yield ln
