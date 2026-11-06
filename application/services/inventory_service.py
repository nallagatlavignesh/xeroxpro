"""Stationery stock. product.stock_quantity always equals the sum of its inventory_transactions.

Sales and cancellations are written by the billing use cases; this module covers everything else.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from application.services import auth_service
from business.errors import StockError, ValidationError
from business.money import line_amount
from business.timeutil import ist_today, utc_now_iso
from database.models import AuditLog, InventoryTransaction, Product


@dataclass(frozen=True)
class StockRow:
    id: int
    name: str
    category: str
    unit: str
    stock: Decimal
    minimum: Decimal
    purchase_price: int
    selling_price: int
    value: int  # stock x purchase price, paise
    low: bool
    active: bool


def _name_prices(name: str, purchase: int, selling: int, minimum: Decimal) -> str:
    name = name.strip()
    if not name:
        raise ValidationError("validation.required", field_key="inventory.name")
    if purchase < 0 or selling < 0:
        raise ValidationError("bill.rate_invalid")
    if minimum < 0:
        raise ValidationError("inventory.minimum_invalid")
    return name


def create_product(session: Session, name: str, category: str, unit: str, purchase_price: int, selling_price: int,
                   minimum_stock: Decimal = Decimal(0)) -> Product:
    name = _name_prices(name, purchase_price, selling_price, minimum_stock)
    if session.scalar(select(Product.id).where(Product.product_name == name)):
        raise ValidationError("inventory.duplicate_name")
    product = Product(product_name=name, category=category.strip(), unit=unit.strip() or "item",
                      purchase_price=purchase_price, selling_price=selling_price, minimum_stock=minimum_stock,
                      stock_quantity=Decimal(0))
    session.add(product)
    session.flush()
    return product


def update_product(session: Session, product_id: int, name: str, category: str, unit: str, purchase_price: int,
                   selling_price: int, minimum_stock: Decimal, is_active: bool = True) -> Product:
    """Stock itself is never edited here, only through purchases, returns and adjustments."""
    name = _name_prices(name, purchase_price, selling_price, minimum_stock)
    product = session.get(Product, product_id)
    clash = session.scalar(select(Product.id).where(Product.product_name == name))
    if product is None or (clash is not None and clash != product_id):
        raise ValidationError("inventory.duplicate_name")
    product.product_name, product.category, product.unit = name, category.strip(), unit.strip() or "item"
    product.purchase_price, product.selling_price = purchase_price, selling_price
    product.minimum_stock, product.is_active = minimum_stock, is_active
    return product


def _move(session: Session, product_id: int, kind: str, qty: Decimal, unit_cost: int, notes: str,
          clock: Callable[[], str]) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise ValidationError("inventory.unknown_product")
    product.stock_quantity = product.stock_quantity + qty
    session.add(InventoryTransaction(product_id=product.id, transaction_type=kind, quantity=qty, unit_cost=unit_cost,
                                     transaction_date=ist_today().isoformat(), notes=notes.strip()))
    return product


def purchase(session: Session, product_id: int, quantity: Decimal, unit_cost: int, notes: str = "",
             clock: Callable[[], str] = utc_now_iso) -> Product:
    """Stock bought for resale. The product's purchase price becomes this cost (used for profit at sale time)."""
    if quantity <= 0:
        raise ValidationError("bill.quantity_positive")
    if unit_cost < 0:
        raise ValidationError("bill.rate_invalid")
    product = _move(session, product_id, "purchase", quantity, unit_cost, notes, clock)
    product.purchase_price = unit_cost
    return product


def customer_return(session: Session, product_id: int, quantity: Decimal, notes: str = "",
                    clock: Callable[[], str] = utc_now_iso) -> Product:
    """Goods brought back by a customer go back on the shelf."""
    if quantity <= 0:
        raise ValidationError("bill.quantity_positive")
    product = session.get(Product, product_id)
    return _move(session, product_id, "return", quantity, product.purchase_price if product else 0, notes, clock)


def adjust(session: Session, product_id: int, delta: Decimal, reason: str, allow_negative: bool = False,
           pin: str | None = None, clock: Callable[[], str] = utc_now_iso) -> Product:
    """Correct the count (e.g. after a stock take). Always audited. Going below zero needs allow_negative AND the PIN."""
    reason = reason.strip()
    if not reason:
        raise ValidationError("validation.required", field_key="bill.cancel_reason")
    if delta == 0:
        raise ValidationError("bill.quantity_positive")
    product = session.get(Product, product_id)
    if product is None:
        raise ValidationError("inventory.unknown_product")
    if product.stock_quantity + delta < 0:
        if not allow_negative:
            raise StockError("inventory.negative_blocked", name=product.product_name)
        auth_service.require_authorized(session, pin)
    before = product.stock_quantity
    _move(session, product_id, "adjustment", delta, product.purchase_price, reason, clock)
    session.add(AuditLog(action="stock_adjusted", entity_type="product", entity_id=product.id, at=clock(), reason=reason,
                         details=json.dumps({"before": str(before), "after": str(product.stock_quantity),
                                             "delta": str(delta)})))
    return product


def list_stock(session: Session, text: str = "", low_only: bool = False, include_inactive: bool = False) -> list[StockRow]:
    query = select(Product).order_by(Product.product_name)
    if not include_inactive:
        query = query.where(Product.is_active.is_(True))
    if text.strip():
        query = query.where(Product.product_name.like(f"%{text.strip()}%"))
    rows = [StockRow(p.id, p.product_name, p.category, p.unit, p.stock_quantity, p.minimum_stock, p.purchase_price,
                     p.selling_price, line_amount(p.stock_quantity, p.purchase_price) if p.stock_quantity > 0 else 0,
                     p.stock_quantity <= p.minimum_stock, p.is_active) for p in session.scalars(query)]
    return [r for r in rows if r.low] if low_only else rows


def stock_value(session: Session) -> int:
    return sum(r.value for r in list_stock(session))


def history(session: Session, product_id: int) -> list[InventoryTransaction]:
    return list(session.scalars(select(InventoryTransaction).where(InventoryTransaction.product_id == product_id)
                                .order_by(InventoryTransaction.id.desc())))


def ledger_total(session: Session, product_id: int) -> Decimal:
    """Sum of all movements; must equal product.stock_quantity (checked by tests)."""
    total = session.scalar(select(func.coalesce(func.sum(InventoryTransaction.quantity), 0))
                           .where(InventoryTransaction.product_id == product_id))
    return Decimal(total)
