# =============================================================================
# NMEA parsing: RMC and ECEFPOSVEL
# =============================================================================
from __future__ import annotations

import math

from nmea.parsing import (
    KNOTS_TO_KMH,
    MS_TO_KMH,
    parse_ecefposvel,
    parse_rmc,
)

REVKECEF = (
    "$ECEFPOSVEL,124015.000,3985352.629186,-54462.755461,"
    "4962832.255023,-0.008022,0.003776,0.022063*28"
)
USER_ECEF_INVALID = (
    "$ECEFPOSVEL,095840.403,0000000.000,0000000.000,6356902.314,"
    "0000000.000,0000000.000,0000000.000*28"
)
SAMPLE_RMC = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
BAD_CHECKSUM_ECEF = (
    "$ECEFPOSVEL,124015.000,3985352.629186,-54462.755461,"
    "4962832.255023,-0.008022,0.003776,0.022063*FF"
)


def test_parse_rmc_source_and_speed_kmh() -> None:
    parsed = parse_rmc(SAMPLE_RMC, satellites_hint=8)
    assert parsed is not None
    assert parsed["source"] == "nmea"
    assert parsed["is_valid"] == "A"
    assert parsed["satellites_count"] == 8
    assert math.isclose(22.4 * KNOTS_TO_KMH, parsed["speed"], rel_tol=1e-6)


def test_parse_ecefposvel_valid_revk_example() -> None:
    parsed = parse_ecefposvel(REVKECEF)
    assert parsed is not None
    assert parsed["source"] == "ecef"
    assert parsed["is_valid"] == "A"
    assert parsed["latitude"] > 0
    assert parsed["longitude"] > 0
    assert parsed["satellites_count"] == 0
    assert parsed["mode"] is None
    speed_ms = math.sqrt((-0.008022) ** 2 + 0.003776 ** 2 + 0.022063 ** 2)
    assert math.isclose(speed_ms * MS_TO_KMH, parsed["speed"], rel_tol=1e-6)
    assert parsed["datetime"] is not None


def test_parse_ecefposvel_xy_zero_is_invalid() -> None:
    parsed = parse_ecefposvel(USER_ECEF_INVALID)
    assert parsed is not None
    assert parsed["source"] == "ecef"
    assert parsed["is_valid"] == "V"
    assert parsed["latitude"] == 0.0
    assert parsed["longitude"] == 0.0
    assert parsed["speed"] == 0.0


def test_parse_ecefposvel_bad_checksum() -> None:
    assert parse_ecefposvel(BAD_CHECKSUM_ECEF) is None
