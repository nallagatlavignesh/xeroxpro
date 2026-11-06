"""One copy of the program at a time (two copies would confuse the owner, and SQLite allows one writer anyway)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile


def acquire(path: Path | str) -> QLockFile | None:
    """The held lock, or None if another copy is already running. A copy that crashed does not block the next start."""
    lock = QLockFile(str(path))
    lock.setStaleLockTime(0)  # only the owning process being alive keeps the lock; no time-based expiry
    return lock if lock.tryLock(0) else None
