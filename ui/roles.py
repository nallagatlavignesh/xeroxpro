"""Button roles for the stylesheet: 'primary' (filled), 'danger' (red outline); everything else is outlined.

One table instead of a call next to every button, so the look of a whole screen is decided in one place.
"""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget

PRIMARY, DANGER = "primary", "danger"

# page key -> {dotted attribute path from the page: role}
PAGES: dict[str, dict[str, str]] = {
    "dashboard": {"btn_bill": PRIMARY},
    "new_bill": {"new_bill.add_btn": PRIMARY, "new_bill.save_view_btn": PRIMARY, "new_bill.remove_btn": DANGER,
                 "history.open_btn": PRIMARY},
    "pdf_printing": {"print_btn": PRIMARY, "open_btn": PRIMARY},
    "job_orders": {"new_btn": PRIMARY, "pay_btn": PRIMARY},
    "customers": {"pay_btn": PRIMARY},
    "inventory": {"new_btn": PRIMARY},
    "expenses": {"add_btn": PRIMARY, "void_btn": DANGER},
    "applications": {"new_btn": PRIMARY},
    "settings": {"save_button": PRIMARY, "pin_remove_btn": DANGER, "rates.set_btn": PRIMARY,
                 "printers.save_btn": PRIMARY},
    "backup": {"now_btn": PRIMARY, "restore_btn": DANGER, "restore_file_btn": DANGER},
}


def set_role(button: QPushButton, role: str) -> None:
    button.setProperty("role", role)
    button.style().unpolish(button)
    button.style().polish(button)


def apply(widget: QWidget, mapping: dict[str, str]) -> None:
    """Set roles on `widget`'s buttons named by (dotted) attribute path."""
    for path, role in mapping.items():
        target = widget
        for part in path.split("."):
            target = getattr(target, part)
        set_role(target, role)


def apply_to_window(window) -> None:
    for key, mapping in PAGES.items():
        apply(window.pages[key], mapping)
