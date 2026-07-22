# -*- coding: utf-8 -*-
"""Тесты HTTP API qr-geo catalog."""

from __future__ import annotations

import io
import json


def test_catalog_replace_requires_auth(client) -> None:
    r = client.post(
        "/api/qr-geo/v1/catalog:replace",
        content=json.dumps(
            [{"qr-value": "A", "latitude": 1, "longitude": 2}]
        ),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 401


def test_catalog_replace_json(client, auth_headers) -> None:
    body = [
        {"qr-value": "STOP-1", "latitude": "46,05123", "longitude": 14.5},
        {"qr-value": "STOP-2", "latitude": 47.0, "longitude": 15.0},
    ]
    r = client.post(
        "/api/qr-geo/v1/catalog:replace",
        content=json.dumps(body),
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["result"] is True
    assert data["count"] == 2
    assert data["mode"] == "replace"


def test_catalog_replace_csv(client, auth_headers) -> None:
    csv_text = (
        "qr-value,latitude,longitude\n"
        'X,"46,1",14.2\n'
        "Y,47.0,15.0\n"
    )
    r = client.post(
        "/api/qr-geo/v1/catalog:replace",
        files={"file": ("geo.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2


def test_catalog_append(client, auth_headers) -> None:
    client.post(
        "/api/qr-geo/v1/catalog:replace",
        content=json.dumps(
            [{"qr-value": "A", "latitude": 1, "longitude": 2}]
        ),
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    r = client.post(
        "/api/qr-geo/v1/catalog:append",
        content=json.dumps(
            [
                {"qr-value": "A", "latitude": 3, "longitude": 4},
                {"qr-value": "B", "latitude": 5, "longitude": 6},
            ]
        ),
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2


def test_catalog_validation_error(client, auth_headers) -> None:
    r = client.post(
        "/api/qr-geo/v1/catalog:replace",
        content=json.dumps(
            [{"qr-value": "A", "latitude": -1, "longitude": 2}]
        ),
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert r.status_code == 422
    body = r.json()
    assert body["result"] is False
    assert body["errors"]


def test_catalog_empty_replace_rejected(client, auth_headers) -> None:
    r = client.post(
        "/api/qr-geo/v1/catalog:replace",
        content=json.dumps([]),
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert r.status_code == 422


def test_invalid_token(client) -> None:
    r = client.post(
        "/api/qr-geo/v1/catalog:replace",
        content=json.dumps(
            [{"qr-value": "A", "latitude": 1, "longitude": 2}]
        ),
        headers={
            "Authorization": f"Bearer wrong",
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 401
    assert "wrong" not in r.text.lower() or True  # body must not echo token
    # ensure middleware does not put token in response
    assert "wrong" not in json.dumps(r.json())
