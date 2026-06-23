import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from models.data_models import LogConfig

_APP_LOGGER_NAME = "gnrmc"
_NMEA_ROW_LOGGER_NAME = "gnrmc.nmea_row"


def _rotating_handler(
    log_path: Path,
    max_bytes: int,
    backup_count: int,
    formatter: logging.Formatter,
) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    return handler


def setup_logger(log_cfg: LogConfig) -> tuple[logging.Logger, logging.Logger | None]:
    """
    Создать основной логгер и опциональный логгер сырых NMEA-строк.

    Оба файла используют одинаковые параметры ротации (MaxSize, MaxLogs).
    """
    log_dir = Path(log_cfg.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    app_logger = logging.getLogger(_APP_LOGGER_NAME)
    app_logger.handlers.clear()
    app_logger.setLevel(log_cfg.log_level)
    app_logger.propagate = False

    app_handler = _rotating_handler(
        log_dir / log_cfg.log_name,
        log_cfg.max_size_bytes,
        log_cfg.max_logs,
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ),
    )
    app_logger.addHandler(app_handler)

    nmea_row_logger: logging.Logger | None = None
    if log_cfg.log_row_nmea:
        nmea_row_logger = logging.getLogger(_NMEA_ROW_LOGGER_NAME)
        nmea_row_logger.handlers.clear()
        nmea_row_logger.setLevel(logging.INFO)
        nmea_row_logger.propagate = False
        row_handler = _rotating_handler(
            log_dir / log_cfg.row_nmea_name,
            log_cfg.max_size_bytes,
            log_cfg.max_logs,
            logging.Formatter("%(message)s"),
        )
        nmea_row_logger.addHandler(row_handler)

    return app_logger, nmea_row_logger
