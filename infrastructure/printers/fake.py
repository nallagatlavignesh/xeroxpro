"""In-memory printers for tests and development on machines without printers."""
from __future__ import annotations

from infrastructure.printers.gateway import (
    PrintError, PrinterCaps, PrinterInfoRow, PrintRequest, PrintResult, check_request,
)


class FakePrinterGateway:
    def __init__(self, printers: dict[str, tuple[str, PrinterCaps]] | None = None, default: str | None = None) -> None:
        """printers: name -> (status, caps)."""
        self.printers = printers if printers is not None else {
            "Office Laser": ("ready", PrinterCaps(colour=False, duplex=True, paper_sizes=("A4", "A5", "Letter"))),
            "Colour Inkjet": ("ready", PrinterCaps(colour=True, duplex=False, paper_sizes=("A4", "A3"))),
        }
        self.default = default or next(iter(self.printers), None)
        self.jobs: list[tuple[str, PrintRequest]] = []
        self.fail_with: str | None = None  # simulate a spooler failure after the checks pass

    def list_printers(self) -> list[PrinterInfoRow]:
        return [PrinterInfoRow(n, n == self.default, s) for n, (s, _) in self.printers.items()]

    def capabilities(self, name: str) -> PrinterCaps:
        if name not in self.printers:
            raise PrintError("print.printer_missing")
        return self.printers[name][1]

    def print_pdf(self, name: str, request: PrintRequest, progress=None) -> PrintResult:
        row = next((r for r in self.list_printers() if r.name == name), None)
        check_request(row, self.printers[name][1] if row else None, request)
        if self.fail_with:
            raise PrintError("print.submit_failed", detail=self.fail_with)
        self.jobs.append((name, request))
        return PrintResult(len(request.pages) * request.copies)
