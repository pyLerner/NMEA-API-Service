import asyncio
from pathlib import Path
from typing import AsyncIterator

from serial.serialutil import SerialException 

# Optional: pyserial-asyncio for async serial
try:
    import serial_asyncio # type: ignore
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
        # writer is not returned by open_serial_connection; port closes with GC.
        pass


if __name__ == "__main__":
    
    async def main():
        """
        Диагностика работы последовательного порта.
        Чтение NMEA по строкам из порта
        """
        port = "/dev/ttyS3"
        baud=9600
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
        exit()