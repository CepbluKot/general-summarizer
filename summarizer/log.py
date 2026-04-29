"""Настройка логирования для general-summarizer."""
from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup(log_file: str | None = None, level: int = logging.DEBUG) -> None:
    """Настраивает root logger.

    Args:
        log_file: Путь к файлу лога. None = только stderr.
        level:    Уровень логирования (default DEBUG).
    """
    fmt = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)
    root.addHandler(stderr_handler)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"summarizer.{name}")
