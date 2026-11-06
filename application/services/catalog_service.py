"""Services and their append-only rate history."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from business.errors import ValidationError
from business.timeutil import utc_now_iso
from database.models import LookupValue, Product, Service, ServiceRate


@dataclass(frozen=True)
class ServiceRow:
    id: int
    name: str
    category: str
    unit: str
    kind: str
    is_active: bool
    rate: int | None  # paise; None = no rate set yet


def current_rate(session: Session, service_id: int, at: str | None = None) -> int | None:
    """Latest rate whose effective_from <= `at` (default now); None if none has been set."""
    return session.scalar(
        select(ServiceRate.rate)
        .where(ServiceRate.service_id == service_id, ServiceRate.effective_from <= (at or utc_now_iso()))
        .order_by(ServiceRate.effective_from.desc())
        .limit(1)
    )


def set_rate(session: Session, service_id: int, rate: int, clock: Callable[[], str] = utc_now_iso) -> None:
    """Add a new rate effective now. Old bills are unaffected: each bill item stores its own rate."""
    if not isinstance(rate, int) or isinstance(rate, bool) or rate < 0:
        raise ValidationError("bill.rate_invalid")
    if session.get(Service, service_id) is None:
        raise ValidationError("catalog.unknown_service")
    now = clock()
    existing = session.scalar(select(ServiceRate).where(
        ServiceRate.service_id == service_id, ServiceRate.effective_from == now))
    if existing:  # shortcut: two edits in the same second overwrite each other, fine for a human
        existing.rate = rate
    else:
        session.add(ServiceRate(service_id=service_id, rate=rate, effective_from=now))


def list_services(session: Session, active_only: bool = False) -> list[ServiceRow]:
    query = select(Service).order_by(Service.id)
    if active_only:
        query = query.where(Service.is_active.is_(True))
    return [
        ServiceRow(s.id, s.service_name, s.category, s.billing_unit, s.kind, s.is_active, current_rate(session, s.id))
        for s in session.scalars(query)
    ]


def _ensure_unit(session: Session, unit: str) -> None:
    if session.scalar(select(LookupValue.id).where(LookupValue.kind == "unit", LookupValue.value == unit)) is None:
        session.add(LookupValue(kind="unit", value=unit, sort_order=999))


def save_service(session: Session, name: str, unit: str, category: str = "", is_active: bool = True,
                 service_id: int | None = None) -> Service:
    name, unit = name.strip(), unit.strip()
    if not name or not unit:
        raise ValidationError("validation.required", field_key="catalog.name" if not name else "catalog.unit")
    clash = session.scalar(select(Service.id).where(Service.service_name == name))
    if clash is not None and clash != service_id:
        raise ValidationError("catalog.duplicate_name")
    _ensure_unit(session, unit)
    if service_id is None:
        service = Service(service_name=name, billing_unit=unit, category=category.strip() or "Other")
        session.add(service)
    else:
        service = session.get(Service, service_id)
        service.service_name, service.billing_unit = name, unit
        if category.strip():
            service.category = category.strip()
    service.is_active = is_active
    session.flush()  # callers need the id of a new service
    return service


def rate_history(session: Session, service_id: int) -> list[tuple[str, int]]:
    """[(effective_from utc iso, rate paise)], newest first."""
    rows = session.execute(select(ServiceRate.effective_from, ServiceRate.rate)
                           .where(ServiceRate.service_id == service_id)
                           .order_by(ServiceRate.effective_from.desc()))
    return [(r[0], r[1]) for r in rows]


def list_sellable_products(session: Session) -> list[tuple[int, str, int, str]]:
    """(id, name, selling price paise, unit) of active products. Product management is Phase 4."""
    rows = session.execute(select(Product.id, Product.product_name, Product.selling_price, Product.unit)
                           .where(Product.is_active.is_(True)).order_by(Product.product_name))
    return [tuple(r) for r in rows]


def list_lookup(session: Session, kind: str) -> list[str]:
    """Editable pick-list values: unit, expense_category, application_type, service_category."""
    return list(session.scalars(
        select(LookupValue.value).where(LookupValue.kind == kind).order_by(LookupValue.sort_order, LookupValue.id)))


def list_units(session: Session) -> list[str]:
    return list_lookup(session, "unit")
