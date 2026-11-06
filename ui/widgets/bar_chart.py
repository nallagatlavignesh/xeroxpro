"""Minimal bar chart (QPainter) - enough for the weekly and monthly sales views, no extra dependency."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from business.money import format_inr


class BarChart(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(190)
        self._labels: list[str] = []
        self._values: list[int] = []  # paise

    def set_data(self, labels: list[str], values: list[int]) -> None:
        self._labels, self._values = labels, values
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPointSize(8)
        p.setFont(font)
        w, h = self.width(), self.height()
        left, top, bottom = 8, 38, 22
        n = len(self._values)
        peak = max(self._values, default=0)
        p.setPen(QColor("#6B7280"))
        p.drawText(QRectF(left, 0, w - left, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"max {format_inr(peak)}" if peak else "")
        p.setPen(QPen(QColor("#D5E2E1"), 1))
        p.drawLine(left, h - bottom, w - left, h - bottom)
        if not n:
            return
        slot = (w - 2 * left) / n
        bar_w = slot * 0.62
        plot_h = h - top - bottom
        step = max(1, round(n / 8))  # thin out x labels on the monthly chart
        for i, value in enumerate(self._values):
            bar_h = plot_h * value / peak if peak else 0
            x = left + i * slot + (slot - bar_w) / 2
            p.fillRect(QRectF(x, h - bottom - bar_h, bar_w, bar_h), QColor("#0F766E"))
            if i % step == 0:
                p.setPen(QColor("#4B5563"))
                p.drawText(QRectF(left + i * slot - 6, h - bottom + 2, slot + 12, bottom - 2),
                           Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._labels[i])
            if n <= 8 and value:
                p.setPen(QColor("#1F2937"))
                p.drawText(QRectF(left + i * slot - 14, h - bottom - bar_h - 16, slot + 28, 14),
                           Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, format_inr(value, False))
