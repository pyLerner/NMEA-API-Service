# -*- coding: utf-8 -*-
"""Тесты нормализации и валидации qr_geo."""

from __future__ import annotations

from qr_geo.validate import normalize_coord_string, parse_coord, validate_all, validate_entry


def test_normalize_quotes_and_comma() -> None:
    assert normalize_coord_string('"46,05123"') == "46.05123"
    assert normalize_coord_string("'14,5'") == "14.5"
    assert normalize_coord_string(" 46.05123 ") == "46.05123"


def test_parse_coord_number() -> None:
    val, err = parse_coord(46.5, "latitude")
    assert err is None
    assert val == 46.5


def test_negative_latitude_rejected() -> None:
    entry, errors = validate_entry(
        {"qr-value": "A", "latitude": -1, "longitude": 10},
        row=1,
    )
    assert entry is None
    assert any(e.field == "latitude" for e in errors)


def test_default_hemispheres() -> None:
    entry, errors = validate_entry(
        {"qr-value": "STOP-1", "latitude": "46,1", "longitude": "14.5"},
        row=1,
    )
    assert errors == []
    assert entry is not None
    assert entry.lat_hemi == "N"
    assert entry.lon_hemi == "E"
    assert entry.latitude == 46.1


def test_south_hemisphere_rejected() -> None:
    entry, errors = validate_entry(
        {
            "qr-value": "A",
            "latitude": 10,
            "longitude": 20,
            "lat-hemisphere": "S",
        },
        row=1,
    )
    assert entry is None
    assert any(e.field == "lat-hemisphere" for e in errors)


def test_duplicate_in_file() -> None:
    rows = [
        {"qr-value": "A", "latitude": 1, "longitude": 2},
        {"qr-value": "A", "latitude": 3, "longitude": 4},
    ]
    entries, errors = validate_all(rows, row_offset=0)
    assert len(entries) == 1
    assert any("duplicate" in e.message for e in errors)
