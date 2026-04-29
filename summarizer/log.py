"""Настройка логирования для general-summarizer."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

FMT     = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

# Визуальные разделители (как в оригинале)
SEP  = "═" * 72
SEP2 = "─" * 72


def setup(log_file: str | None = None, level: int = logging.DEBUG) -> None:
    fmt = logging.Formatter(FMT, datefmt=DATEFMT)

    root = logging.getLogger("summarizer")
    root.setLevel(level)
    root.handlers.clear()

    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(fmt)
    root.addHandler(h)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

    # Заглушаем шумные внешние библиотеки
    for noisy in ("httpcore", "httpx", "openai", "instructor", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"summarizer.{name}")
