# =============================================================================
# Configuration models and loading
# =============================================================================

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DatabaseConfig:
    """Database-related configuration parameters."""

    db_path: str
    max_rows: int


@dataclass(frozen=True)
class HardwareConfig:
    """Hardware-related configuration for serial port input."""

    port: str
    baud: int


@dataclass(frozen=True)
class ApiConfig:
    """API server configuration (host, port, token)."""

    host: str
    port: int
    workers: int
    token: str


@dataclass(frozen=True)
class SystemConfig:
    """General system settings (paths, input source, logging)."""

    program_directory: str
    input_path: str
    stdin: bool
    log_dir: str


@dataclass(frozen=True)
class MemoryConfig:
    """In-memory cache configuration.

    CacheRecordsLength: max size (number of records) retained in the in-memory cache.
    CacheRecords: number of new items since last flush that triggers a DB write of the entire cache.
    """

    cache_records_length: int
    cache_records_trigger: int


@dataclass(frozen=True)
class AppConfig:
    """Full application configuration container."""

    database: DatabaseConfig
    hardware: HardwareConfig
    api: ApiConfig
    system: SystemConfig
    memory: MemoryConfig


def load_config(path: Path) -> AppConfig:
    """
    Load TOML configuration and return a structured AppConfig.

    Raises:
        FileNotFoundError: if the TOML file is missing.
        KeyError/TypeError: if required keys are missing or malformed.
    """
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    db = raw.get("Database", {})
    hw = raw.get("Hardware", {})
    api = raw.get("API", {})
    sys_ = raw.get("System", {})
    mem = raw.get("Memory", {})

    return AppConfig(
        database=DatabaseConfig(
            db_path=db.get("DB", "data/gnrmc.db"),
            max_rows=int(db.get("MaxRows", 150_000)),
        ),
        hardware=HardwareConfig(
            port=hw.get("HardwarePort", "/dev/ttyS3"),
            baud=int(hw.get("Baud", 9600)),
        ),
        api=ApiConfig(
            host=api.get("Host", "0.0.0.0"),
            port=int(api.get("HTTP_Port", 7000)),
            workers = int(api.get("Workers", 2)),
            token=str(api.get("Token", "123")),
        ),
        system=SystemConfig(
            program_directory=sys_.get("ProgramDirectory", "/usr/local/gnrmc"),
            input_path=sys_.get("Input", ""),
            stdin=bool(sys_.get("Stdin", False)),
            log_dir=sys_.get("LogDir", "logs"),
        ),
        memory=MemoryConfig(
            cache_records_length=int(mem.get("CacheRecordsLength", 5000)),
            cache_records_trigger=int(mem.get("CacheRecords", 100)),
        ),
    )
