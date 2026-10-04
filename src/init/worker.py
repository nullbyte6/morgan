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
import logging

from PySide6.QtCore import *

from src.init.session_runner import SessionRunner
from src.init.voice_input import VoiceInputRunner


class VoiceInputWorker(VoiceInputRunner, QThread):
    levels = Signal(object)
    processing = Signal()
    speech_started = Signal()
    utterance = Signal(object)

    def __init__(self, parent=None, *, automatic=False, live=False):
        QThread.__init__(self, parent)
        VoiceInputRunner.__init__(self, automatic=automatic, live=live)

    def interrupted(self):
        return self.isInterruptionRequested()


# noinspection PyBroadException
class AssistantWorker(SessionRunner, QObject):
    chunk = Signal(int, str)
    audio = Signal(int, object)
    directory = Signal(str)
    speaking = Signal(int, bool)
    subtitle = Signal(int, str)
    phase = Signal(int, str)
    activity = Signal(int, object)
    task_title = Signal(int, str)
    permission_denied = Signal(int)
    finished = Signal(str)
    git_diff_ready = Signal(str, str)
    failed = Signal(str)
    ready = Signal()
    confirmation_requested = Signal(int, str, int, int)
    confirmation_closed = Signal(int)
    accepted = Signal(int)
    rejected = Signal(int, str)
    screenshot_requested = Signal(object)
    clipboard_requested = Signal(object)
    exit_requested = Signal()

    def __init__(self, greet=False, *, muted=False, session_key=None, primary=True):
        QObject.__init__(self)
        SessionRunner.__init__(self, greet, muted=muted,
                               session_key=session_key, primary=primary)

    @Slot()
    def initialize(self):
        super().initialize()

    @Slot(int, object)
    def ask(self, turn_id, message):
        super().ask(turn_id, message)

    @Slot()
    def shutdown(self):
        super().shutdown()

    def show_response_surface(self, title):
        try:
            from src.init.visuals.response import request_response_workspace
            result = request_response_workspace(title or "Response",
                                                owner=self.session_key)
            logging.getLogger("assistant.response").info(
                "Response workspace result: %s", result)
            return False
        except Exception:
            logging.getLogger("assistant.response").exception(
                "Unable to open response workspace; falling back to chat")
            return True
