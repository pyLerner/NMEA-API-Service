# =============================================================================
# API record formatting for Go client compatibility
# =============================================================================
from __future__ import annotations

from api.record_format import format_record_for_api
from db.cache import Record


def test_format_record_id_null_becomes_zero() -> None:
    rec = Record(
        key_id=None,
        datetime="2026-01-01T00:00:00+00:00",
        is_valid="A",
        latitude=1.0,
        latitude_hemi="N",
        longitude=2.0,
        longitude_hemi="E",
        speed=0.0,
        direction=0.0,
        mode="A",
        satellites_count=5,
    )
    assert rec.to_dict()["record_id"] == 0


def test_format_coordinates_seven_decimals() -> None:
    out = format_record_for_api(
        {"record_id": 1, "latitude": 46.05123456789, "longitude": 14.50678901234}
    )
    assert out["latitude"] == 46.0512346
    assert out["longitude"] == 14.506789


def test_format_speed_one_decimal_kmh() -> None:
    out = format_record_for_api({"speed": 0.84})
    assert out["speed"] == 0.8
    out = format_record_for_api({"speed": 22.46})
    assert out["speed"] == 22.5


def test_format_direction_one_decimal() -> None:
    out = format_record_for_api({"direction": 176.54})
    assert out["direction"] == 176.5


def test_format_satellites_null_becomes_zero() -> None:
    out = format_record_for_api({"satellites_count": None})
    assert out["satellites_count"] == 0
