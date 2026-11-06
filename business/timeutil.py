"""Timestamps are stored as UTC ISO text and shown in IST (fixed +05:30, India has no DST)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
_FMT = "%Y-%m-%dT%H:%M:%S"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime(_FMT)


def to_ist(utc_iso: str) -> datetime:
    return datetime.strptime(utc_iso, _FMT).replace(tzinfo=timezone.utc).astimezone(IST)


def ist_today() -> date:
    return datetime.now(IST).date()
