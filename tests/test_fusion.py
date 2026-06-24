# =============================================================================
# NavFusion unit tests
# =============================================================================
from __future__ import annotations

import time

from models.data_models import VehicleProfile
from navigation.fusion import NavFusion


def _tram_profile() -> VehicleProfile:
    return VehicleProfile(
        v_max_kmh=25,
        a_max=1.0,
        t_hold_sec=12,
        t_lost_sec=60,
        frozen_jump_m=2.0,
        standstill_pos_m=0.3,
        standstill_sec=3,
        innov_gate_sigma=3.0,
        innov_gate_min_m=2.0,
        rmc_invalid_inflate=8.0,
    )


def _rmc_rec(lat: float, lon: float, is_valid: str = "A") -> dict:
    lat_a, lat_h, lon_a, lon_h = abs(lat), "N" if lat >= 0 else "S", abs(lon), (
        "E" if lon >= 0 else "W"
    )
    return {
        "datetime": "2024-01-01T12:00:00+00:00",
        "is_valid": is_valid,
        "latitude": lat_a,
        "latitude_hemi": lat_h,
        "longitude": lon_a,
        "longitude_hemi": lon_h,
        "speed": 0.0,
        "direction": 0.0,
        "mode": "A",
        "satellites_count": 8,
        "source": "nmea",
    }


def test_fusion_requires_rmc_before_ecef() -> None:
    fusion = NavFusion(_tram_profile())
    ecef = {
        "datetime": "2024-01-01T12:00:01+00:00",
        "is_valid": "A",
        "latitude": 48.1173,
        "latitude_hemi": "N",
        "longitude": 11.5167,
        "longitude_hemi": "E",
        "source": "ecef",
    }
    assert fusion.ingest_ecef(ecef) is None
    assert not fusion.initialized


def test_fusion_rmc_good_quality() -> None:
    fusion = NavFusion(_tram_profile())
    out = fusion.ingest_rmc(_rmc_rec(48.1173, 11.5167))
    assert out is not None
    assert out.quality == "GOOD"
    assert fusion.initialized


def test_fusion_rejects_impossible_speed_tram() -> None:
    fusion = NavFusion(_tram_profile())
    fusion.ingest_rmc(_rmc_rec(48.1173, 11.5167))
    time.sleep(0.05)
    far = fusion.ingest_rmc(_rmc_rec(48.2, 11.6))
    assert far is not None
    assert far.quality != "GOOD" or far.latitude != 48.2


def test_fusion_bus_allows_higher_speed() -> None:
    bus = VehicleProfile(
        v_max_kmh=80,
        a_max=2.5,
        t_hold_sec=25,
        t_lost_sec=90,
        frozen_jump_m=5.0,
        standstill_pos_m=0.3,
        standstill_sec=3,
        innov_gate_sigma=3.0,
        innov_gate_min_m=5.0,
        rmc_invalid_inflate=8.0,
    )
    fusion = NavFusion(bus)
    fusion.ingest_rmc(_rmc_rec(55.75, 37.62))
    time.sleep(0.05)
    out = fusion.ingest_rmc(_rmc_rec(55.7501, 37.6201))
    assert out is not None
    assert out.quality == "GOOD"
