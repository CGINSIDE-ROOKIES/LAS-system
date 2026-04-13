from __future__ import annotations

import logging
import sys
from typing import Any

_LOGGER_NAME = "doc_processor.structure_analysis"


def get_logger(config: Any | None = None) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
    level_name = getattr(config, "console_log_level", "INFO") if config is not None else "INFO"
    level = getattr(logging, str(level_name).upper(), logging.INFO)
    logger.setLevel(level)
    return logger


def log_info(config: Any | None, message: str, *args: Any) -> None:
    if config is not None and getattr(config, "console_logging_enabled", True) is False:
        return
    get_logger(config).info(message, *args)


def log_warning(config: Any | None, message: str, *args: Any) -> None:
    if config is not None and getattr(config, "console_logging_enabled", True) is False:
        return
    get_logger(config).warning(message, *args)
