"""Dev tool: draw the application icon (teal rounded square with a white document and X).

    QT_QPA_PLATFORM=offscreen python tools/make_icon.py
"""
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen

app = QGuiApplication(sys.argv)
size = 256
img = QImage(size, size, QImage.Format.Format_ARGB32)
img.fill(Qt.GlobalColor.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
p.setBrush(QColor("#0F766E"))
p.setPen(Qt.PenStyle.NoPen)
p.drawRoundedRect(QRectF(8, 8, 240, 240), 52, 52)
page = QPainterPath()  # a sheet of paper with a folded corner
page.moveTo(78, 52); page.lineTo(150, 52); page.lineTo(184, 86); page.lineTo(184, 204); page.lineTo(78, 204); page.closeSubpath()
p.setBrush(QColor("white"))
p.drawPath(page)
p.setBrush(QColor("#B7DAD6"))
fold = QPainterPath()
fold.moveTo(150, 52); fold.lineTo(150, 86); fold.lineTo(184, 86); fold.closeSubpath()
p.drawPath(fold)
p.setPen(QPen(QColor("#0F766E"), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
p.drawLine(QPointF(100, 118), QPointF(162, 180))
p.drawLine(QPointF(162, 118), QPointF(100, 180))
p.end()
out = Path(__file__).resolve().parent.parent / "resources" / "icons"
img.save(str(out / "xeroxpro.png"))
img.save(str(out / "xeroxpro.ico"))
print("wrote", out)

# small dropdown chevron used by the stylesheet (PNG: needs no SVG plugin in the packaged app)
chev = QImage(24, 24, QImage.Format.Format_ARGB32)
chev.fill(Qt.GlobalColor.transparent)
q = QPainter(chev)
q.setRenderHint(QPainter.RenderHint.Antialiasing)
q.setPen(QPen(QColor("#0F766E"), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
q.drawLine(QPointF(6, 9), QPointF(12, 15))
q.drawLine(QPointF(12, 15), QPointF(18, 9))
q.end()
chev.save(str(out / "chevron-down.png"))

# white tick for checked check boxes
tick = QImage(18, 18, QImage.Format.Format_ARGB32)
tick.fill(Qt.GlobalColor.transparent)
t = QPainter(tick)
t.setRenderHint(QPainter.RenderHint.Antialiasing)
t.setPen(QPen(QColor("white"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
t.drawLine(QPointF(4.5, 9.5), QPointF(7.8, 12.8))
t.drawLine(QPointF(7.8, 12.8), QPointF(13.5, 5.8))
t.end()
tick.save(str(out / "check.png"))
