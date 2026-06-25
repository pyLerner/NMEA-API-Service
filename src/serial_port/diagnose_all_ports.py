# -*- coding: utf-8 -*-
# =============================================================================
# Сканирование всех /dev/ttyS* на наличие данных (UTF-8)
# =============================================================================
"""
Утилита командной строки: перебор портов и типовых baudrate.

Помогает найти активный serial с NMEA на целевой платформе.
Запуск: ``python -m serial_port.diagnose_all_ports``.
"""
from __future__ import annotations

import glob
import time

import serial


def check_port_data() -> None:
    """
    Перебрать ``/dev/ttyS*`` и стандартные скорости; вывести порты с данными.

    Для каждой пары (порт, baudrate) открывает порт с ``timeout=2``,
    ждёт 0.5 с и печатает декодированный текст, если буфер не пуст.
    """
    ports = sorted(glob.glob("/dev/ttyS*"))
    baudrates = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]

    if not ports:
        print("Порты /dev/ttyS* не найдены.")
        return

    print(f"{'Порт':<12} | {'Baudrate':<10} | {'Статус данных'}")
    print("-" * 45)

    for port in ports:
        for baud in baudrates:
            try:
                with serial.Serial(port, baud, timeout=2) as ser:
                    ser.reset_input_buffer()
                    time.sleep(0.5)
                    if ser.in_waiting > 0:
                        raw_data = ser.read(ser.in_waiting)
                        text_data = raw_data.decode("utf-8", errors="replace").strip()

                        if text_data:
                            print(f"{port:<12} | {baud:<10} | ТЕКСТ: {text_data}")
                        else:
                            print(
                                f"{port:<12} | {baud:<10} | Получены непечатные символы"
                            )

            except (serial.SerialException, PermissionError):
                continue


if __name__ == "__main__":
    print("Начинаю сканирование (это может занять время)...")
    check_port_data()
