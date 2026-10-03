#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of morgan.
#
#  This program is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty
#  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Theme-aware drawing helpers shared by Nova's calendar views."""
from datetime import date

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from src.init.theme import current_theme, on_theme_changed

from . import formatting
from .calendar_math import month_grid, shift_month
from .entries import FLAG_ROLES, Event

BELL = "\U000f009a"
FLAG = "\U000f023b"
CHEVRON_LEFT = "\U000f0141"
CHEVRON_RIGHT = "\U000f0142"
ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter


def color(role: str, alpha: int | None = None) -> QColor:
    return current_theme().color(role, alpha)


def tint(role: str, amount: int, base: str = "surface") -> QColor:
    """The role at the given opacity (0-255) over a base role, as an opaque color."""
    return QColor(current_theme().blend(role, amount, base))


def entry_role(entry) -> str:
    return "accent" if isinstance(entry, Event) else "warning"


def text_font(base: QFont, pixels: int) -> QFont:
    font = QFont(base)
    font.setPixelSize(pixels)
    font.setBold(False)
    return font


def glyph_font(pixels: int) -> QFont:
    family = QApplication.instance().property("codeFontFamily") or "JetBrainsMonoNL NFM"
    font = QFont(family)
    font.setPixelSize(pixels)
    return font


def draw_text(painter: QPainter, rect: QRect, text: str, font: QFont, role: str,
              flags=ALIGN_LEFT, alpha: int | None = None) -> None:
    painter.setFont(font)
    painter.setPen(color(role, alpha))
    painter.drawText(rect, flags, painter.fontMetrics().elidedText(
        text, Qt.TextElideMode.ElideRight, max(1, rect.width())))


def draw_chip(painter: QPainter, rect: QRect, entry, base: QFont, *, hovered: bool = False,
              pixels: int = 12) -> None:
    """A compact entry marker: tinted background, accent bar and a one-line title."""
    role = entry_role(entry)
    completed = bool(getattr(entry, "is_completed", False))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(tint("text_subtle" if completed else role, 90 if hovered else 62))
    painter.drawRoundedRect(QRectF(rect), 5, 5)
    painter.setBrush(color("text_subtle" if completed else role))
    painter.drawRoundedRect(QRectF(rect.left(), rect.top() + 3, 3, max(1, rect.height() - 6)), 1.5, 1.5)
    inner = rect.adjusted(9, 0, -5, 0)
    font = text_font(base, pixels)
    if not isinstance(entry, Event):
        icon = glyph_font(pixels)
        draw_text(painter, QRect(inner.left(), inner.top(), pixels + 2, inner.height()), BELL, icon, role)
        inner = inner.adjusted(pixels + 6, 0, 0, 0)
    if entry.flag != "none" and inner.width() > 3 * pixels:
        flag_width = pixels + 4
        draw_text(painter, QRect(inner.right() - flag_width + 1, inner.top(), flag_width, inner.height()),
                  FLAG, glyph_font(pixels), "text_subtle" if completed else FLAG_ROLES[entry.flag], ALIGN_RIGHT)
        inner = inner.adjusted(0, 0, -flag_width, 0)
    font.setStrikeOut(completed)
    draw_text(painter, inner, entry.title, font, "text_subtle" if completed else "text")


def paint_month(painter: QPainter, rect: QRect, year: int, month: int, *, base: QFont,
                first_weekday: int, today: date, counts: dict[date, int],
                hovered: date | None = None, selected: date | None = None,
                title: bool = True) -> tuple[list[tuple[QRect, date]], QRect]:
    """Draw one compact month and return the clickable day cells and the title area."""
    title_height = 28 if title else 0
    header_height = 20
    cell_width = rect.width() / 7
    cell_height = (rect.height() - title_height - header_height) / 6
    title_rect = QRect(rect.left(), rect.top(), rect.width(), title_height) if title else QRect()
    if title:
        draw_text(painter, title_rect, formatting.month_name(month), text_font(base, 15), "text")
    for column in range(7):
        label = formatting.weekday_name((first_weekday + column) % 7, "narrow")
        draw_text(painter, QRect(round(rect.left() + column * cell_width), rect.top() + title_height,
                                 round(cell_width), header_height),
                  label, text_font(base, 10), "text_subtle", ALIGN_CENTER)
    pixels = int(max(10, min(13, min(cell_width, cell_height) * 0.46)))
    diameter = min(cell_width, cell_height, 26) - 2
    hits = []
    for row, week in enumerate(month_grid(year, month, first_weekday)):
        for column, day in enumerate(week):
            if day.month != month:
                continue
            cell = QRect(round(rect.left() + column * cell_width),
                         round(rect.top() + title_height + header_height + row * cell_height),
                         round(cell_width), round(cell_height))
            hits.append((cell, day))
            disc = QRectF(cell.center().x() - diameter / 2, cell.center().y() - diameter / 2,
                          diameter, diameter)
            painter.setPen(Qt.PenStyle.NoPen)
            count = counts.get(day, 0)
            if day == today:
                painter.setBrush(color("accent"))
                painter.drawEllipse(disc)
            elif day == hovered:
                painter.setBrush(color("surface_raised"))
                painter.drawEllipse(disc)
            elif count:
                painter.setBrush(tint("accent", min(36 + count * 26, 130)))
                painter.drawEllipse(disc)
            if day == selected and day != today:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(color("accent"))
                painter.drawEllipse(disc)
            draw_text(painter, cell, str(day.day), text_font(base, pixels),
                      "on_accent" if day == today else "text", ALIGN_CENTER)
    return hits, title_rect


class MiniMonth(QWidget):
    """A single month with previous/next arrows, used to pick a date."""

    day_selected = Signal(object)
    WIDTH, HEIGHT = 264, 272

    def __init__(self, day: date | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaMiniMonth")
        self.setMouseTracking(True)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self._selected = day or date.today()
        self._shown = self._selected.replace(day=1)
        self._hovered: date | None = None
        self._cells: list[tuple[QRect, date]] = []
        self._previous = QRect(8, 8, 28, 28)
        self._next = QRect(self.WIDTH - 36, 8, 28, 28)
        on_theme_changed(self._theme_changed)

    @property
    def selected(self) -> date:
        return self._selected

    def set_selected(self, day: date) -> None:
        self._selected = day
        self._shown = day.replace(day=1)
        self.update()

    def _theme_changed(self, _theme) -> None:
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.font()
        title = formatting.month_title(self._shown)
        draw_text(painter, QRect(40, 8, self.WIDTH - 80, 28), title, text_font(base, 15), "text", ALIGN_CENTER)
        for rect, glyph in ((self._previous, CHEVRON_LEFT), (self._next, CHEVRON_RIGHT)):
            draw_text(painter, rect, glyph, glyph_font(16), "text_muted", ALIGN_CENTER)
        self._cells, _ = paint_month(
            painter, QRect(8, 40, self.WIDTH - 16, self.HEIGHT - 48), self._shown.year, self._shown.month,
            base=base, first_weekday=formatting.first_weekday(), today=date.today(), counts={},
            hovered=self._hovered, selected=self._selected, title=False)
        painter.end()

    def _day_at(self, point: QPoint) -> date | None:
        return next((day for rect, day in self._cells if rect.contains(point)), None)

    def mouseMoveEvent(self, event):
        hovered = self._day_at(event.position().toPoint())
        if hovered != self._hovered:
            self._hovered = hovered
            self.update()
        self.setCursor(Qt.CursorShape.PointingHandCursor if hovered or self._over_arrow(event.position().toPoint())
                       else Qt.CursorShape.ArrowCursor)

    def _over_arrow(self, point: QPoint) -> bool:
        return self._previous.contains(point) or self._next.contains(point)

    def leaveEvent(self, event):
        self._hovered = None
        self.update()

    def mousePressEvent(self, event):
        point = event.position().toPoint()
        if self._previous.contains(point):
            self._shown = shift_month(self._shown, -1)
            self.update()
        elif self._next.contains(point):
            self._shown = shift_month(self._shown, 1)
            self.update()
        else:
            day = self._day_at(point)
            if day is not None:
                self._selected = day
                self.update()
                self.day_selected.emit(day)
