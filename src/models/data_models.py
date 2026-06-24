# =============================================================================
# Модели конфигурации и загрузка TOML
# =============================================================================

import logging
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_SIZE_SUFFIX = {
    "k": 1024,
    "m": 1024**2,
    "g": 1024**3,
}


def parse_max_size(value: str | int) -> int:
    """
    Разобрать размер лог-файла: байты или строка с суффиксом k/m/g (регистр не важен).
    """
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"MaxSize must be positive, got {value}")
        return value

    text = str(value).strip()
    if not text:
        raise ValueError("MaxSize must not be empty")

    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmgKMG])?", text)
    if not match:
        raise ValueError(f"Invalid MaxSize format: {value!r}")

    number = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    multiplier = _SIZE_SUFFIX.get(suffix, 1)
    size = int(number * multiplier)
    if size <= 0:
        raise ValueError(f"MaxSize must be positive, got {value!r}")
    return size


def parse_log_level(value: str) -> int:
    """Разобрать уровень логирования (INFO, DEBUG, …)."""
    level = logging.getLevelName(str(value).strip().upper())
    if not isinstance(level, int):
        raise ValueError(f"Invalid LogLevel: {value!r}")
    return level


def parse_yes_no(value: str | bool, field_name: str) -> bool:
    """Разобрать yes/no (регистр не важен)."""
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized == "yes":
        return True
    if normalized == "no":
        return False
    raise ValueError(f"Invalid {field_name}: {value!r} (expected yes or no)")


@dataclass(frozen=True)
class DatabaseConfig:
    """Параметры базы данных SQLite."""

    db_path: str
    max_rows: int


@dataclass(frozen=True)
class HardwareConfig:
    """Параметры serial-порта."""

    port: str
    baud: int


@dataclass(frozen=True)
class ApiConfig:
    """Параметры HTTP API (хост, порт, токен)."""

    host: str
    port: int
    workers: int
    token: str


@dataclass(frozen=True)
class SystemConfig:
    """Общие системные настройки (каталог, источник входных данных)."""

    program_directory: str
    input_path: str
    stdin: bool


@dataclass(frozen=True)
class LogConfig:
    """Настройки логирования приложения и опционального сырого NMEA-лога."""

    log_dir: str
    log_name: str
    log_level: int
    max_logs: int
    max_size_bytes: int
    log_row_nmea: bool
    row_nmea_name: str


_VALID_PROFILES = frozenset({"tram", "bus", "custom"})

_VEHICLE_PROFILE_KEYS = {
    "VMaxKmh": "v_max_kmh",
    "AMax": "a_max",
    "THoldSec": "t_hold_sec",
    "TLostSec": "t_lost_sec",
    "FrozenJumpM": "frozen_jump_m",
    "StandstillPosM": "standstill_pos_m",
    "StandstillSec": "standstill_sec",
    "InnovGateSigma": "innov_gate_sigma",
    "InnovGateMinM": "innov_gate_min_m",
    "RmcInvalidInflate": "rmc_invalid_inflate",
}


@dataclass(frozen=True)
class VehicleProfile:
    v_max_kmh: float
    a_max: float
    t_hold_sec: float
    t_lost_sec: float
    frozen_jump_m: float
    standstill_pos_m: float
    standstill_sec: int
    innov_gate_sigma: float
    innov_gate_min_m: float
    rmc_invalid_inflate: float


@dataclass(frozen=True)
class NavigationConfig:
    profile_name: str
    vehicle_profiles_path: Path
    profile: VehicleProfile
    output_rate_hz: int
    serial_restart_on_rmc_loss: bool
    serial_restart_after_sec: float


@dataclass(frozen=True)
class MemoryConfig:
    """
    Параметры in-memory кэша.

    CacheRecordsLength: максимальный размер deque.
    CacheRecords: размер окна flush-цикла (порция в БД + ResidualCache в памяти).
    ResidualCache: число новейших записей, остающихся в кэше после flush.
    """

    cache_records_length: int
    cache_records_trigger: int
    residual_cache: int

    @property
    def flush_batch(self) -> int:
        """Число старейших записей, сбрасываемых в БД за один flush."""
        return self.cache_records_trigger - self.residual_cache


@dataclass(frozen=True)
class AppConfig:
    """Полная конфигурация приложения."""

    database: DatabaseConfig
    hardware: HardwareConfig
    api: ApiConfig
    system: SystemConfig
    log: LogConfig
    memory: MemoryConfig
    navigation: NavigationConfig


def _load_log_config(raw: dict, sys_: dict) -> LogConfig:
    log = raw.get("Log", {})
    log_dir = log.get("LogDir")
    if log_dir is None:
        log_dir = sys_.get("LogDir", "logs")

    return LogConfig(
        log_dir=str(log_dir),
        log_name=str(log.get("LogName", "gnrmc.log")),
        log_level=parse_log_level(log.get("LogLevel", "INFO")),
        max_logs=int(log.get("MaxLogs", 5)),
        max_size_bytes=parse_max_size(log.get("MaxSize", "5m")),
        log_row_nmea=parse_yes_no(log.get("LogRowNMEA", "no"), "LogRowNMEA"),
        row_nmea_name=str(log.get("RowNMEA", "nmea-row.log")),
    )


def _load_vehicle_profile(path: Path, section: str) -> VehicleProfile:
    if not path.exists():
        raise FileNotFoundError(f"VehicleProfiles not found: {path}")
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    if section not in raw:
        raise ValueError(
            f"Profile section [{section}] not found in {path}"
        )
    sec = raw[section]
    kwargs: dict[str, float | int] = {}
    for toml_key, field in _VEHICLE_PROFILE_KEYS.items():
        if toml_key not in sec:
            raise ValueError(
                f"Missing {toml_key} in [{section}] of {path}"
            )
        val = sec[toml_key]
        if toml_key == "StandstillSec":
            kwargs[field] = int(val)
        else:
            kwargs[field] = float(val)
    return VehicleProfile(**kwargs)  # type: ignore[arg-type]


def _validate_vehicle_profile(profile: VehicleProfile) -> None:
    if profile.v_max_kmh <= 0:
        raise ValueError("VMaxKmh must be > 0")
    if profile.a_max <= 0:
        raise ValueError("AMax must be > 0")
    if profile.frozen_jump_m <= 0:
        raise ValueError("FrozenJumpM must be > 0")
    if profile.t_hold_sec >= profile.t_lost_sec:
        raise ValueError("THoldSec must be < TLostSec")


def _load_navigation_config(raw: dict, config_dir: Path) -> NavigationConfig:
    nav = raw.get("Navigation", {})
    profile_name = str(nav.get("Profile", "tram")).strip().lower()
    if profile_name not in _VALID_PROFILES:
        raise ValueError(
            f"Navigation.Profile must be one of {sorted(_VALID_PROFILES)}, "
            f"got {profile_name!r}"
        )

    profiles_rel = nav.get("VehicleProfilesPath", "VehicleProfiles.toml")
    profiles_path = Path(profiles_rel)
    if not profiles_path.is_absolute():
        profiles_path = config_dir / profiles_path
    if not profiles_path.exists():
        bundled = Path(__file__).resolve().parent.parent.parent / "etc" / Path(
            profiles_rel
        ).name
        if bundled.exists():
            profiles_path = bundled

    profile = _load_vehicle_profile(profiles_path, profile_name)
    _validate_vehicle_profile(profile)

    output_rate_hz = int(nav.get("OutputRateHz", 10))
    if not 1 <= output_rate_hz <= 20:
        raise ValueError("OutputRateHz must be in [1, 20]")

    serial_restart_on = parse_yes_no(
        nav.get("SerialRestartOnRmcLoss", "yes"), "SerialRestartOnRmcLoss"
    )
    serial_restart_after = float(nav.get("SerialRestartAfterSec", 90))
    if serial_restart_after < profile.t_lost_sec:
        raise ValueError(
            "SerialRestartAfterSec must be >= TLostSec "
            f"(got {serial_restart_after} < {profile.t_lost_sec})"
        )

    return NavigationConfig(
        profile_name=profile_name,
        vehicle_profiles_path=profiles_path,
        profile=profile,
        output_rate_hz=output_rate_hz,
        serial_restart_on_rmc_loss=serial_restart_on,
        serial_restart_after_sec=serial_restart_after,
    )


def _validate_memory_config(mem: MemoryConfig) -> None:
    if mem.residual_cache < 0:
        raise ValueError("ResidualCache must be >= 0")
    if mem.residual_cache >= mem.cache_records_trigger:
        raise ValueError(
            "ResidualCache must be less than CacheRecords "
            f"(got {mem.residual_cache} >= {mem.cache_records_trigger})"
        )
    if mem.residual_cache >= mem.cache_records_length:
        raise ValueError(
            "ResidualCache must be less than CacheRecordsLength "
            f"(got {mem.residual_cache} >= {mem.cache_records_length})"
        )


def load_config(path: Path) -> AppConfig:
    """
    Загрузить TOML-конфиг и вернуть AppConfig.

    Raises:
        FileNotFoundError: файл конфигурации не найден.
        ValueError: некорректные значения параметров.
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

    memory = MemoryConfig(
        cache_records_length=int(mem.get("CacheRecordsLength", 5000)),
        cache_records_trigger=int(mem.get("CacheRecords", 100)),
        residual_cache=int(mem.get("ResidualCache", 10)),
    )
    _validate_memory_config(memory)

    config_dir = path.parent
    navigation = _load_navigation_config(raw, config_dir)

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
            workers=int(api.get("Workers", 2)),
            token=str(api.get("Token", "123")),
        ),
        system=SystemConfig(
            program_directory=sys_.get("ProgramDirectory", "/usr/local/gnrmc"),
            input_path=sys_.get("Input", ""),
            stdin=bool(sys_.get("Stdin", False)),
        ),
        log=_load_log_config(raw, sys_),
        memory=memory,
        navigation=navigation,
    )
