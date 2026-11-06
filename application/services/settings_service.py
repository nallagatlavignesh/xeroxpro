"""Shop settings use cases. Validation lives here, not in the UI."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from application.services.i18n import LANGUAGES
from business.billing import PAYMENT_METHODS
from business.errors import ValidationError
from database.models import ShopSettings

_EDITABLE = ("shop_name", "address", "phone", "email", "receipt_footer", "preferred_language",
             "default_payment_method", "bill_prefix", "receipt_show_phone")


def get_shop_settings(session: Session) -> ShopSettings:
    return session.get(ShopSettings, 1)


def update_shop_settings(session: Session, **changes: str | bool | None) -> ShopSettings:
    unknown = set(changes) - set(_EDITABLE)
    if unknown:
        raise ValueError(f"not editable: {sorted(unknown)}")
    if "shop_name" in changes and not (changes["shop_name"] or "").strip():
        raise ValidationError("validation.required", field_key="settings.shop_name")
    if "preferred_language" in changes and changes["preferred_language"] not in LANGUAGES:
        raise ValidationError("validation.bad_language")
    if "default_payment_method" in changes and changes["default_payment_method"] not in PAYMENT_METHODS:
        raise ValidationError("bill.payment_method_invalid")
    if "bill_prefix" in changes:
        prefix = (changes["bill_prefix"] or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9-]{0,10}", prefix):
            raise ValidationError("settings.bad_prefix")
        changes["bill_prefix"] = prefix
    row = get_shop_settings(session)
    for name, value in changes.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(row, name, (value or None) if name == "email" else value if isinstance(value, bool) else (value or ""))
    return row
