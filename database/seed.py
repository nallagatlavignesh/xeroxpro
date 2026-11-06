"""First-run data: placeholder shop settings, service *names* (no rates) and pick-lists. No transactions."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import LookupValue, Service, ShopSettings

SERVICES = [  # name, category, billing unit, kind
    ("Xerox / Photocopy", "Copying", "page", "service"),
    ("B&W Printing", "Printing", "page", "service"),
    ("Colour Printing", "Printing", "page", "service"),
    ("Lamination", "Finishing", "item", "service"),
    ("Spiral Binding", "Finishing", "item", "service"),
    ("Scanning", "Scanning", "page", "service"),
    ("Online Application Assistance", "Online Services", "job", "service"),
    ("Stationery", "Stationery", "item", "stationery"),
]
LOOKUPS = {
    "unit": ["page", "copy", "sheet", "item", "set", "job"],
    "expense_category": ["Paper", "Toner and ink", "Electricity", "Machine maintenance",
                         "Stationery purchases", "Rent", "Other"],
    "application_type": ["PAN Card", "Passport", "Ration Card", "Scholarship", "Exam Registration", "Other"],
    "service_category": ["Copying", "Printing", "Finishing", "Scanning", "Online Services", "Stationery"],
}


def seed_if_empty(session: Session) -> bool:
    """Returns True if it seeded. Safe to call on every start."""
    if session.scalar(select(ShopSettings.id)) is not None:
        return False
    session.add(ShopSettings(id=1, shop_name="XeroxPro"))
    for name, category, unit, kind in SERVICES:
        session.add(Service(service_name=name, category=category, billing_unit=unit, kind=kind))
    for kind, values in LOOKUPS.items():
        session.add_all(LookupValue(kind=kind, value=v, sort_order=i) for i, v in enumerate(values))
    return True
