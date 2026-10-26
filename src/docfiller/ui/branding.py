"""Brand assets — the application mark, the horizontal logo and the splash screen.

Design language: one accent colour, geometric and plain shapes; no emoji and no
stock icon set. Everything is drawn with Qt, so no binary asset is bundled and
the images stay sharp at every screen scale.

The mark: **a document page + a small table + a check badge.** The three parts
sit in separate regions, so they stay distinct even as a 16 px taskbar icon.

**High DPI:** every image is drawn at the screen's device pixel ratio. Drawn at
1x and scaled by Qt, text turns soft and faded at 125 % / 150 % scaling.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from . import theme

APP_NAME = "DOCFILLER"
SUBTITLE = "Document Automation"

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _ratio() -> float:
    try:
        screen = QGuiApplication.primaryScreen()
        return float(screen.devicePixelRatio()) if screen else 1.0
    except Exception:  # noqa: BLE001 - no application object yet
        return 1.0


def _canvas(width: float, height: float):
    ratio = _ratio()
    pixmap = QPixmap(max(1, int(width * ratio)), max(1, int(height * ratio)))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.scale(ratio, ratio)
    return pixmap, painter


def mark(size: int, background: bool = True) -> QPixmap:
    """Square brand mark: document page + table + check badge."""
    c = theme.COLOURS
    pixmap, p = _canvas(size, size)
    b = float(size)

    if background:
        gradient = QLinearGradient(0, 0, b, b)
        gradient.setColorAt(0.0, QColor(c["accent_bright"]))
        gradient.setColorAt(1.0, QColor(c["accent_dark"]))
        box = QPainterPath()
        box.addRoundedRect(QRectF(0, 0, b, b), b * 0.24, b * 0.24)
        p.fillPath(box, QBrush(gradient))
        # a thin highlight so the box is not a flat blob of colour
        shine = QLinearGradient(0, 0, 0, b * 0.55)
        shine.setColorAt(0.0, QColor(255, 255, 255, 46))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(box, QBrush(shine))
        paper = QColor("#ffffff")
    else:
        paper = QColor(c["accent"])

    # --- the page (top right corner folded)
    left, top = b * 0.24, b * 0.17
    width, height = b * 0.46, b * 0.60
    fold = b * 0.15
    page = QPainterPath()
    page.moveTo(left, top)
    page.lineTo(left + width - fold, top)
    page.lineTo(left + width, top + fold)
    page.lineTo(left + width, top + height)
    page.lineTo(left, top + height)
    page.closeSubpath()
    p.fillPath(page, paper)
    corner = QPainterPath()
    corner.moveTo(left + width - fold, top)
    corner.lineTo(left + width, top + fold)
    corner.lineTo(left + width - fold, top + fold)
    corner.closeSubpath()
    p.fillPath(corner, QColor(c["accent_dark"] if background else "#ffffff"))

    ink = QColor(c["accent_dark"]) if background else QColor("#ffffff")

    # --- a small table: the spreadsheet the values come from
    pen = QPen(ink)
    pen.setWidthF(max(0.8, b * 0.028))
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    grid_left, grid_top = left + width * 0.18, top + height * 0.26
    grid_width, grid_height = width * 0.64, height * 0.30
    p.drawRect(QRectF(grid_left, grid_top, grid_width, grid_height))
    p.drawLine(QPointF(grid_left + grid_width * 0.40, grid_top),
               QPointF(grid_left + grid_width * 0.40, grid_top + grid_height))
    p.drawLine(QPointF(grid_left, grid_top + grid_height / 2),
               QPointF(grid_left + grid_width, grid_top + grid_height / 2))

    # --- text lines below the table, so it reads as a document
    line = QPen(ink)
    line.setWidthF(max(0.8, b * 0.034))
    line.setCapStyle(Qt.RoundCap)
    p.setPen(line)
    for position, length in ((0.70, 0.80), (0.84, 0.58)):
        p.drawLine(
            QPointF(left + width * 0.20, top + height * position),
            QPointF(left + width * length, top + height * position),
        )

    # --- check badge (bottom right)
    diameter = b * 0.40
    centre = QPointF(b * 0.735, b * 0.735)
    if background:
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(c["accent_dark"])))
        p.drawEllipse(centre, diameter / 2 + b * 0.028, diameter / 2 + b * 0.028)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor(c["success"]) if background else QColor(c["accent"])))
    p.drawEllipse(centre, diameter / 2, diameter / 2)
    tick = QPen(QColor("#ffffff"))
    tick.setWidthF(max(1.2, b * 0.058))
    tick.setCapStyle(Qt.RoundCap)
    tick.setJoinStyle(Qt.RoundJoin)
    p.setPen(tick)
    p.setBrush(Qt.NoBrush)
    p.drawPolyline(
        [
            QPointF(centre.x() - diameter * 0.22, centre.y() + diameter * 0.02),
            QPointF(centre.x() - diameter * 0.05, centre.y() + diameter * 0.18),
            QPointF(centre.x() + diameter * 0.24, centre.y() - diameter * 0.20),
        ]
    )
    p.end()
    return pixmap


def _fit(font: QFont, text: str, room: float, start: float) -> QFont:
    """Reduce the point size until `text` fits in `room`."""
    size = start
    while size > 5:
        font.setPointSizeF(size)
        if QFontMetricsF(font).horizontalAdvance(text) <= room:
            break
        size -= 0.5
    return font


def logo(width: int = 320, dark_background: bool = True) -> QPixmap:
    """Horizontal logo: mark + name + subtitle."""
    c = theme.COLOURS
    height = int(width * 0.28)
    pixmap, p = _canvas(width, height)
    mark_size = int(height * 0.92)
    p.drawPixmap(0, (height - mark_size) // 2, mark(mark_size))

    x = mark_size + height * 0.22
    room = width - x

    name_font = QFont()
    name_font.setWeight(QFont.Black)
    name_font.setLetterSpacing(QFont.PercentageSpacing, 102)
    p.setFont(_fit(name_font, APP_NAME, room, height * 0.34))
    p.setPen(QColor("#ffffff") if dark_background else QColor(c["text"]))
    p.drawText(QRectF(x, height * 0.10, room, height * 0.46), Qt.AlignVCenter, APP_NAME)

    sub_font = QFont()
    sub_font.setWeight(QFont.DemiBold)
    p.setFont(_fit(sub_font, SUBTITLE, room, height * 0.22))
    p.setPen(QColor(c["accent_bright"]) if dark_background else QColor(c["text_muted"]))
    p.drawText(QRectF(x, height * 0.54, room, height * 0.38), Qt.AlignVCenter, SUBTITLE)
    p.end()
    return pixmap


def splash(width: int = 620, height: int = 360, status: str = "") -> QPixmap:
    """The splash screen image."""
    c = theme.COLOURS
    pixmap, p = _canvas(width, height)
    w, h = float(width), float(height)

    ground = QPainterPath()
    ground.addRoundedRect(QRectF(0, 0, w, h), 20, 20)
    gradient = QLinearGradient(0, 0, w, h)
    gradient.setColorAt(0.0, QColor("#0e1c22"))
    gradient.setColorAt(0.55, QColor(c["sidebar_bg"]))
    gradient.setColorAt(1.0, QColor(c["accent_dark"]))
    p.fillPath(ground, QBrush(gradient))

    # a large, very faint mark in the corner for depth
    p.save()
    p.setClipPath(ground)
    p.setOpacity(0.07)
    watermark = int(h * 0.95)
    p.drawPixmap(int(w - watermark * 0.55), int(h - watermark * 0.62), mark(watermark, background=False))
    p.restore()

    stripe = QLinearGradient(0, 0, w, 0)
    stripe.setColorAt(0.0, QColor(c["accent_bright"]))
    stripe.setColorAt(1.0, QColor(c["success"]))
    top = QPainterPath()
    top.addRoundedRect(QRectF(0, 0, w, 5), 2.5, 2.5)
    p.fillPath(top, QBrush(stripe))

    size = int(h * 0.30)
    p.drawPixmap(int(w * 0.5 - size / 2), int(h * 0.15), mark(size))

    name_font = QFont()
    name_font.setWeight(QFont.Black)
    name_font.setLetterSpacing(QFont.PercentageSpacing, 108)
    p.setFont(_fit(name_font, APP_NAME, w * 0.82, h * 0.095))
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(0, h * 0.52, w, h * 0.12), Qt.AlignCenter, APP_NAME)

    sub_font = QFont()
    sub_font.setWeight(QFont.DemiBold)
    sub_font.setLetterSpacing(QFont.PercentageSpacing, 104)
    p.setFont(_fit(sub_font, SUBTITLE, w * 0.8, h * 0.05))
    p.setPen(QColor(c["accent_bright"]))
    p.drawText(QRectF(0, h * 0.645, w, h * 0.08), Qt.AlignCenter, SUBTITLE)

    p.setPen(QPen(QColor(255, 255, 255, 28), 1))
    p.drawLine(QPointF(w * 0.33, h * 0.755), QPointF(w * 0.67, h * 0.755))

    note_font = QFont()
    note_font.setPointSizeF(h * 0.036)
    p.setFont(note_font)
    p.setPen(QColor(c["sidebar_text"]))
    p.drawText(QRectF(0, h * 0.80, w, h * 0.09), Qt.AlignCenter,
               status or "Documents are filled without changing their layout")
    p.end()
    return pixmap


def icon() -> QIcon:
    """Window and taskbar icon."""
    result = QIcon()
    for size in ICON_SIZES:
        result.addPixmap(mark(size))
    return result


def write_ico(target: str | Path) -> Path:
    """Write an .ico file for the executable and shortcuts."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    image = mark(max(ICON_SIZES)).toImage()
    if not image.save(str(target), "ICO"):
        raise OSError(f"The icon could not be written: {target}")
    return target
