"""Logging setup shared by the API process and background tasks."""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
NOISY_LOGGERS = ("httpx", "httpcore", "watchdog")


def configure_logging(level: str) -> None:
    """Configure the root logger and quiet chatty third party loggers."""
    logging.basicConfig(level=level.upper(), format=LOG_FORMAT, force=True)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)