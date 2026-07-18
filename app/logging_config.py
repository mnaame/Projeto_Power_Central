import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAMES = ("collector", "web", "softguard", "telegram", "watchdog")


def configure_logging(app) -> None:
    log_dir = Path(app.config["LOG_DIR"])
    log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, str(app.config.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    handler = RotatingFileHandler(
        log_dir / "power_central.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(formatter)
    handler.setLevel(level)

    app.logger.setLevel(level)
    app.logger.addHandler(handler)

    for name in LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.addHandler(handler)
