# =============================================================================
# Тесты парсинга секции [Log] и вспомогательных функций
# =============================================================================
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from models.data_models import load_config, parse_max_size, parse_yes_no


def test_parse_max_size_suffixes() -> None:
    assert parse_max_size("5m") == 5 * 1024 * 1024
    assert parse_max_size("512k") == 512 * 1024
    assert parse_max_size("1g") == 1024**3
    assert parse_max_size(1_000_000) == 1_000_000


def test_parse_max_size_invalid() -> None:
    with pytest.raises(ValueError):
        parse_max_size("bad")
    with pytest.raises(ValueError):
        parse_max_size("0m")


def test_parse_yes_no() -> None:
    assert parse_yes_no("yes", "x") is True
    assert parse_yes_no("NO", "x") is False
    with pytest.raises(ValueError):
        parse_yes_no("maybe", "x")


def test_load_config_log_section(tmp_path: Path) -> None:
    cfg_path = tmp_path / "test.toml"
    cfg_path.write_text(
        """
[Log]
LogDir = "custom-logs"
LogName = "app.log"
LogLevel = "DEBUG"
MaxLogs = 3
MaxSize = "1m"
LogRowNMEA = "yes"
RowNMEA = "raw.log"

[Memory]
CacheRecords = 50
ResidualCache = 5
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg.log.log_dir == "custom-logs"
    assert cfg.log.log_name == "app.log"
    assert cfg.log.log_level == logging.DEBUG
    assert cfg.log.max_logs == 3
    assert cfg.log.max_size_bytes == 1024 * 1024
    assert cfg.log.log_row_nmea is True
    assert cfg.log.row_nmea_name == "raw.log"
    assert cfg.memory.flush_batch == 45


def test_load_config_logdir_fallback_from_system(tmp_path: Path) -> None:
    cfg_path = tmp_path / "legacy.toml"
    cfg_path.write_text(
        """
[System]
LogDir = "legacy-logs"
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg.log.log_dir == "legacy-logs"


def test_load_config_rejects_invalid_residual(tmp_path: Path) -> None:
    cfg_path = tmp_path / "bad.toml"
    cfg_path.write_text(
        """
[Memory]
CacheRecords = 10
ResidualCache = 10
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ResidualCache"):
        load_config(cfg_path)
