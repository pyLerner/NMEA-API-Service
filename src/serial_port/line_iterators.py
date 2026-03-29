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
