# -*- coding: utf-8 -*-
"""Тест резолва Bearer-токена из env и EventTimeSource."""

from __future__ import annotations

import pytest

from models.data_models import ENV_API_TOKEN, resolve_api_token
from qr_geo.config import normalize_event_time_source


def test_resolve_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv(ENV_API_TOKEN, " from-env ")
    assert resolve_api_token("from-toml") == "from-env"


def test_resolve_falls_back_to_toml(monkeypatch) -> None:
    monkeypatch.delenv(ENV_API_TOKEN, raising=False)
    assert resolve_api_token("from-toml") == "from-toml"


def test_normalize_event_time_source() -> None:
    assert normalize_event_time_source("event") == "event"
    assert normalize_event_time_source("load-image") == "load-image"
    assert normalize_event_time_source("timestamp") == "event"
    with pytest.raises(ValueError):
        normalize_event_time_source("bogus")
