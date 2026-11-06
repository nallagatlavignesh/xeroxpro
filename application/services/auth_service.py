"""Optional owner PIN (assumption A1). If no PIN is set, protected actions need only the UI confirmation."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from sqlalchemy.orm import Session

from business.errors import AuthorizationError, ValidationError
from database.models import ShopSettings

_ITERATIONS = 200_000


def _hash(pin: str, salt: bytes, iterations: int = _ITERATIONS) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, iterations)
    return f"pbkdf2${iterations}${salt.hex()}${digest.hex()}"


def _row(session: Session) -> ShopSettings:
    return session.get(ShopSettings, 1)


def has_pin(session: Session) -> bool:
    return bool(_row(session).owner_pin_hash)


def verify_pin(session: Session, pin: str | None) -> bool:
    stored = _row(session).owner_pin_hash
    if not stored:
        return True
    if not pin:
        return False
    _, iterations, salt_hex, _ = stored.split("$")
    return hmac.compare_digest(_hash(pin, bytes.fromhex(salt_hex), int(iterations)), stored)


def require_authorized(session: Session, pin: str | None) -> None:
    if not verify_pin(session, pin):
        raise AuthorizationError("auth.pin_wrong" if pin else "auth.pin_required")


def set_pin(session: Session, new_pin: str, current_pin: str | None = None) -> None:
    """Set or change the PIN (needs the current one if already set)."""
    require_authorized(session, current_pin)
    if not (new_pin.isdigit() and 4 <= len(new_pin) <= 6):
        raise ValidationError("auth.pin_format")
    _row(session).owner_pin_hash = _hash(new_pin, secrets.token_bytes(16))


def clear_pin(session: Session, current_pin: str | None) -> None:
    require_authorized(session, current_pin)
    _row(session).owner_pin_hash = None
