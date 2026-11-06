"""Reading PDFs for the print assistant (PyMuPDF)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PySide6.QtGui import QImage

from business.errors import DomainError

_PAPERS = {"A3": (297, 420), "A4": (210, 297), "A5": (148, 210), "Letter": (216, 279), "Legal": (216, 356)}
_MM = 25.4 / 72


class PdfError(DomainError):
    pass


@dataclass(frozen=True)
class PdfInfo:
    path: str
    page_count: int
    page_sizes_mm: list[tuple[float, float]]  # (width, height) of every page

    @property
    def paper_names(self) -> list[str]:
        return [paper_name(w, h) for w, h in self.page_sizes_mm]

    @property
    def mixed_sizes(self) -> bool:
        return len(set(self.paper_names)) > 1


def paper_name(width_mm: float, height_mm: float, tolerance: float = 3.0) -> str:
    """'A4', 'Letter', ... (either orientation) or e.g. '120x200 mm' when it is not a standard size."""
    short, long_ = sorted((width_mm, height_mm))
    for name, (w, h) in _PAPERS.items():
        if abs(short - w) <= tolerance and abs(long_ - h) <= tolerance:
            return name
    return f"{short:.0f}x{long_:.0f} mm"


def read_pdf(path: str | Path) -> PdfInfo:
    try:
        doc = pymupdf.open(path)
    except Exception:  # PyMuPDF raises several types for missing/corrupt files
        raise PdfError("print.pdf_unreadable") from None
    try:
        if doc.needs_pass:
            raise PdfError("print.pdf_encrypted")
        if not doc.is_pdf or doc.page_count < 1:
            raise PdfError("print.pdf_unreadable")
        return PdfInfo(str(path), doc.page_count,
                       [(p.rect.width * _MM, p.rect.height * _MM) for p in doc])
    finally:
        doc.close()


def render_page(path: str | Path, page_number: int, dpi: int) -> QImage:
    """Render one page (1-based) to an RGB image."""
    doc = pymupdf.open(path)
    try:
        pix = doc[page_number - 1].get_pixmap(dpi=dpi, alpha=False)
        return QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
    finally:
        doc.close()
