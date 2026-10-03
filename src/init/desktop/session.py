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
"""Runtime and visible state owned by one desktop conversation session."""

from PySide6.QtCore import QElapsedTimer, QObject, QThread, Signal, Slot

from src.init.desktop.task_presentation import TaskPresentation


class DesktopSession(QObject):
    """GUI-thread owner of one worker; routes its signals back to this session."""
    request = Signal(int, object)

    def __init__(self, window, index, worker):
        super().__init__(window)
        self.window = window
        self.index = index
        self.worker = worker
        self.worker_thread = QThread(window)
        self.presentation = TaskPresentation(self)
        self.panel_id = None
        self.ui = None
        self.ready = False
        self.closing = False
        self.released = False
        self.busy = False
        self.stopping = False
        self.speaking = False
        self.submitting = None
        self.pending_prompt = None
        self.active_prompt = None
        self.paused_prompt = None
        self.task_stop_requested = False
        self.permission_denied_state = False
        self.pending_voice_barge = False
        self.pending_wake_barge = False
        self.wake_command_id = None
        self.turn_id = 0
        self.current_reply = None
        self.current_response_view = None
        self.completed_git_diff = None
        self.status_key = ""
        self.subtitle_text = ""
        self.command_output = ""
        self.command_output_visible = False
        self.draft = ""
        self.confirmation_dialogs = {}
        self.response_timer = QElapsedTimer()
        self.response_timer_running = False
        self.response_timer_text = "0s"

    def bind(self):
        worker = self.worker
        worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(worker.initialize)
        self.request.connect(worker.ask)
        worker.ready.connect(self.on_ready)
        worker.accepted.connect(self.on_accepted)
        worker.rejected.connect(self.on_rejected)
        worker.chunk.connect(self.on_chunk)
        worker.audio.connect(self.on_audio)
        worker.speaking.connect(self.on_speaking)
        worker.subtitle.connect(self.on_subtitle)
        worker.activity.connect(self.presentation.on_activity)
        worker.phase.connect(self.presentation.on_phase)
        worker.task_title.connect(self.presentation.set_task_title)
        worker.permission_denied.connect(self.on_permission_denied)
        worker.finished.connect(self.on_finished)
        worker.git_diff_ready.connect(self.on_git_diff_ready)
        worker.directory.connect(self.on_directory)
        worker.failed.connect(self.on_failed)
        worker.confirmation_requested.connect(self.on_confirmation_requested)
        worker.confirmation_closed.connect(self.on_confirmation_closed)
        self.presentation.changed.connect(self.on_view)
        self.worker_thread.finished.connect(worker.shutdown)
        self.worker_thread.finished.connect(worker.deleteLater)

    @Slot()
    def on_ready(self):
        if not self.closing:
            self.window.on_ready(self)

    @Slot(int)
    def on_accepted(self, turn_id):
        if not self.closing:
            self.window.on_request_accepted(self, turn_id)

    @Slot(int, str)
    def on_rejected(self, turn_id, error):
        if self.closing:
            self.window.release_session(self)
        else:
            self.window.on_request_rejected(self, turn_id, error)

    @Slot(int, str)
    def on_chunk(self, turn_id, chunk):
        if not self.closing:
            self.window.on_chunk(self, turn_id, chunk)

    @Slot(int, object)
    def on_audio(self, turn_id, levels):
        if not self.closing:
            self.window.on_audio(self, turn_id, levels)

    @Slot(int, bool)
    def on_speaking(self, turn_id, speaking):
        if not self.closing:
            self.window.on_speaking(self, turn_id, speaking)

    @Slot(int, str)
    def on_subtitle(self, turn_id, text):
        if not self.closing:
            self.window.on_subtitle(self, turn_id, text)

    @Slot(int)
    def on_permission_denied(self, turn_id):
        if not self.closing:
            self.window.on_permission_denied(self, turn_id)

    @Slot(str)
    def on_finished(self, reply):
        if self.closing:
            self.window.release_session(self)
        else:
            self.window.on_finished(self, reply)

    @Slot(str)
    def on_directory(self, directory):
        if not self.closing:
            self.window.on_session_directory(self, directory)

    @Slot(str, str)
    def on_git_diff_ready(self, directory, diff):
        self.completed_git_diff = (directory, diff)

    @Slot(str)
    def on_failed(self, error):
        if self.closing:
            self.window.release_session(self)
        else:
            self.window.on_error(self, error)

    @Slot(int, str, int, int)
    def on_confirmation_requested(self, turn_id, message, request_id, timeout):
        if self.closing:
            self.worker.resolve_confirmation(False, request_id)
        else:
            self.window.on_confirmation_requested(self, turn_id, message, request_id, timeout)

    @Slot(int)
    def on_confirmation_closed(self, request_id):
        request = self.confirmation_dialogs.get(request_id)
        if request is not None:
            request.cancel()

    @Slot(object)
    def on_view(self, view):
        if not self.closing:
            self.window.on_session_view(self, view)
