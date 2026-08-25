import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.paths import LOGS_DIR


LOGGER_NAME = "car_deal_finder"
LOG_FILE = LOGS_DIR / "car_deal_finder.log"


def configure_logging(log_file: str | Path = LOG_FILE) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    destination = Path(log_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    rotating_file = RotatingFileHandler(
        destination,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    rotating_file.setFormatter(formatter)

    logger.addHandler(console)
    logger.addHandler(rotating_file)
    return logger


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{component}")
