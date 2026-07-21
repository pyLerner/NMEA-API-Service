# =============================================================================
# load_config: [Sources.*] и legacy [Hardware]
# =============================================================================
from __future__ import annotations

from pathlib import Path

from models.data_models import load_config


def test_load_sources_nmea_hardware(tmp_path: Path) -> None:
    cfg_path = tmp_path / "src.toml"
    cfg_path.write_text(
        """
[Sources.nmea]
Enabled = true
Type = "serial-nmea"
HardwarePort = "/dev/ttyUSB0"
Baud = 115200

[Sources.imu]
Enabled = false
Type = "imu"

[Memory]
CacheRecords = 50
ResidualCache = 5
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg.hardware.port == "/dev/ttyUSB0"
    assert cfg.hardware.baud == 115200
    names = {p.name: p for p in cfg.sources}
    assert names["nmea"].enabled is True
    assert names["imu"].enabled is False
    assert names["nmea"].type == "serial-nmea"


def test_load_legacy_hardware_fallback(tmp_path: Path) -> None:
    cfg_path = tmp_path / "legacy.toml"
    cfg_path.write_text(
        """
[Hardware]
HardwarePort = "/dev/ttyS9"
Baud = 4800

[Memory]
CacheRecords = 50
ResidualCache = 5
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg.hardware.port == "/dev/ttyS9"
    assert len(cfg.sources) == 1
    assert cfg.sources[0].name == "nmea"
    assert cfg.sources[0].enabled is True
