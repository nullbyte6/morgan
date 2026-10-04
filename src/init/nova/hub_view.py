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
"""The page of a Nova hub: a grid of square tiles, one per section, that reflows as the panel is resized."""
from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QPushButton, QScrollArea, QWidget

from src.init.theme import on_theme_changed

from .calendar_paint import ALIGN_CENTER, color, draw_text, glyph_font, text_font
from .sections import Hub, Section

TILE_MIN = 104
TILE_MAX = 148
GAP = 12
MAX_COLUMNS = 3


class HubTile(QPushButton):
    """A section drawn with the theme: its icon above its name, lit while the mouse is over it."""

    def __init__(self, section: Section, parent: QWidget | None = None):
        super().__init__(parent)
        self.section = section
        self.setObjectName("novaTile")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        on_theme_changed(self._theme_changed)

    def _theme_changed(self, _theme) -> None:
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = self.underMouse()
        width, height = self.width(), self.height()
        painter.setPen(QPen(color("border_strong" if hover else "border"), 2))
        painter.setBrush(color("surface_raised") if hover else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
        draw_text(painter, QRect(0, int(height * 0.14), width, int(height * 0.44)), self.section.glyph,
                  glyph_font(int(height * 0.3)), "accent" if hover else "text_muted", ALIGN_CENTER)
        draw_text(painter, QRect(8, int(height * 0.6), width - 16, int(height * 0.26)), self.section.title,
                  text_font(self.font(), 14), "text" if hover else "text_muted", ALIGN_CENTER)
        painter.end()


class HubGrid(QScrollArea):
    """The tiles of one hub, in up to three columns of equal squares that grow and shrink with the panel."""

    section_selected = Signal(object)

    def __init__(self, hub: Hub, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaScroll")
        self.hub = hub
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        self.setMinimumSize(TILE_MIN, TILE_MIN)
        self._columns = 0
        self._body = QWidget()
        self._body.setObjectName("novaHub")
        self.setWidget(self._body)
        self._grid = QGridLayout(self._body)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(GAP)
        self._tiles = [HubTile(section) for section in hub.sections]
        for tile in self._tiles:
            tile.clicked.connect(lambda _checked=False, section=tile.section: self.section_selected.emit(section))
        self._arrange()

    def minimumSizeHint(self) -> QSize:
        return QSize(TILE_MIN, TILE_MIN)

    @property
    def columns(self) -> int:
        return self._columns

    @property
    def tiles(self) -> list[HubTile]:
        return list(self._tiles)

    def refresh_language(self) -> None:
        for tile in self._tiles:
            tile.update()

    def _arrange(self) -> None:
        available = max(self.viewport().width(), TILE_MIN)
        columns = max(1, min(MAX_COLUMNS, (available + GAP) // (TILE_MIN + GAP)))
        size = max(TILE_MIN, min(TILE_MAX, (available - GAP * (columns - 1)) // columns))
        rows = -(-len(self._tiles) // columns)
        while self._grid.count():
            self._grid.takeAt(0)
        for index, tile in enumerate(self._tiles):
            tile.setFixedSize(size, size)
            self._grid.addWidget(tile, index // columns, index % columns)
        for column in range(MAX_COLUMNS + 1):
            self._grid.setColumnStretch(column, 1 if column == columns else 0)
        for row in range(len(self._tiles) + 1):
            self._grid.setRowStretch(row, 1 if row == rows else 0)
        self._body.setMinimumHeight(rows * size + (rows - 1) * GAP)
        self._columns = columns

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()
