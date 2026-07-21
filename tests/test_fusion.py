# =============================================================================
# NavFusion v2 unit tests
# =============================================================================
from __future__ import annotations

import asyncio
import time

from db.cache import RecordsCache
from models.data_models import VehicleProfile
from navigation.enums import NavQuality, PublishMode
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
        rmc_speed_zero_kmh=0.5,
        rmc_trust_modes=frozenset({"A", "D"}),
    )


def _rmc_rec(
    lat: float,
    lon: float,
    is_valid: str = "A",
    speed: float = 0.0,
    mode: str = "A",
) -> dict:
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
        "speed": speed,
        "direction": 109.0,
        "mode": mode,
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
        "speed": 0.0,
        "direction": 0.0,
        "source": "ecef",
    }
    assert fusion.ingest_ecef(ecef) is None
    assert not fusion.initialized


def test_fusion_rmc_good_quality() -> None:
    fusion = NavFusion(_tram_profile())
    out = fusion.ingest_rmc(_rmc_rec(48.1173, 11.5167))
    assert out is not None
    assert out.quality == NavQuality.GOOD.value
    assert fusion.initialized


def test_trusted_rmc_hard_reset_after_drift() -> None:
    fusion = NavFusion(_tram_profile(), publish_mode=PublishMode.MEASUREMENT)
    fusion.ingest_rmc(_rmc_rec(60.015107, 30.284370))
    fusion._x[0] = 500.0
    fusion._x[1] = 500.0
    fusion._x[2] = 5.0
    fusion._x[3] = 5.0
    out = fusion.ingest_rmc(_rmc_rec(60.015110, 30.284375))
    assert out is not None
    assert out.quality == NavQuality.GOOD.value
    assert abs(out.latitude - 60.015110) < 1e-4
    assert out.speed == 0.0


def test_untrusted_rmc_reject_lowers_quality() -> None:
    fusion = NavFusion(_tram_profile(), publish_mode=PublishMode.MEASUREMENT)
    fusion.ingest_rmc(_rmc_rec(48.1173, 11.5167))
    time.sleep(0.05)
    out = fusion.ingest_rmc(_rmc_rec(48.2, 11.6, mode="E"))
    assert out is None
    assert fusion.quality in (NavQuality.COAST, NavQuality.DEGRADED)


def test_standstill_rmc_zeros_speed() -> None:
    fusion = NavFusion(_tram_profile())
    base_lat, base_lon = 60.015107, 30.284370
    out = None
    for _ in range(5):
        time.sleep(0.35)
        out = fusion.ingest_rmc(_rmc_rec(base_lat, base_lon, speed=0.0))
    assert out is not None
    assert out.speed == 0.0
    assert fusion._frozen


def test_speed_from_rmc_not_delta_publish() -> None:
    fusion = NavFusion(_tram_profile())
    out = fusion.ingest_rmc(_rmc_rec(55.75, 37.62, speed=12.0))
    assert out is not None
    assert out.speed == 12.0
    assert out.direction == 109.0


def test_gate_uses_last_rmc_not_publish() -> None:
    fusion = NavFusion(_tram_profile())
    fusion.ingest_rmc(_rmc_rec(60.0, 30.0))
    for _ in range(10):
        fusion.predict_internal_only(0.1)
    time.sleep(0.55)
    out = fusion.ingest_rmc(_rmc_rec(60.00001, 30.00001))
    assert out is not None
    assert out.quality == NavQuality.GOOD.value


def test_measurement_mode_no_timer_cache() -> None:
    async def _run() -> int:
        cache = RecordsCache(100, 1000, 10, __import__("logging").getLogger("t"))
        fusion = NavFusion(_tram_profile(), publish_mode=PublishMode.MEASUREMENT)
        fusion.ingest_rmc(_rmc_rec(60.0, 30.0))

        async def _tick() -> None:
            for _ in range(10):
                fusion.predict_internal_only(0.1)
                if fusion.should_publish_timer():
                    out = fusion.build_publish_output()
                    if out is not None:
                        await cache.add(
                            __import__("runner_task", fromlist=["fusion_output_to_record"])
                            .fusion_output_to_record(out)
                        )
                await asyncio.sleep(0)

        await _tick()
        return len(await cache.snapshot())

    count = asyncio.run(_run())
    assert count == 0


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
        rmc_speed_zero_kmh=0.5,
        rmc_trust_modes=frozenset({"A", "D"}),
    )
    fusion = NavFusion(bus)
    fusion.ingest_rmc(_rmc_rec(55.75, 37.62))
    time.sleep(0.55)
    out = fusion.ingest_rmc(_rmc_rec(55.7501, 37.6201))
    assert out is not None
    assert out.quality == NavQuality.GOOD.value


def test_hybrid_should_publish_when_not_good() -> None:
    fusion = NavFusion(_tram_profile(), publish_mode=PublishMode.HYBRID)
    fusion.ingest_rmc(_rmc_rec(60.0, 30.0))
    assert fusion.should_publish_timer() is False
    fusion._quality = NavQuality.COAST
    fusion._last_rmc_seen_mono = time.monotonic() - 2.0
    assert fusion.should_publish_timer() is True
