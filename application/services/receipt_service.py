"""Builds the data a receipt needs from stored records (never from the live screen)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from application.services import bill_queries
from business.timeutil import to_ist
from database.models import ShopSettings
from infrastructure.pdf.receipt import ReceiptData, ReceiptLine


def build_receipt_data(session: Session, bill_id: int) -> ReceiptData:
    shop = session.get(ShopSettings, 1)
    d = bill_queries.get_bill_detail(session, bill_id)
    s = d.summary
    collected = [(p.method, p.amount) for p in d.payments if p.kind == "payment"]
    # For a cancelled bill the stored totals are zeroed; show what the bill was for.
    cancelled = s.status in ("cancelled", "refunded")
    return ReceiptData(
        shop_name=shop.shop_name, address=shop.address, phone=shop.phone if shop.receipt_show_phone else "",
        footer=shop.receipt_footer, bill_number=s.bill_number, created_at=to_ist(d.created_at),
        customer_name=s.customer_name,
        lines=[ReceiptLine(i.description, i.quantity, i.unit, i.unit_rate, i.amount) for i in d.items],
        subtotal=d.subtotal, discount=d.discount, grand_total=s.grand_total,
        total_paid=sum(a for _, a in collected) if cancelled else s.total_paid,
        outstanding=0 if cancelled else s.outstanding, payments=collected, status=s.status)
