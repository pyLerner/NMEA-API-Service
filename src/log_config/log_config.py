import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


# --- ЛОГИРОВАНИЕ ---
def setup_logger(log_file: str | Path) -> logging.Logger:
    """Создаёт и настраивает логгер с ротацией логов."""
    if isinstance(log_file, str):
        log_path = Path(log_file)
    elif isinstance(log_file, Path):
        log_path = log_file

    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(str(Path(__file__).stem))
    logger.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    # console_handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    # console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    # logger.addHandler(console_handler)
    return logger
