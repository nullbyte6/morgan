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
"""Qt-free signals with the connect/emit surface the desktop interface relies on."""

import threading


class Emitter:
    """Call every connected handler synchronously on the emitting thread."""

    def __init__(self):
        self._handlers = []
        self._lock = threading.Lock()

    def connect(self, handler):
        with self._lock:
            self._handlers.append(handler)

    def disconnect(self, handler):
        with self._lock:
            if handler in self._handlers:
                self._handlers.remove(handler)

    def emit(self, *arguments):
        with self._lock:
            handlers = tuple(self._handlers)
        for handler in handlers:
            handler(*arguments)


class Event:
    """Class-level declaration creating one Emitter per instance on first use.

    A subclass that also derives from a Qt class replaces it with a real Signal.
    """

    def __set_name__(self, owner, name):
        self.key = "_event_" + name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        emitter = instance.__dict__.get(self.key)
        if emitter is None:
            emitter = instance.__dict__.setdefault(self.key, Emitter())
        return emitter
