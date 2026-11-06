from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from business.errors import DomainError

Tr = Callable[..., str]


def message_for(error: DomainError, tr: Tr) -> str:
    """Translate a domain error; a `field_key` param is itself a key to translate."""
    params = dict(error.params)
    if "field_key" in params:
        params["field"] = tr(params.pop("field_key"))
    return tr(error.key, **params)


def amp(text: str) -> str:
    """Qt buttons/tabs treat & as a shortcut marker; double it to show a literal &."""
    return text.replace("&", "&&")


def parse_money(text: str) -> int:
    """'12.50' / '₹1,200' -> paise; blank -> 0. Raises ValidationError('rates.invalid') for anything else."""
    from business.errors import ValidationError
    from business.money import to_paise

    text = text.strip().replace("₹", "").replace(",", "")
    try:
        return to_paise(text) if text else 0
    except (ValueError, TypeError):
        raise ValidationError("rates.invalid") from None


def show_domain_error(parent: QWidget, error: DomainError, tr: Tr) -> None:
    QMessageBox.warning(parent, tr("common.error"), message_for(error, tr))


def request_pin(parent: QWidget, session_factory, tr: Tr) -> tuple[bool, str | None]:
    """(proceed, pin). If no owner PIN is configured nothing is asked."""
    from application.services import auth_service
    from database.connection import session_scope

    with session_scope(session_factory) as s:
        if not auth_service.has_pin(s):
            return True, None
    text, ok = QInputDialog.getText(parent, tr("auth.enter_pin"), tr("auth.enter_pin"), QLineEdit.EchoMode.Password)
    return ok, text or None


class Page(QWidget):
    """Base for sidebar pages. Subclasses override retranslate() to refresh every visible string."""

    def __init__(self, title_key: str, tr: Tr) -> None:
        super().__init__()
        self._tr = tr
        self._title_key = title_key
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(28, 24, 28, 24)
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.layout_.addWidget(self.title)

    def retranslate(self) -> None:
        self.title.setText(self._tr(self._title_key))

    def on_show(self) -> None:
        """Called each time the page is opened from the sidebar, so it can reload fresh data."""


class PlaceholderPage(Page):
    """Honest stand-in for a module built in a later phase: no buttons, just a notice."""

    def __init__(self, title_key: str, tr: Tr) -> None:
        super().__init__(title_key, tr)
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.layout_.addWidget(self.hint)
        self.layout_.addStretch(1)
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        self.hint.setText(self._tr("page.coming_soon"))
        self.hint.setAlignment(Qt.AlignmentFlag.AlignLeft)
