"""Domain errors. `key` is a translation key so the UI can show the message in the active language."""
from __future__ import annotations


class DomainError(Exception):
    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


class ValidationError(DomainError):
    pass


class AuthorizationError(DomainError):
    """Owner PIN missing or wrong."""


class StockError(DomainError):
    pass
