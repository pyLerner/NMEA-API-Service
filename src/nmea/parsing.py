# =============================================================================
# NMEA parsing utilities
# =============================================================================

import re
from datetime import datetime, timezone
from typing import Any, Optional

GNRMC_RE = re.compile(r"^\$G[PN]RMC,")
CHECKSUM_RE = re.compile(r"^\$(.*)\*([0-9A-Fa-f]{2})$")
GGA_RE = re.compile(r"^\$G[PN]GGA,")


def nmea_checksum_is_valid(sentence: str) -> bool:
    """
    Validate NMEA checksum.

    Args:
        sentence: Full NMEA sentence with leading '$' and trailing '*XX'.

    Returns:
        True if checksum matches, False otherwise.
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
    Convert NMEA ddmm.mmmm to decimal degrees.

    Returns:
        Decimal degrees or None on failure/empty.
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


def parse_gga_satellites(sentence: str) -> Optional[int]:
    """
    Parse satellites count from $GPGGA/$GNGGA sentence.

    GGA fields reference:
      0: $GPGGA
      1: UTC time
      2: Latitude
      3: N/S
      4: Longitude
      5: E/W
      6: Fix quality
      7: Number of satellites (integer)
      ...

    Args:
        sentence: NMEA GGA sentence.

    Returns:
        Satellites count (int) or None if not available or invalid.
    """
    s = sentence.strip()
    if "*" in s and not nmea_checksum_is_valid(s):
        return None

    payload = s[1:] if s.startswith("$") else s
    payload = payload.split("*", 1)[0] if "*" in payload else payload
    parts = payload.split(",")

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
    Parse $GNRMC/$GPRMC sentence and return a dict of fields, augmented with satellites_count.

    Fields produced:
    - datetime (ISO8601 UTC)
    - is_valid ('A' or 'V')
    - latitude (decimal degrees, signed by hemisphere)
    - latitude_hemi ('N'|'S' or None)
    - longitude (decimal degrees, signed by hemisphere)
    - longitude_hemi ('E'|'W' or None)
    - speed (knots -> float or None)
    - direction (degrees -> float or None)
    - mode ('E'|'D'|'A'|'N' or None)
    - satellites_count (int or None)

    Args:
        sentence: NMEA RMC sentence.
        satellites_hint: latest satellites count observed from GGA; may be None.

    Returns:
        Parsed record dict or None on failure.
    """
    s = sentence.strip()
    if not s:
        return None
    if "*" in s and not nmea_checksum_is_valid(s):
        return None

    payload = s[1:] if s.startswith("$") else s
    payload = payload.split("*", 1)[0] if "*" in payload else payload
    parts = payload.split(",")

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

        speed = float(speed_str) if speed_str else 0.0  # None
        direction = float(course_str) if course_str else 0.0 # None

        # Указываем дефолтные значение. Не None
        return {
            "datetime": dt_utc.isoformat() if dt_utc else None,
            "is_valid": status if status in ("A", "V") else None,
            "latitude": latitude if latitude else 0.0,
            "latitude_hemi": lat_hemi if lat_hemi in ("N", "S") else "N", # None,
            "longitude": longitude if longitude else 0.0, 
            "longitude_hemi": lon_hemi if lon_hemi in ("E", "W") else "E", # None,
            "speed": speed,
            "direction": direction,
            "mode": mode if mode in ("E", "D", "A", "N") else None,
            "satellites_count": satellites_hint
                if isinstance(satellites_hint, int)
            else 0,
        }
    except Exception:
        return None
