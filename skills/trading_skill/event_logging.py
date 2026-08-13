from __future__ import annotations

import json
import logging

_LOGGER_NAME = "angelique.trading"


def get_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def log_event(level: int, event: str, **data) -> None:
    logger = get_logger()
    payload = {"event": event, **data}
    logger.log(level, json.dumps(payload, default=str, sort_keys=True))
