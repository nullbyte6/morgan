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
"""The song workspace view: album cover, progress, playback controls, copy buttons and a summary."""
import html
import logging
import re
import threading
import time
from dataclasses import replace

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QStackedWidget, QStyle, QVBoxLayout, QWidget)

from src.init.lang import tr

from . import playback, summary
from .monitor import SongMonitor
from .playback import Song

log = logging.getLogger("assistant.song")

PREVIOUS = "\U000f04ae"
NEXT = "\U000f04ad"
PLAY = "\U000f040a"
PAUSE = "\U000f03e4"
COPY = "\U000f018f"
COPIED = "\U000f012c"
SUMMARY = "\U000f0bc2"
SEEK_STEPS = 1000
TICK_MS = 250
COPIED_MS = 1200
COVER_MAX = 322
COVER_MIN = 96
COVER_RADIUS = 16
CONTENT_BELOW_COVER = 400
SIDE_MARGIN = 28
ACTION_SIZE = 36


def clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def rounded_cover(source: QPixmap, side: int) -> QPixmap:
    scaled = source.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    cover = QPixmap(side, side)
    cover.fill(Qt.GlobalColor.transparent)
    painter = QPainter(cover)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, side, side, COVER_RADIUS, COVER_RADIUS)
    painter.setClipPath(path)
    painter.drawPixmap((side - scaled.width()) // 2, (side - scaled.height()) // 2, scaled)
    painter.end()
    return cover


def _label(name: str, wrap: bool = True, align=Qt.AlignmentFlag.AlignHCenter) -> QLabel:
    label = QLabel()
    label.setObjectName(name)
    label.setWordWrap(wrap)
    label.setAlignment(align)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return label


def _button(name: str, size: int | None = None) -> QPushButton:
    button = QPushButton()
    button.setObjectName(name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    if size is not None:
        button.setFixedSize(size, size)
    return button


class SeekSlider(QSlider):
    """A progress bar that jumps where it is clicked and asks for a seek when released."""

    seek_requested = Signal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("songSeek")
        self.setRange(0, SEEK_STEPS)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _value_at(self, event) -> int:
        return QStyle.sliderValueFromPosition(0, SEEK_STEPS, round(event.position().x()), max(1, self.width()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.setSliderDown(True)
            self.setValue(self._value_at(event))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.setValue(self._value_at(event))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.isSliderDown() and event.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._value_at(event))
            self.setSliderDown(False)
            self.seek_requested.emit(self.value() / SEEK_STEPS)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class SongSummaryView(QWidget):
    """The summary of the song that is playing, shown in a panel of its own below the song."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("songSummaryView")
        self.setProperty("workspaceEmpty", False)
        self.text = _label("songSummary", align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column = QVBoxLayout()
        column.setContentsMargins(SIDE_MARGIN, 22, SIDE_MARGIN, 22)
        column.addWidget(self.text)
        column.addStretch(1)
        body = QWidget()
        body.setObjectName("novaEntryBody")
        body.setLayout(column)
        scroll = QScrollArea()
        scroll.setObjectName("novaScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setWidget(body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def minimumSizeHint(self) -> QSize:
        return QSize(300, 120)


class SongView(QWidget):
    """The song that is playing, with its cover, a progress bar, playback controls, copy buttons and a summary."""

    summarized = Signal(str, str, bool)
    summary_requested = Signal(object)
    command_finished = Signal(bool)

    def __init__(self, monitor: SongMonitor, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("songView")
        self.setProperty("workspaceEmpty", False)
        self._monitor = monitor
        self._song: Song | None = monitor.current
        self._cover_source: QPixmap | None = None
        self._cover_id: tuple | None = None
        self._cover_side = 0
        self._summaries: dict[str, tuple[str, bool]] = {}
        self._pending: set[str] = set()
        self._summary_view: SongSummaryView | None = None

        self.empty = _label("songEmpty", align=Qt.AlignmentFlag.AlignCenter)

        self.cover = QLabel()
        self.cover.setObjectName("songCover")
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = _label("songTitle")
        self.artist = _label("songArtist")
        self.album = _label("songAlbum")

        self.seek = SeekSlider()
        self.elapsed = _label("songTime", wrap=False, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.length = _label("songTime", wrap=False, align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for label in (self.elapsed, self.length):
            label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            label.setMinimumWidth(46)
        progress = QHBoxLayout()
        progress.setSpacing(10)
        progress.addWidget(self.elapsed)
        progress.addWidget(self.seek, 1)
        progress.addWidget(self.length)

        self.previous_button = _button("songTransport", 44)
        self.previous_button.setText(PREVIOUS)
        self.play_button = _button("songPlay", 56)
        self.next_button = _button("songTransport", 44)
        self.next_button.setText(NEXT)
        self.copy_button = _button("songAction", ACTION_SIZE)
        self.summarize_button = _button("songAction", ACTION_SIZE)
        self.summarize_button.setText(SUMMARY)
        self.copy_reset = QTimer(self)
        self.copy_reset.setSingleShot(True)
        self.copy_reset.setInterval(COPIED_MS)
        self.copy_reset.timeout.connect(self._label_copies)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.copy_button)
        actions.addWidget(self.summarize_button)
        transport = QHBoxLayout()
        transport.setSpacing(14)
        for button in (self.previous_button, self.play_button, self.next_button):
            transport.addWidget(button)
        controls = QGridLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addLayout(actions, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        controls.addLayout(transport, 0, 0, Qt.AlignmentFlag.AlignHCenter)


        column = QVBoxLayout()
        column.setContentsMargins(SIDE_MARGIN, 22, SIDE_MARGIN, 22)
        column.setSpacing(12)
        column.addSpacing(40)
        column.addStretch(2)
        column.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(6)
        names = QVBoxLayout()
        names.setSpacing(4)
        names.addWidget(self.title)
        names.addWidget(self.artist)
        names.addWidget(self.album)
        column.addLayout(names)
        column.addStretch(1)
        column.addLayout(progress)
        column.addLayout(controls)
        column.addSpacing(64)
        body = QWidget()
        body.setObjectName("novaEntryBody")
        body.setLayout(column)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("novaScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setWidget(body)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.empty)
        self.pages.addWidget(self.scroll)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.pages)

        self.clock = QTimer(self)
        self.clock.setInterval(TICK_MS)
        self.clock.timeout.connect(self._tick)
        monitor.updated.connect(self._on_song, Qt.ConnectionType.QueuedConnection)
        self.summarized.connect(self._show_summary, Qt.ConnectionType.QueuedConnection)
        self.command_finished.connect(self._command_finished, Qt.ConnectionType.QueuedConnection)
        self.previous_button.clicked.connect(lambda: self._command("previous"))
        self.next_button.clicked.connect(lambda: self._command("next"))
        self.play_button.clicked.connect(self._toggle)
        self.seek.seek_requested.connect(self._seek)
        self.copy_button.clicked.connect(self._copy)
        self.summarize_button.clicked.connect(self._summarize)
        self.refresh_language()

    def minimumSizeHint(self) -> QSize:
        return QSize(300, 260)

    def refresh_language(self) -> None:
        self.empty.setText(tr("song.empty"))
        self.previous_button.setToolTip(tr("song.previous"))
        self.next_button.setToolTip(tr("song.next"))
        self._label_copies()
        self._render()

    def _label_copies(self) -> None:
        self.copy_button.setText(COPY)
        self.copy_button.setToolTip(tr("song.copy_title_tooltip"))

    def _on_song(self, song: Song | None) -> None:
        self._song = song
        self._render()

    def _position(self) -> float:
        return self._song.position_at(time.monotonic()) if self._song is not None else 0.0

    def _render(self) -> None:
        song = self._song
        self.pages.setCurrentWidget(self.empty if song is None else self.scroll)
        if song is None:
            self._cover_id = None
            return
        self.title.setText(song.title)
        self.artist.setText(song.artist)
        self.album.setText(song.album)
        self.album.setVisible(bool(song.album))
        self.play_button.setText(PAUSE if song.playing else PLAY)
        self.play_button.setToolTip(tr("song.pause" if song.playing else "song.play"))
        self.length.setText(clock(song.duration) if song.duration > 0 else "")
        self.seek.setEnabled(song.seekable and song.duration > 0)
        self.copy_button.setEnabled(bool(song.title))
        self._render_cover()
        self._render_summary()
        self._tick()

    def _render_cover(self) -> None:
        song = self._song
        cover_id = (song.key, bool(song.cover))
        if cover_id != self._cover_id:
            self._cover_id = cover_id
            self._cover_source = None
            if song.cover:
                pixmap = QPixmap()
                if pixmap.loadFromData(song.cover) and not pixmap.isNull():
                    self._cover_source = pixmap
            self._cover_side = 0
        side = max(COVER_MIN, min(COVER_MAX, self.width() - 2 * SIDE_MARGIN - 8,
                                  self.height() - CONTENT_BELOW_COVER))
        if side == self._cover_side:
            return
        self._cover_side = side
        self.cover.setFixedSize(side, side)
        if self._cover_source is not None:
            self.cover.setText("")
            self.cover.setPixmap(rounded_cover(self._cover_source, side))
        else:
            self.cover.setPixmap(QPixmap())
            self.cover.setText("\U000f075a")

    def _tick(self) -> None:
        song = self._song
        if song is None:
            return
        position = self._position()
        self.elapsed.setText(clock(position))
        if song.duration > 0 and not self.seek.isSliderDown():
            self.seek.setValue(round(position / song.duration * SEEK_STEPS))
        elif song.duration <= 0:
            self.seek.setValue(0)

    def _toggle(self) -> None:
        song = self._song
        if song is None:
            return
        now = time.monotonic()
        self._song = replace(song, playing=not song.playing, position=song.position_at(now), stamp=now)
        self._render()
        self._command("pause" if song.playing else "play")

    def _seek(self, fraction: float) -> None:
        song = self._song
        if song is None or song.duration <= 0:
            self._render()
            return
        target = fraction * song.duration
        self._song = replace(song, position=target, stamp=time.monotonic())
        self._tick()
        threading.Thread(target=self._run, args=(playback.seek, song, target), name="song-seek",
                         daemon=True).start()

    def _command(self, action: str) -> None:
        song = self._song
        if song is None:
            return
        threading.Thread(target=self._run, args=(playback.control, song, action), name="song-control",
                         daemon=True).start()

    def _run(self, command, song: Song, argument) -> None:
        try:
            accepted = command(song, argument)
        except Exception:
            log.exception("The player command failed")
            accepted = False
        self._monitor.refresh()
        try:
            self.command_finished.emit(accepted)
        except RuntimeError:
            pass

    def _command_finished(self, accepted: bool) -> None:
        if not accepted:
            self._song = self._monitor.current
            self._render()

    def _copy(self) -> None:
        song = self._song
        if song is None:
            return
        QApplication.clipboard().setText(song.title)
        self.copy_button.setText(COPIED)
        self.copy_reset.start()

    def _summarize(self) -> None:
        song = self._song
        if song is None or song.key in self._pending:
            return
        key, title, artist, album = song.key, song.title, song.artist, song.album
        self._pending.add(key)
        self._summaries.pop(key, None)
        self._open_summary()
        self._render_summary()

        def run() -> None:
            try:
                text, failed = summary.summarize(title, artist, album), False
            except Exception as error:
                log.exception("The song summary could not be written")
                text, failed = str(error), True
            try:
                self.summarized.emit(key, text, failed)
            except RuntimeError:
                pass

        threading.Thread(target=run, name="song-summary", daemon=True).start()

    def _show_summary(self, key: str, text: str, failed: bool) -> None:
        self._pending.discard(key)
        self._summaries[key] = (text, failed)
        self._render_summary()

    def _open_summary(self) -> None:
        if self._summary_view is not None:
            return
        view = SongSummaryView()
        view.destroyed.connect(self._summary_closed)
        self._summary_view = view
        self.summary_requested.emit(view)

    def _summary_closed(self) -> None:
        self._summary_view = None

    def _render_summary(self) -> None:
        song = self._song
        if song is None:
            return
        busy = song.key in self._pending
        self.summarize_button.setEnabled(not busy)
        self.summarize_button.setToolTip(tr("song.summarizing" if busy else "song.summarize"))
        view = self._summary_view
        if view is None:
            return
        result = self._summaries.get(song.key)
        if busy:
            view.text.setText(tr("song.summarizing"))
        elif result is None:
            view.text.setText("")
        else:
            text, failed = result
            view.text.setText(self._markup(tr("song.summary_error", error=text) if failed else text, failed))

    @staticmethod
    def _markup(text: str, plain: bool) -> str:
        markup = html.escape(text.strip())
        if not plain:
            for section in ("lyrics", "themes", "facts"):
                name = html.escape(tr(f"song.section.{section}"))
                markup = re.sub(rf"(?m)^[^\w\n]*{re.escape(name)}[^\w\n]*:", f"<b>{name}:</b>", markup, flags=re.IGNORECASE)
        return markup.replace("\n", "<br>")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._song is not None:
            self._render_cover()

    def showEvent(self, event):
        super().showEvent(event)
        self._on_song(self._monitor.current)
        self.clock.start()

    def hideEvent(self, event):
        self.clock.stop()
        super().hideEvent(event)

    def dispose(self) -> None:
        self.clock.stop()
        self.copy_reset.stop()
