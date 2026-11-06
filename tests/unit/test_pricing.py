import pytest

from business.errors import ValidationError
from business.pricing import estimate_print, parse_page_ranges, sheets_for


@pytest.mark.parametrize("spec, pages, expected", [
    ("", 5, [1, 2, 3, 4, 5]), ("  ", 3, [1, 2, 3]), ("2", 5, [2]), ("1-3", 5, [1, 2, 3]),
    ("1-3, 5", 5, [1, 2, 3, 5]), ("5,1,3-4", 5, [1, 3, 4, 5]), ("2-4,3-5", 5, [2, 3, 4, 5]), ("3 - 4", 5, [3, 4]),
])
def test_page_ranges(spec, pages, expected):
    assert parse_page_ranges(spec, pages) == expected


@pytest.mark.parametrize("spec, key", [
    ("0", "print.range_invalid"), ("3-1", "print.range_invalid"), ("a", "print.range_invalid"),
    ("1,,2", "print.range_invalid"), ("-3", "print.range_invalid"), ("1-", "print.range_invalid"),
    ("6", "print.range_out_of_bounds"), ("1-9", "print.range_out_of_bounds"),
])
def test_bad_page_ranges(spec, key):
    with pytest.raises(ValidationError) as e:
        parse_page_ranges(spec, 5)
    assert e.value.key == key


@pytest.mark.parametrize("pages, duplex, sheets", [(1, False, 1), (1, True, 1), (2, True, 1), (3, True, 2),
                                                  (10, True, 5), (11, True, 6), (11, False, 11)])
def test_sheets_vs_pages(pages, duplex, sheets):
    assert sheets_for(pages, duplex) == sheets


def test_single_sided_cost_per_page():
    e = estimate_print(25, 2, False, 200, "page")  # 25 pages x 2 copies x Rs2
    assert (e.total_pages, e.total_sheets, e.cost) == (50, 50, 10000)
    assert (e.quantity_per_copy, e.copies) == (25, 2)


def test_double_sided_per_page_billing_charges_every_side():
    e = estimate_print(25, 2, True, 200, "page")
    assert (e.sheets_per_copy, e.total_sheets, e.total_pages, e.cost) == (13, 26, 50, 10000)


def test_double_sided_per_sheet_billing_charges_physical_sheets():
    e = estimate_print(25, 2, True, 300, "sheet")  # 13 sheets per copy x 2 copies x Rs3
    assert (e.total_sheets, e.quantity_per_copy, e.cost) == (26, 13, 7800)
    single = estimate_print(25, 2, False, 300, "sheet")
    assert single.cost == 15000 and e.cost < single.cost


def test_copies_never_share_a_sheet():
    assert estimate_print(3, 2, True, 100, "sheet").total_sheets == 4  # not ceil(6/2)=3


def test_manual_page_override_is_just_a_different_page_count():
    assert estimate_print(7, 1, False, 200, "page").cost == 1400  # owner typed 7 although the selection had 10


@pytest.mark.parametrize("pages, copies, rate", [(0, 1, 100), (-1, 1, 100), (1, 0, 100), (1, 1, -5), (1, 1, 2.5)])
def test_estimate_rejects_bad_input(pages, copies, rate):
    with pytest.raises(ValidationError):
        estimate_print(pages, copies, False, rate, "page")
