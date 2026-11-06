from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import config


def setup_logging() -> None:
    handler = RotatingFileHandler(config.log_dir() / "xeroxpro.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
