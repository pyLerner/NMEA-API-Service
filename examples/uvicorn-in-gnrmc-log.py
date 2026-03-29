import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from gnrmc_utils import setup_logger

# --- Логгер ---
log_file = Path("logs/gnrmc.log")
logger = setup_logger(log_file)

# Переназначаем uvicorn-логгеры на наш хендлер
uvicorn_logger = logging.getLogger("uvicorn")
uvicorn_logger.handlers = logger.handlers
uvicorn_logger.setLevel(logger.level)

logging.getLogger("uvicorn.error").handlers = logger.handlers
logging.getLogger("uvicorn.access").handlers = logger.handlers

# Переназначаем fastapi-логгер
logging.getLogger("fastapi").handlers = logger.handlers
logging.getLogger("fastapi").setLevel(logger.level)

# --- FastAPI приложение ---
app = FastAPI()


@app.get("/")
async def root():
    logger.info("Обработан запрос /")
    return {"message": "Hello World"}


if __name__ == "__main__":
    logger.info("Запуск API на 0.0.0.0:7000")
    uvicorn.run(app, host="0.0.0.0", port=7000, log_level="info")
