from decimal import Decimal

import pytest

from business.billing import LineInput, PaymentInput, compute_totals, discount_from_percent
from business.errors import ValidationError

D = Decimal


def test_25_pages_x_2_copies_x_rs2_is_rs100():
    t = compute_totals([LineInput(D(25), 200, copies=2)])
    assert (t.subtotal, t.grand_total) == (10000, 10000)


def test_10_laminations_at_rs20_is_rs200():
    assert compute_totals([LineInput(D(10), 2000)]).grand_total == 20000


def test_multiple_items_add_up():
    t = compute_totals([LineInput(D(25), 200, 2), LineInput(D(10), 2000), LineInput(D("2.5"), 1000)])
    assert t.subtotal == 10000 + 20000 + 2500


def test_discount_amount_and_percent():
    t = compute_totals([LineInput(D(100), 200)], discount=500)
    assert (t.subtotal, t.discount, t.grand_total) == (20000, 500, 19500)
    assert discount_from_percent(20000, D(10)) == 2000
    assert discount_from_percent(999, D("10")) == 100  # 99.9 rounds half-up


@pytest.mark.parametrize("discount", [-1, 20001])
def test_bad_discount_rejected(discount):
    with pytest.raises(ValidationError) as e:
        compute_totals([LineInput(D(100), 200)], discount=discount)
    assert e.value.key == "bill.discount_invalid"


def test_partial_payment_leaves_outstanding():
    t = compute_totals([LineInput(D(50), 200)], payments=[PaymentInput(6000, "cash")])
    assert (t.total_paid, t.outstanding, t.status) == (6000, 4000, "partial")


def test_status_unpaid_and_paid():
    assert compute_totals([LineInput(D(1), 200)]).status == "unpaid"
    assert compute_totals([LineInput(D(1), 200)], payments=[PaymentInput(200, "upi")]).status == "paid"


def test_split_payment_across_methods():
    t = compute_totals([LineInput(D(1), 1000)], payments=[PaymentInput(400, "cash"), PaymentInput(600, "upi")])
    assert (t.outstanding, t.status) == (0, "paid")


@pytest.mark.parametrize("qty", [D(0), D(-1), D("-0.5")])
def test_zero_or_negative_quantity_rejected(qty):
    with pytest.raises(ValidationError) as e:
        compute_totals([LineInput(qty, 200)])
    assert e.value.key == "bill.quantity_positive"


@pytest.mark.parametrize("rate", [-1, -200])
def test_negative_rate_rejected(rate):
    with pytest.raises(ValidationError) as e:
        compute_totals([LineInput(D(1), rate)])
    assert e.value.key == "bill.rate_invalid"


def test_float_rate_and_bad_copies_rejected():
    with pytest.raises(ValidationError):
        compute_totals([LineInput(D(1), 2.5)])
    with pytest.raises(ValidationError):
        compute_totals([LineInput(D(1), 200, copies=0)])


def test_overpayment_bad_method_and_empty_bill_rejected():
    line = [LineInput(D(1), 200)]
    with pytest.raises(ValidationError) as e:
        compute_totals(line, payments=[PaymentInput(201, "cash")])
    assert e.value.key == "bill.overpayment"
    with pytest.raises(ValidationError):
        compute_totals(line, payments=[PaymentInput(100, "cheque")])
    with pytest.raises(ValidationError):
        compute_totals(line, payments=[PaymentInput(0, "cash")])
    with pytest.raises(ValidationError) as e:
        compute_totals([])
    assert e.value.key == "bill.no_lines"
