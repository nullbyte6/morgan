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
"""Nova's sidebar: a star that folds it to icons, and one entry per section."""
from PySide6.QtCore import QEasingCurve, QRect, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QButtonGroup, QPushButton, QVBoxLayout, QWidget

from src.init.lang import tr
from src.init.theme import on_theme_changed

from .calendar_paint import ALIGN_CENTER, ALIGN_LEFT, color, draw_text, glyph_font, text_font
from .sections import Section

STAR = "\U000f0ae2"
EXPANDED_WIDTH = 208
COLLAPSED_WIDTH = 62
SLIDE_MS = 220
ITEM_HEIGHT = 42
ICON_WIDTH = 40


class NavItem(QPushButton):
    """A section entry drawn with the theme: icon always visible, label while there is room."""

    def __init__(self, section: Section, parent: QWidget | None = None):
        super().__init__(parent)
        self.section = section
        self.setObjectName("novaNavItem")
        self.setCheckable(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(ITEM_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        on_theme_changed(self._theme_changed)

    def _theme_changed(self, _theme) -> None:
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.isChecked()
        hover = self.underMouse()
        if active or hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color("surface_selected" if active else "surface_raised"))
            painter.drawRoundedRect(QRectF(self.rect()), 10, 10)
        draw_text(painter, QRect(0, 0, ICON_WIDTH + 4, self.height()), self.section.glyph, glyph_font(23),
                  "accent" if active else ("text" if hover else "text_muted"), ALIGN_CENTER)
        label = QRect(ICON_WIDTH + 6, 0, max(0, self.width() - ICON_WIDTH - 14), self.height())
        if label.width() > 12:
            draw_text(painter, label, self.section.title, text_font(self.font(), 15),
                      "text" if active or hover else "text_muted", ALIGN_LEFT)
        painter.end()


class NovaSidebar(QWidget):
    """Section navigation that slides between a labelled column and an icon strip."""

    section_selected = Signal(object)
    toggle_requested = Signal()

    def __init__(self, initial: Section = Section.AGENDA, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaSidebar")
        self._collapsed = False
        self.setFixedWidth(EXPANDED_WIDTH)

        self._slide = QVariantAnimation(self)
        self._slide.setDuration(SLIDE_MS)
        self._slide.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._slide.valueChanged.connect(lambda width: self.setFixedWidth(int(width)))

        self.star = QPushButton(STAR)
        self.star.setObjectName("novaStar")
        self.star.setFixedSize(42, 42)
        self.star.setCursor(Qt.CursorShape.PointingHandCursor)
        self.star.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.star.clicked.connect(self.toggle_requested)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._items: dict[Section, NavItem] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(14)
        layout.addWidget(self.star)
        navigation = QVBoxLayout()
        navigation.setSpacing(4)
        for section in Section:
            item = NavItem(section)
            item.toggled.connect(lambda checked, section=section: checked and self.section_selected.emit(section))
            self._group.addButton(item)
            navigation.addWidget(item)
            self._items[section] = item
        layout.addLayout(navigation)
        layout.addStretch(1)
        self._items[initial].setChecked(True)
        self.refresh_language()

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def select(self, section: Section) -> None:
        self._items[section].setChecked(True)

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        target = COLLAPSED_WIDTH if collapsed else EXPANDED_WIDTH
        self._slide.stop()
        if not animate or not self.isVisible():
            self.setFixedWidth(target)
            return
        self._slide.setStartValue(self.width())
        self._slide.setEndValue(target)
        self._slide.start()

    def refresh_language(self) -> None:
        self.star.setToolTip(tr("nova.sidebar.toggle"))
        for item in self._items.values():
            item.update()
