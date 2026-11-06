"""Several cashiers/threads saving at once, or the same click twice: numbers stay unique, nothing is duplicated."""
import threading
from decimal import Decimal

from sqlalchemy import func, select

from application.use_cases.save_bill import BillRequest, LineRequest, save_bill
from business.billing import PaymentInput
from database.connection import session_scope
from database.models import Bill, Payment


def _save(factory, ids, key, results):
    try:
        with session_scope(factory) as s:
            saved = save_bill(s, BillRequest(key, [LineRequest(Decimal(50), "page", 200, service_id=ids["Xerox / Photocopy"])],
                                             payments=[PaymentInput(10000, "cash")]), lambda: "2026-02-10T08:00:00")
            results.append((key, saved.bill_number, saved.created))
    except Exception as exc:  # collected so the test can fail with the real cause
        results.append((key, repr(exc), None))


def run_threads(factory, ids, keys):
    results = []
    threads = [threading.Thread(target=_save, args=(factory, ids, k, results)) for k in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


def test_parallel_saves_get_unique_gap_free_bill_numbers(shop):
    factory, ids = shop
    results = run_threads(factory, ids, [f"k{i}" for i in range(12)])
    assert len(results) == 12 and all(created for _, _, created in results), results
    numbers = sorted(n for _, n, _ in results)
    assert numbers == [f"2026-{i:06d}" for i in range(1, 13)]
    with session_scope(factory) as s:
        assert s.scalar(select(func.count(Bill.id))) == 12 and s.scalar(select(func.count(Payment.id))) == 12


def test_the_same_submission_arriving_many_times_creates_one_bill(shop):
    factory, ids = shop
    results = run_threads(factory, ids, ["same-click"] * 8)
    assert all(not isinstance(n, str) or n.startswith("2026-") for _, n, _ in results), results
    assert sum(1 for _, _, created in results if created) == 1  # exactly one real save, the rest got the same bill
    assert len({n for _, n, _ in results}) == 1
    with session_scope(factory) as s:
        assert s.scalar(select(func.count(Bill.id))) == 1 and s.scalar(select(func.count(Payment.id))) == 1
