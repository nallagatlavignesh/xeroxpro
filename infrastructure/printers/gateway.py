"""Printer access through the operating system's drivers (Qt Print Support).

Nothing here proves paper came out: submission to the OS print queue is the most we can know.
Capabilities are whatever the driver reports; when it reports nothing the value is None ("not detected").
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from business.errors import DomainError
from infrastructure.pdf.pdf_info import render_page


class PrintError(DomainError):
    pass


@dataclass(frozen=True)
class PrinterInfoRow:
    name: str
    is_default: bool
    status: str  # ready | busy | error


@dataclass(frozen=True)
class PrinterCaps:
    colour: bool | None  # None = the driver did not say
    duplex: bool | None
    paper_sizes: tuple[str, ...]  # empty = not detected


@dataclass(frozen=True)
class PrintRequest:
    pdf_path: str
    pages: list[int]  # 1-based, already resolved from the page range
    copies: int = 1
    colour: bool = False
    duplex: bool = False
    paper: str | None = None  # e.g. "A4"


@dataclass(frozen=True)
class PrintResult:
    pages_sent: int  # page images handed to the print queue (selected pages x copies)


class PrinterGateway(Protocol):
    def list_printers(self) -> list[PrinterInfoRow]: ...
    def capabilities(self, name: str) -> PrinterCaps: ...
    def print_pdf(self, name: str, request: PrintRequest, progress: Callable[[int, int], None] | None = None) -> PrintResult: ...


def check_request(row: PrinterInfoRow | None, caps: PrinterCaps | None, request: PrintRequest) -> None:
    """Refuse jobs the printer is known not to handle. Unknown (None) capabilities are allowed through."""
    if row is None:
        raise PrintError("print.printer_missing")
    if row.status == "error":
        raise PrintError("print.printer_error")
    if request.colour and caps.colour is False:
        raise PrintError("print.no_colour")
    if request.duplex and caps.duplex is False:
        raise PrintError("print.no_duplex")
    if not request.pages or request.copies < 1:
        raise PrintError("print.submit_failed", detail="empty job")


_PAGE_IDS = {"A3": QPageSize.PageSizeId.A3, "A4": QPageSize.PageSizeId.A4, "A5": QPageSize.PageSizeId.A5,
             "Letter": QPageSize.PageSizeId.Letter, "Legal": QPageSize.PageSizeId.Legal}


def paint_pages(printer: QPrinter, request: PrintRequest, progress: Callable[[int, int], None] | None = None) -> int:
    """Draw every selected page, `copies` times in a row (collated), onto `printer`. Returns pages drawn.

    Copies are produced here rather than via the driver's copy count so the result does not depend on the driver.
    Pages are rasterised at up to 300 dpi and fitted to the printable area.
    """
    if request.paper in _PAGE_IDS:
        printer.setPageSize(QPageSize(_PAGE_IDS[request.paper]))
    printer.setColorMode(QPrinter.ColorMode.Color if request.colour else QPrinter.ColorMode.GrayScale)
    printer.setDuplex(QPrinter.DuplexMode.DuplexLongSide if request.duplex else QPrinter.DuplexMode.DuplexNone)
    printer.setCopyCount(1)
    painter = QPainter()
    if not painter.begin(printer):
        raise PrintError("print.submit_failed", detail="the printer did not accept the job")
    total = len(request.pages) * request.copies
    done = 0
    try:
        for _ in range(request.copies):
            for number in request.pages:
                image = render_page(request.pdf_path, number, min(300, max(72, printer.resolution())))
                printer.setPageOrientation(QPageLayout.Orientation.Landscape if image.width() > image.height()
                                           else QPageLayout.Orientation.Portrait)
                if done and not printer.newPage():
                    raise PrintError("print.submit_failed", detail="could not start a new page")
                area = printer.pageRect(QPrinter.Unit.DevicePixel)
                # fit inside the printable area, keeping the aspect ratio; the painter scales (no giant temp image)
                factor = min(area.width() / image.width(), area.height() / image.height())
                w, h = image.width() * factor, image.height() * factor
                painter.drawImage(QRectF(area.x() + (area.width() - w) / 2, area.y() + (area.height() - h) / 2, w, h),
                                  image)
                done += 1
                if progress:
                    progress(done, total)
    finally:
        painter.end()
    return done


class QtPrinterGateway:
    def list_printers(self) -> list[PrinterInfoRow]:
        status = {QPrinter.PrinterState.Idle: "ready", QPrinter.PrinterState.Active: "busy"}
        default = QPrinterInfo.defaultPrinterName()
        return [PrinterInfoRow(i.printerName(), i.printerName() == default, status.get(i.state(), "error"))
                for i in QPrinterInfo.availablePrinters()]

    def _info(self, name: str) -> QPrinterInfo | None:
        info = QPrinterInfo.printerInfo(name)
        return None if info.isNull() else info

    def capabilities(self, name: str) -> PrinterCaps:
        info = self._info(name)
        if info is None:
            raise PrintError("print.printer_missing")
        colour_modes, duplex_modes = info.supportedColorModes(), info.supportedDuplexModes()
        return PrinterCaps(
            colour=QPrinter.ColorMode.Color in colour_modes if colour_modes else None,
            duplex=any(m in (QPrinter.DuplexMode.DuplexLongSide, QPrinter.DuplexMode.DuplexShortSide)
                       for m in duplex_modes) if duplex_modes else None,
            paper_sizes=tuple(p.name() for p in info.supportedPageSizes()))

    def print_pdf(self, name: str, request: PrintRequest, progress=None) -> PrintResult:
        info = self._info(name)
        row = next((r for r in self.list_printers() if r.name == name), None)
        check_request(row, self.capabilities(name) if info else None, request)
        printer = QPrinter(info, QPrinter.PrinterMode.HighResolution)
        sent = paint_pages(printer, request, progress)
        if printer.printerState() == QPrinter.PrinterState.Error:
            raise PrintError("print.submit_failed", detail="the printer reported an error after submission")
        return PrintResult(sent)
