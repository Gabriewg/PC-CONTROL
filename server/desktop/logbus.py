# SPDX-License-Identifier: AGPL-3.0-or-later
"""Log do servidor: arquivo rotativo + painel de atividade da janela."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "[%(asctime)s] %(message)s"
LOG_DATEFMT = "%H:%M:%S"


class QueueHandler(logging.Handler):
    """Manda cada linha formatada para um callback (a janela)."""

    def __init__(self, sink) -> None:
        super().__init__()
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._sink(self.format(record))
        except Exception:  # noqa: BLE001
            pass


def setup(log_path: Path, sink) -> logging.Logger:
    logger = logging.getLogger("localcontrol")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001
            pass

    formatter = logging.Formatter(LOG_FORMAT, LOG_DATEFMT)

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        pass

    gui_handler = QueueHandler(sink)
    gui_handler.setFormatter(formatter)
    logger.addHandler(gui_handler)
    return logger
