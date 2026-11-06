from decimal import Decimal

import pytest

from business.money import format_inr, line_amount, to_paise


def test_to_paise():
    assert to_paise("2") == 200
    assert to_paise("12.50") == 1250
    assert to_paise(Decimal("0.05")) == 5


@pytest.mark.parametrize("bad", ["1.005", "abc"])
def test_to_paise_rejects(bad):
    with pytest.raises(ValueError):
        to_paise(bad)


def test_to_paise_rejects_float():
    with pytest.raises(TypeError):
        to_paise(2.5)


def test_line_amount_spec_examples():
    assert line_amount(Decimal(25 * 2), 200) == 10000  # 25 pages x 2 copies x Rs2 = Rs100
    assert line_amount(Decimal(10), 2000) == 20000  # 10 laminations x Rs20 = Rs200


def test_line_amount_rounds_half_up():
    assert line_amount(Decimal("0.5"), 5) == 3  # 2.5 paise -> 3
    assert line_amount(Decimal("1.5"), 1) == 2


@pytest.mark.parametrize("paise, text", [
    (0, "₹0.00"), (5, "₹0.05"), (99999, "₹999.99"), (100000, "₹1,000.00"),
    (12345678, "₹1,23,456.78"), (1000000000, "₹1,00,00,000.00"), (-250, "-₹2.50"),
])
def test_format_inr(paise, text):
    assert format_inr(paise) == text
