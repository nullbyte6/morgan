#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
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
"""Watches the song that is playing in the background and reports it when something about it changes."""
import logging
import threading

from PySide6.QtCore import QObject, Signal

from .playback import Song, SongReader

log = logging.getLogger("assistant.song")

POLL_SECONDS = 1.0
SEEK_TOLERANCE = 1.5
FAILURE_LIMIT = 5


def differs(old: Song | None, new: Song | None) -> bool:
    """Whether new is worth reporting: another song or state, or a position that is not just time passing."""
    if old is None or new is None:
        return old is not new
    if (old.key, old.playing, old.duration, old.seekable, old.album, old.source) != (
            new.key, new.playing, new.duration, new.seekable, new.album, new.source):
        return True
    if bool(old.cover) != bool(new.cover):
        return True
    expected = old.position_at(new.stamp)
    return abs(new.position - expected) > SEEK_TOLERANCE


class SongMonitor(QObject):
    """Polls the media sessions once a second and emits `updated` with the song, or None when none plays."""

    updated = Signal(object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.current: Song | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="song-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def refresh(self) -> None:
        """Read the player again now, for example right after a command."""
        self._wake.set()

    def _run(self) -> None:
        reader = SongReader()
        failures = 0
        try:
            while not self._stop.is_set():
                try:
                    song = reader.read()
                    failures = 0
                except Exception:
                    failures += 1
                    log.exception("The playing song could not be read")
                    if failures >= FAILURE_LIMIT:
                        log.error("Song detection was turned off after repeated failures")
                        return
                    song = self.current
                if differs(self.current, song):
                    self.current = song
                    try:
                        self.updated.emit(song)
                    except RuntimeError:
                        return
                self._wake.wait(POLL_SECONDS)
                self._wake.clear()
        finally:
            reader.close()
