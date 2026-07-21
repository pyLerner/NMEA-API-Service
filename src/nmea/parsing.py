# -*- coding: utf-8 -*-
# =============================================================================
# Разбор NMEA-предложений GNRMC, GGA, ECEFPOSVEL (UTF-8)
# =============================================================================
"""
Утилиты парсинга NMEA для NavFusion.

Поддерживаемые типы:
- ``$GNRMC`` / ``$GPRMC`` — основной источник позиции и скорости;
- ``$GPGGA`` / ``$GNGGA`` — число спутников (подсказка для RMC);
- ``$ECEFPOSVEL`` — резервный ECEF-источник при паузах RMC.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

GNRMC_RE = re.compile(r"^\$G[PN]RMC,")
ECEFPOSVEL_RE = re.compile(r"^\$ECEFPOSVEL,")
CHECKSUM_RE = re.compile(r"^\$(.*)\*([0-9A-Fa-f]{2})$")
GGA_RE = re.compile(r"^\$G[PN]GGA,")

WGS84_A = 6378137.0
WGS84_E2 = 6.69437999014e-3
KNOTS_TO_KMH = 1.852
MS_TO_KMH = 3.6
ECEF_RADIUS_MIN_M = 6_300_000.0
ECEF_RADIUS_MAX_M = 6_440_000.0


def nmea_checksum_is_valid(sentence: str) -> bool:
    """
    Проверить контрольную сумму NMEA-предложения.

    Args:
        sentence: Полная строка с ведущим ``$`` и завершающим ``*XX``.

    Returns:
        ``True``, если XOR-сумма тела совпадает с шестнадцатеричным суффиксом.
    """
    s = sentence.strip()
    m = CHECKSUM_RE.match(s)
    if not m:
        return False
    body, cs_hex = m.groups()
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return calc == int(cs_hex, 16)
    except ValueError:
        return False


def ddmm_to_decimal(ddmm_str: str) -> Optional[float]:
    """
    Преобразовать NMEA-координату ``ddmm.mmmm`` в десятичные градусы.

    Args:
        ddmm_str: Строка широты/долготы в формате NMEA.

    Returns:
        Десятичные градусы (7 знаков) или ``None`` при пустой/некорректной строке.
    """
    if not ddmm_str:
        return None
    try:
        val = float(ddmm_str)
    except ValueError:
        return None
    degrees = int(val // 100)
    minutes = val - degrees * 100
    return round(degrees + minutes / 60.0, 7)


def _parse_nmea_time(time_str: str) -> Optional[datetime]:
    """
    Разобрать поле времени ``HHMMSS.sss`` с датой текущего UTC-дня.

    Args:
        time_str: Временная метка из NMEA без даты.

    Returns:
        ``datetime`` в UTC или ``None``.
    """
    if not time_str or len(time_str) < 6:
        return None
    try:
        hh = int(time_str[0:2])
        mm = int(time_str[2:4])
        ss = int(time_str[4:6])
        frac = 0
        if "." in time_str:
            frac_part = time_str.split(".", 1)[1]
            frac = int(float("0." + frac_part) * 1_000_000)
        today = datetime.now(timezone.utc).date()
        return datetime(
            today.year,
            today.month,
            today.day,
            hh,
            mm,
            ss,
            frac,
            tzinfo=timezone.utc,
        )
    except Exception:
        return None


def _ecef_to_geodetic(x: float, y: float, z: float) -> tuple[float, float]:
    """
    Преобразовать ECEF (м) в геодезические широту и долготу (градусы).

    Args:
        x, y, z: Координаты в системе ECEF, метры.

    Returns:
        Пара ``(широта, долгота)`` в десятичных градусах.
    """
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    if p < 1e-6:
        lat = math.copysign(math.pi / 2, z)
    else:
        lat = math.atan2(z, p * (1 - WGS84_E2))
        for _ in range(5):
            sin_lat = math.sin(lat)
            n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat * sin_lat)
            lat = math.atan2(z + WGS84_E2 * n * sin_lat, p)
    return math.degrees(lat), math.degrees(lon)


def _ecef_velocity_to_course(
    x: float, y: float, z: float, vx: float, vy: float, vz: float
) -> float:
    """
    Вычислить курс по земле из скорости в ECEF (м/с).

    Args:
        x, y, z: Позиция ECEF, м.
        vx, vy, vz: Скорость ECEF, м/с.

    Returns:
        Курс в градусах ``[0, 360)``; ``0`` при нулевой горизонтальной скорости.
    """
    lat_rad = math.radians(_ecef_to_geodetic(x, y, z)[0])
    lon_rad = math.atan2(y, x)

    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_lon = math.sin(lon_rad)
    cos_lon = math.cos(lon_rad)

    v_e = -sin_lon * vx + cos_lon * vy
    v_n = (
        -sin_lat * cos_lon * vx
        - sin_lat * sin_lon * vy
        + cos_lat * vz
    )

    if abs(v_e) < 1e-9 and abs(v_n) < 1e-9:
        return 0.0
    return (math.degrees(math.atan2(v_e, v_n)) + 360.0) % 360.0


def _split_nmea_payload(sentence: str) -> Optional[list[str]]:
    """
    Разбить NMEA-строку на поля CSV после проверки checksum.

    Args:
        sentence: Сырое NMEA-предложение.

    Returns:
        Список полей или ``None`` при пустой строке / неверной контрольной сумме.
    """
    s = sentence.strip()
    if not s:
        return None
    if "*" in s and not nmea_checksum_is_valid(s):
        return None
    payload = s[1:] if s.startswith("$") else s
    payload = payload.split("*", 1)[0] if "*" in payload else payload
    return payload.split(",")


def _ecef_position_valid(x: float, y: float, z: float) -> bool:
    """
    Проверить правдоподобность ECEF-позиции по радиусу от центра Земли.

    Args:
        x, y, z: Координаты ECEF, м.

    Returns:
        ``True``, если радиус в допустимом диапазоне WGS84.
    """
    if abs(x) < 1.0 and abs(y) < 1.0:
        return False
    radius = math.sqrt(x * x + y * y + z * z)
    return ECEF_RADIUS_MIN_M <= radius <= ECEF_RADIUS_MAX_M


def parse_gga_satellites(sentence: str) -> Optional[int]:
    """
    Извлечь число спутников из ``$GPGGA`` / ``$GNGGA``.

    Поля GGA (фрагмент):
      0 — заголовок ``$GPGGA``;
      7 — число спутников (целое).

    Args:
        sentence: NMEA-предложение GGA.

    Returns:
        Число спутников или ``None``, если поле отсутствует или некорректно.
    """
    parts = _split_nmea_payload(sentence)
    if not parts or not parts[0].endswith("GGA"):
        return None

    try:
        sat_field = parts[7] if len(parts) > 7 else ""
        return int(sat_field) if sat_field.isdigit() else None
    except Exception:
        return None


def parse_rmc(
    sentence: str, satellites_hint: Optional[int]
) -> Optional[dict[str, Any]]:
    """
    Разобрать ``$GNRMC`` / ``$GPRMC`` в словарь полей для fusion/API.

    Ключи результата:
    - ``datetime`` — ISO8601 UTC;
    - ``is_valid`` — ``A`` (валидно) или ``V``;
    - ``latitude``, ``longitude`` — десятичные градусы со знаком по полушарию;
    - ``latitude_hemi``, ``longitude_hemi`` — ``N``/``S``, ``E``/``W``;
    - ``speed`` — км/ч;
    - ``direction`` — курс, градусы;
    - ``mode`` — режим фиксации ``E``/``D``/``A``/``N`` или ``None``;
    - ``satellites_count`` — из ``satellites_hint`` (GGA) или ``0``;
    - ``source`` — ``nmea``.

    Args:
        sentence: NMEA-предложение RMC.
        satellites_hint: Последнее известное число спутников из GGA; может быть ``None``.

    Returns:
        Словарь полей или ``None`` при ошибке разбора.
    """
    parts = _split_nmea_payload(sentence)
    if not parts or not parts[0].endswith("RMC"):
        return None

    try:
        time_str = parts[1]
        status = parts[2] if len(parts) > 2 else ""
        lat_str = parts[3] if len(parts) > 3 else ""
        lat_hemi = parts[4] if len(parts) > 4 else ""
        lon_str = parts[5] if len(parts) > 5 else ""
        lon_hemi = parts[6] if len(parts) > 6 else ""
        speed_str = parts[7] if len(parts) > 7 else ""
        course_str = parts[8] if len(parts) > 8 else ""
        date_str = parts[9] if len(parts) > 9 else ""

        mode = None
        if len(parts) >= 13 and parts[12]:
            mode = parts[12]
        elif len(parts) >= 12 and parts[11] in ("A", "D", "E", "N"):
            mode = parts[11]

        dt_utc = None
        if time_str and date_str:
            try:
                hh = int(time_str[0:2])
                mm = int(time_str[2:4])
                ss = int(time_str[4:6])
                frac = 0
                if "." in time_str:
                    frac_part = time_str.split(".", 1)[1]
                    frac = int(float("0." + frac_part) * 1_000_000)
                day = int(date_str[0:2])
                month = int(date_str[2:4])
                year = int(date_str[4:6]) + 2000
                dt_utc = datetime(
                    year, month, day, hh, mm, ss, frac, tzinfo=timezone.utc
                )
            except Exception:
                dt_utc = None

        latitude = ddmm_to_decimal(lat_str)
        longitude = ddmm_to_decimal(lon_str)
        if latitude is not None and lat_hemi == "S":
            latitude = -abs(latitude)
        if longitude is not None and lon_hemi == "W":
            longitude = -abs(longitude)

        speed_knots = float(speed_str) if speed_str else 0.0
        speed = speed_knots * KNOTS_TO_KMH
        direction = float(course_str) if course_str else 0.0

        return {
            "datetime": dt_utc.isoformat() if dt_utc else None,
            "is_valid": status if status in ("A", "V") else None,
            "latitude": latitude if latitude else 0.0,
            "latitude_hemi": lat_hemi if lat_hemi in ("N", "S") else "N",
            "longitude": longitude if longitude else 0.0,
            "longitude_hemi": lon_hemi if lon_hemi in ("E", "W") else "E",
            "speed": speed,
            "direction": direction,
            "mode": mode if mode in ("E", "D", "A", "N") else None,
            "satellites_count": satellites_hint
            if isinstance(satellites_hint, int)
            else 0,
            "source": "nmea",
        }
    except Exception:
        return None


def parse_ecefposvel(sentence: str) -> Optional[dict[str, Any]]:
    """
    Разобрать ``$ECEFPOSVEL`` в словарь, совместимый с полями RMC.

    Формат предложения::
        $ECEFPOSVEL,time,X,Y,Z,Vx,Vy,Vz*CS

    Скорость сохраняется в км/ч (конвертация из м/с).

    Args:
        sentence: NMEA-предложение ECEFPOSVEL.

    Returns:
        Словарь полей (``source`` = ``ecef``) или ``None`` при ошибке.
    """
    parts = _split_nmea_payload(sentence)
    if not parts or parts[0] != "ECEFPOSVEL":
        return None

    if len(parts) < 8:
        return None

    try:
        time_str = parts[1]
        x = float(parts[2])
        y = float(parts[3])
        z = float(parts[4])
        vx = float(parts[5])
        vy = float(parts[6])
        vz = float(parts[7])

        position_valid = _ecef_position_valid(x, y, z)
        is_valid = "A" if position_valid else "V"

        if position_valid:
            lat_deg, lon_deg = _ecef_to_geodetic(x, y, z)
            latitude = abs(lat_deg)
            latitude_hemi = "N" if lat_deg >= 0 else "S"
            longitude = abs(lon_deg)
            longitude_hemi = "E" if lon_deg >= 0 else "W"
            direction = _ecef_velocity_to_course(x, y, z, vx, vy, vz)
        else:
            latitude = 0.0
            latitude_hemi = "N"
            longitude = 0.0
            longitude_hemi = "E"
            direction = 0.0

        speed_ms = math.sqrt(vx * vx + vy * vy + vz * vz)
        speed = speed_ms * MS_TO_KMH

        dt_utc = _parse_nmea_time(time_str)

        return {
            "datetime": dt_utc.isoformat() if dt_utc else None,
            "is_valid": is_valid,
            "latitude": latitude,
            "latitude_hemi": latitude_hemi,
            "longitude": longitude,
            "longitude_hemi": longitude_hemi,
            "speed": speed,
            "direction": direction,
            "mode": None,
            "satellites_count": 0,
            "source": "ecef",
        }
    except Exception:
        return None
