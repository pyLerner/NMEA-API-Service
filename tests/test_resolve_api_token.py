# -*- coding: utf-8 -*-
"""Тест резолва Bearer-токена из env."""

from __future__ import annotations

import os

from models.data_models import ENV_API_TOKEN, resolve_api_token


def test_resolve_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv(ENV_API_TOKEN, " from-env ")
    assert resolve_api_token("from-toml") == "from-env"


def test_resolve_falls_back_to_toml(monkeypatch) -> None:
    monkeypatch.delenv(ENV_API_TOKEN, raising=False)
    assert resolve_api_token("from-toml") == "from-toml"
