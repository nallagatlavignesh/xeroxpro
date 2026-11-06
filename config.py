"""Paths and constants. No Qt imports here so business/tests can use it."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "XeroxPro"
APP_VERSION = "0.1.0"


def data_dir() -> Path:
    """Per-user data folder (never beside the exe). XEROXPRO_DATA_DIR overrides it for tests/dev."""
    override = os.environ.get("XEROXPRO_DATA_DIR")
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    else:
        base = Path.home() / ".local" / "share" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "xeroxpro.db"


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_backup_dir() -> Path:
    """Outside the data dir on purpose, so one folder mishap doesn't take DB and backups together."""
    if os.environ.get("XEROXPRO_DATA_DIR"):
        return data_dir().parent / (data_dir().name + "-backups")
    return Path.home() / "Documents" / f"{APP_NAME} Backups"


def resource_path(*parts: str) -> Path:
    """Works from source and from a PyInstaller bundle (sys._MEIPASS)."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root.joinpath("resources", *parts)
