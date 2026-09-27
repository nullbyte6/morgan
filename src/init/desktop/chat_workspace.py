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

"""Arlo desktop interface using PySide6."""
import html
import logging
import os
import re
import random
import sys
import threading
import tempfile
from getpass import getuser
from tkinter import font

from src.init.identity import get_assistant_name, get_assistant_identifier, register_assistant
from src.init.utils import *

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"
os.environ["TORCH_LOGS"] = "-all"
ASSISTANT_INSTANCE_SERVER = f"Diego.{get_assistant_identifier().capitalize()}.Desktop"

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import *

from src.init.orb import Orb
from src.init.orb_subtitles import MascotSubtitleBubble
from src.init.audio_visualizer import AudioVisualizer
from src.init.worker import AssistantWorker, VoiceInputWorker
from src.init.chat import ChatInput
from src.init.indicators import (GitBranchIndicator, PrivacyIndicator,
                                 WorkingDirectory)
from src.init.visuals.workspace import Workspace, WorkspacePanel
from src.init.visuals.response import ResponseBridge


WORKSPACE_VIEW_CONFIG = {
    "logs": {
        "title": "Logs",
        "shortcut": "Ctrl+L",
        "icon": "",
    },
    "browser" : {
        "title": "Browser",
        "shortcut": "Ctrl+B",
        "icon": ""
    },
    "editor": {
        "title": "Editor",
        "shortcut": "Ctrl+E",
        "icon": "󰨞",
    },
    "settings": {
        "title": "Settings",
        "shortcut": "Ctrl+Alt+S",
        "icon": "",
    },
    "terminal": {
        "title": "Terminal",
        "shortcut": "Ctrl+T",
        "icon": "",
    },
}

from src.init.attachment_widgets import AttachmentTray
from src.init.attachments import DesktopMessage, DesktopVoiceMessage
from src.init.brain import kill_self
from src.init.config import DEFAULTS, HOME_PATH, load_dev_file, load_config
from src.init.editor.live import EditorView
from src.init.lang import get_language, set_language, tr
from src.init.logs import LogView
from src.init.settings import SettingsView

from src.init.voice_ipc import (
    WAKE_RECORD_REQUEST,
    ProcessLock,
    WakeInbox,
)

from src.init.desktop.capture import (
    CaptureRequest,
    capture_to_clipboard,
    register_capture_handler,
    unregister_capture_handler,
)

from src.init.desktop.clipboard import (
    ClipboardRequest,
    read_clipboard_on_gui_thread,
    register_clipboard_handler,
    unregister_clipboard_handler,
)
from src.init.desktop.task_progress import TaskProgressPill
from src.init.desktop.composition import CompositionLayout, CompositionSurface
from src.init.desktop.command_palette import Command, CommandPalette, CommandRegistry
from src.init.desktop.activity_trail import ActivityTrail
from src.init.desktop.task_presentation import TaskPresentation
from src.init.desktop.window import DesktopWindow
from src.init.desktop.zoom import ZoomView
from src.init.desktop.file_drop import FileDropRouter
from src.init.visuals.bridge import FlowchartBridge
from src.init.visuals.browser_bridge import BrowserBridge
from src.init.terminal import TerminalBridge

class ChatWorkspace(QWidget):
    request = Signal(int, object)
    username = getuser().capitalize()

    def __init__(self, session, host):
        super().__init__()
        self.setProperty("workspaceViewKey", "chat")
        self.setProperty("session_id", session.session_id)
        self.session = session
        session.workspace = self
        self.host = host
        self.workspace = host.workspace
        self.settings = host.settings
        self.muted = self.settings.value("muted", False, type=bool)
        self.subtitles_enabled = self.settings.value("subtitles", True, type=bool)
        orb_speech_pulse = self.settings.value("orb_speech_pulse", True, type=bool)
        self.mascot = host.mascot_projection(session)
        self.mascot_subtitles = host.subtitle_projection(session)
        self.main_workspace_panel_id = session.session_id
        self._dialogs = {}
        self.has_text = False
        self.recording = False
        self.voice_thread = None
        self.pending_voice_barge = False
        self.permission_denied_state = False
        self.pending_wake_barge = False
        self.closing_after_voice = False
        self.quitting = False
        self.send = QPushButton("")
        font = self.send.font()
        font.setPointSize(32 if self.send.text() == "" or "" else 11)
        self.send.setFont(font)
        self.greeting_key = f"greeting.{random.randrange(6)}"

        self.worker = AssistantWorker(session, self.startup_greeting, muted=self.muted)

        self.attach = QPushButton("")
        self.directory_indicator = WorkingDirectory(self)
        self.branch_indicator = GitBranchIndicator(self)
        self.privacy_indicator = PrivacyIndicator(self)

        self.privacy_indicator.clicked.connect(
            lambda: self.privacy_indicator.private_toggle(self.worker)
        )

        self.attachment_tray = AttachmentTray(load_config()["attachments"])
        self.submitting = None
        self.input = ChatInput()
        self.composer_widget = QWidget()
        self.input_meter = AudioVisualizer()
        self.input_meter.setMinimumWidth(0)
        self.input_meter.setFixedHeight(48)
        self.input_meter.hide()
        self.status = QLabel()
        self.task_presentation = TaskPresentation(self)
        self.activity_trail = ActivityTrail(
            self.task_presentation, steps_enabled=self.settings.value("ephemeral_steps", True, type=bool))
        self.command_output = QPlainTextEdit()
        self.active_language = None
        self.subtitles = QLabel(self.startup_greeting)

        self.orb = Orb(self, fill_ratio=0.54)
        self.orb.set_speech_pulse_enabled(orb_speech_pulse)

        self.thread = QThread(self)

        session.thread = self.thread
        self.log_dir = HOME_PATH / ".log"

        self.busy = False
        self.ready = False
        self.speaking = False
        self.stopping = False
        self.pending_prompt = None
        self.active_prompt = None
        self.paused_prompt = None
        self.task_stop_requested = False
        self.turn_id = 0
        self.status_key = "status.waking"
        self.showing_greeting = True
        self.current_reply = None
        self.current_response_view = None
        self._completed_git_diff = None
        self.response_timer = QElapsedTimer()
        self.response_timer_running = False
        self.response_timer_display = QLabel()
        self.response_timer_tick = QTimer(self)
        self.response_timer_tick.setInterval(50)
        self.response_timer_tick.timeout.connect(self._update_response_timer)
        self.subtitle_text = ""
        self._startup_reveal_animations = []
        self._workspace_hiding = False
        self._workspace_exit_ready = False
        self.wake_inbox = None
        self.wake_command_id = None

        self.build_ui()
        self.task_presentation.changed.connect(self.render_task_view)
        self.language_timer = QTimer(self)
        self.language_timer.setInterval(500)
        self.language_timer.timeout.connect(self.refresh_language)
        self.language_timer.start()
        self.build_worker()

    def build_ui(self):
        root = CompositionSurface()
        root.setObjectName("root")

        main = CompositionLayout(root)
        main.addWidget(self.orb)
        main.addWidget(self.activity_trail)

        self.status.setObjectName("status")
        self.status.setProperty("orbContext", True)
        self.status.setAlignment(Qt.AlignCenter)
        main.addWidget(self.status)

        self.subtitles.setObjectName("subtitles")
        self.subtitles.setAlignment(Qt.AlignCenter)
        self.subtitles.setWordWrap(True)
        self.subtitles.setTextFormat(Qt.RichText)
        self.subtitles.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.subtitles.setMinimumHeight(0)
        self.subtitles.setMaximumHeight(0)
        self.subtitles.setVisible(False)
        main.addWidget(self.subtitles)

        self.command_output.setObjectName("commandOutput")
        self.command_output.setReadOnly(True)
        self.command_output.setMinimumHeight(110)
        self.command_output.setMaximumHeight(220)
        self.command_output.hide()
        main.addWidget(self.command_output)

        composer_area = QVBoxLayout()
        composer_area.setSpacing(8)

        composer = QHBoxLayout()
        composer.setSpacing(12)

        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        input_frame.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred
        )
        input_frame.setMinimumHeight(48)
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(16, 0, 0, 0)
        input_layout.setSpacing(0)

        self.input.submitted.connect(self.send_message)
        input_layout.addWidget(self.input, 1, Qt.AlignVCenter)
        input_layout.addWidget(self.input_meter)
        input_layout.addWidget(self.attach, 0, Qt.AlignBottom)

        input_column = QVBoxLayout()
        input_column.setContentsMargins(0, 0, 0, 0)
        input_column.setSpacing(8)

        self.attachment_tray.setMinimumWidth(0)
        self.attachment_tray.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed)

        input_column.addWidget(self.attachment_tray)
        indicator_row = QHBoxLayout()
        indicator_row.setContentsMargins(0, 0, 0, 0)
        indicator_row.setSpacing(6)
        indicator_row.setAlignment(Qt.AlignVCenter)
        self.response_timer_display.setObjectName("responseTimer")
        self.response_timer_display.setAlignment(Qt.AlignCenter)
        self.response_timer_display.setText("0s")
        self.response_timer_display.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Fixed)
        indicator_row.addWidget(self.response_timer_display)
        indicator_row.addWidget(self.directory_indicator)
        indicator_row.addWidget(self.branch_indicator)
        indicator_row.addWidget(self.privacy_indicator)
        indicator_row.addStretch()
        self.indicator_row = QWidget()
        self.indicator_row.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.indicator_row.setLayout(indicator_row)
        self.indicator_row.setMaximumHeight(0)
        input_column.addWidget(self.indicator_row)
        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(12)
        input_row.addWidget(input_frame, 1)
        input_row.addWidget(self.send, 0, Qt.AlignVCenter)
        input_column.addLayout(input_row)

        input_group = QWidget()
        input_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.attachment_tray.changed.connect(self.update_send_button)

        self.attach.setObjectName("attach")
        self.attach.setFixedSize(48, 48)
        self.attach.clicked.connect(self.attachment_tray.choose_files)

        self.send.setObjectName("send")
        self.send.setFixedSize(48, 48)
        self.send.clicked.connect(self.on_send_clicked)
        self.send.hide()

        input_group.setLayout(input_column)
        self.input_group = input_group
        self.input_group.setMaximumHeight(0)
        self.input_group.setVisible(False)

        composer.addWidget(input_group, 1)

        composer_container = QWidget()
        composer_container.setLayout(composer)
        composer_container.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred
        )

        composer_row = QHBoxLayout()
        composer_row.setContentsMargins(20, 0, 20, 12)
        composer_row.setSpacing(0)

        composer_row.addStretch(1)
        composer_row.addWidget(composer_container, 2)
        composer_row.addStretch(1)

        composer_area.addLayout(composer_row)
        self.composer_widget.setLayout(composer_area)
        main.addWidget(self.composer_widget)

        self.input.textChanged.connect(self.update_send_button)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.task_progress = TaskProgressPill(self.task_presentation, self)
        layout.addWidget(root, 0, 0)
        layout.addWidget(self.task_progress, 0, 0, Qt.AlignLeft | Qt.AlignTop)
        self.set_enabled(False)
        self.refresh_language()


    def _poll_wake_commands(self):
        """Consume only when ready; preserve the composer and compact mode."""
        barge_candidate = self.busy and not self.stopping
        if (not self.ready or (self.busy and not barge_candidate) or
                self.voice_thread is not None or self.submitting is not None or
                (self.pending_prompt is not None and not barge_candidate) or
                self.closing_after_voice or self.worker.assistant.shutdown_requested.is_set()):
            return
        try:
            if self.wake_inbox is None:
                self.wake_inbox = WakeInbox()
            command = self.wake_inbox.claim()
        except Exception:
            logging.getLogger("assistant.wake").exception(
                "Wake inbox unavailable; will retry")
            return
        if command is None:
            return
        command_id, text = command
        if text == WAKE_RECORD_REQUEST or text.partition("://")[2] == "voice/start-recording":
            self.wake_command_id = command_id
            if barge_candidate:
                self.pending_wake_barge = True
                self.pending_prompt = None
                self.stop_response()
                return
            self.start_recording(automatic=True)
            self.finish_wake_command(
                "completed" if self.recording else "failed",
                "" if self.recording else "Recording was unavailable",
            )
            return
        self.wake_command_id = command_id
        self.start_prompt(DesktopMessage(text))


    def finish_wake_command(self, state, detail=""):
        command_id, self.wake_command_id = self.wake_command_id, None
        if command_id is not None:
            try:
                self.wake_inbox.finish(command_id, state, detail)
            except Exception:
                logging.getLogger("assistant.wake").exception(
                    "Wake acknowledgement failed")


    def workspace_content(self) -> QWidget:
        """Create navigation controls for a manually opened workspace."""
        content = QWidget()
        content.setObjectName("manualWorkspaceContent")
        content.setProperty("workspaceEmpty", True)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        navigation = QHBoxLayout()
        navigation.setContentsMargins(0, 0, 0, 0)
        navigation.setSpacing(8)

        buttons = [("󰭹", "chatNav", get_assistant_name(), None)]
        buttons.extend((options["icon"], f"{view_key}Nav", options["title"], view_key)
                       for view_key, options in WORKSPACE_VIEW_CONFIG.items())

        for icon, object_name, tooltip, view_key in buttons:
            button = QPushButton(icon, content)
            button.setObjectName(object_name)
            button.setFixedSize(48, 48)
            button.setToolTip(tooltip)
            button.setCursor(Qt.PointingHandCursor)
            if view_key is None:
                button.clicked.connect(self.focus_main_workspace)
            else:
                button.clicked.connect(
                    lambda checked=False, key=view_key, source=button:
                    self.open_workspace_view(key, source))
            navigation.addWidget(button)

        navigation.addStretch()
        layout.addLayout(navigation)
        placeholder = QLabel("Select a workspace type", content)
        placeholder.setObjectName("workspacePlaceholderLabel")
        placeholder.setAlignment(Qt.AlignCenter)
        layout.addWidget(placeholder, 1)
        return content


    def _update_response_timer(self):
        if not self.response_timer_running:
            return
        self.response_timer_display.setText(self._response_timer_text())


    def _response_timer_text(self):
        total_seconds = self.response_timer.elapsed() // 1000
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"


    def _start_response_timer(self):
        self.response_timer.start()
        self.response_timer_running = True
        self.response_timer_display.setText("0s")
        self.response_timer_tick.start()


    def _stop_response_timer(self):
        if self.response_timer_running:
            self._update_response_timer()
        self.response_timer_running = False
        self.response_timer_tick.stop()


    def _reset_response_timer(self):
        self.response_timer_running = False
        self.response_timer_tick.stop()
        self.response_timer_display.setText("0s")


    def focus_main_workspace(self):
        self.workspace.focus_panel(self.main_workspace_panel_id)
        if self.ready:
            self.input.setFocus()


    @property
    def startup_greeting(self) -> str:
        return tr(self.greeting_key, username=self.username, name=get_assistant_name())


    def set_orbs_thinking(self, thinking: bool):
        for orb in (self.orb, self.mascot):
            orb.set_thinking(thinking)


    @Slot()
    def open_workspace(self, direction: Qt.Key | None = None) -> None:
        """Open a manually created workspace from the main window."""
        try:
            before = set(self.workspace.panel_ids)
            self.workspace._open_shortcut_panel(direction=direction)
            self._own_new_panels(before)
        except Exception:
            logging.getLogger("assistant.workspace").exception(
                "Failed to open a workspace")
            raise


    def _workspace_view_factory(self, view_key: str) -> QWidget:
        """Create a fresh view instance for one workspace panel."""
        if view_key == "logs":
            return LogView(self.log_dir, session_id=self.session.session_id)
        if view_key == "editor":
            return EditorView(directory=self.session.working_directory)
        if view_key == "terminal":
            from src.init.terminal import TerminalView
            return TerminalView(directory=self.session.working_directory)
        if view_key == "browser":
            from src.init.visuals.browser import BrowserView
            return BrowserView()
        if view_key == "settings":
            view = SettingsView(
                self.subtitles_enabled,
                self.settings.value("orb_speech_pulse", True, type=bool),
                muted=self.muted,
                ephemeral_steps_enabled=self.settings.value("ephemeral_steps", True, type=bool))
            view.setProperty("session_id", self.session.session_id)
            view.mute_changed.connect(self.toggle_mute)
            view.subtitles_changed.connect(self.toggle_subtitles)
            view.orb_pulse_changed.connect(self.toggle_orb_speech_pulse)
            view.ephemeral_steps_changed.connect(self.toggle_ephemeral_steps)
            view.language_changed.connect(self.change_language)
            return view
        raise ValueError(f"Unknown workspace view: {view_key}")


    def open_workspace_view(self, view_key: str, source=None) -> None:
        """Open or replace a configured view in the embedded workspace."""
        options = WORKSPACE_VIEW_CONFIG.get(view_key)
        if options is None:
            raise ValueError(f"Unknown workspace view: {view_key}")
        sender = source
        panel = None
        while sender is not None:
            if isinstance(sender, WorkspacePanel):
                panel = sender
                break
            sender = sender.parentWidget()
        if panel is not None:
            try:
                content = self._workspace_view_factory(view_key)
                content.setProperty("workspaceViewKey", view_key)
                panel.set_title(options["title"])
                panel.set_content(content)
                self.workspace.focus_panel(panel.panel_id)
                panel.setProperty("session_id", self.session.session_id)
            except Exception:
                logging.getLogger("assistant.workspace").exception(
                    "Failed to replace workspace view %s", view_key)
            return
        count = getattr(self, "_workspace_view_counts", {}).get(view_key, 0) + 1
        if not hasattr(self, "_workspace_view_counts"):
            self._workspace_view_counts = {}
        self._workspace_view_counts[view_key] = count
        title = options["title"] if count == 1 else f"{options['title']} {count}"
        try:
            before = set(self.workspace.panel_ids)
            self.workspace.open_registered_panel(
                view_key,
                title,
                lambda: self._workspace_view_factory(view_key))
            self._own_new_panels(before)
        except Exception:
            logging.getLogger("assistant.workspace").exception(
                "Failed to open workspace view %s", view_key)
            return


    def open_terminal_command(self, command: str) -> None:
        from src.init.terminal import TerminalView
        view = TerminalView(directory=self.session.working_directory, command=command,
                            preserve_output=True, autostart=False)
        try:
            before = set(self.workspace.panel_ids)
            self.workspace.open_registered_panel("terminal", "Terminal", lambda: view)
            self._own_new_panels(before)
            view.start_session()
        except Exception:
            view.dispose()
            if view.parentWidget() is None:
                view.deleteLater()
            raise


    def _own_new_panels(self, before):
        for panel_id in set(self.workspace.panel_ids) - before:
            panel = self.workspace.get_panel(panel_id)
            panel.setProperty("session_id", self.session.session_id)

    def on_confirmation_requested(self, turn_id, request_id, message):
        if turn_id != self.turn_id or self.stopping:
            self.worker.resolve_confirmation(False, request_id)
            return
        self.task_presentation.awaiting_permission(turn_id)
        dialog = QMessageBox(self.host)
        dialog.setWindowTitle(tr("command.title"))
        dialog.setIcon(QMessageBox.Question)
        dialog.setText(tr("command.request"))
        dialog.setInformativeText(message)
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dialog.setDefaultButton(QMessageBox.No)
        dialog.setModal(False)
        self._dialogs[request_id] = dialog
        identity = (self.session.session_id, turn_id)
        def answered(result):
            self._dialogs.pop(request_id, None)
            if self.session.accepts(*identity):
                self.task_presentation.awaiting_permission(turn_id, waiting=False)
                self.worker.resolve_confirmation(result == QMessageBox.Yes, request_id)
            dialog.deleteLater()
        dialog.finished.connect(answered)
        dialog.show()

    def set_status(self, key):
        self.status_key = key
        self.status.setText(tr(key) if key else "")
        self.status.setVisible(bool(key))


    def set_enabled(self, enabled):
        self.input.setEnabled(enabled and self.submitting is None)
        self.update_send_button()


    def update_send_button(self):
        self.has_text = bool(self.input.toPlainText().strip())
        voice_active = self.voice_thread is not None
        live_active = voice_active and self.voice_thread.live
        stopping_available = self.busy and self.speaking and not self.stopping
        self.send.setText("" if stopping_available or self.recording or live_active else
                          "" if self.has_text else "")

        font = self.send.font()
        font.setPointSize(32 if self.send.text() == "" or "" else 12)
        self.send.setFont(font)

        self.send.setEnabled(
            self.ready and (live_active or self.recording or stopping_available or (
                    not voice_active and not self.busy and
                    self.submitting is None and self.attachment_tray.can_send)))
        editable = self.ready and self.submitting is None and not voice_active
        self.attach.setEnabled(editable)
        self.attachment_tray.setEnabled(editable)
        self.input.setEnabled(editable)
        self.attach.setToolTip(tr("ui.attach_files"))
        self.attach.setAccessibleName(tr("ui.attach_files"))
        key = ("ui.stop" if stopping_available or self.recording or live_active else
               "ui.send" if self.has_text else "voice.record")
        label = tr(key)
        self.send.setAccessibleName(label)
        self.send.setToolTip(
            tr("ui.stop_hint") if stopping_available else label)
        self.input.setPlaceholderText(
            tr("ui.steering_input" if self.busy else "ui.input"))


    @Slot(str)
    def change_language(self, language):
        try:
            set_language(language)
        except (OSError, ValueError) as error:
            self.refresh_settings_workspaces()
            QMessageBox.warning(self, tr("ui.settings"),
                                tr("ui.error", error=error))
            return
        self.refresh_language()


    def refresh_language(self):
        language = get_language()
        name = get_assistant_name()
        if language == self.active_language and name == getattr(self, "active_assistant_name", None):
            return
        self.active_language = language
        self.active_assistant_name = name
        title = f"{name} {load_dev_file()['version']}"
        self.host.setWindowTitle(title)
        if hasattr(self, "workspace"):
            panel = self.workspace.get_panel(getattr(self, "main_workspace_panel_id", "main"))
            if panel is not None:
                panel.set_title(title)
        tray = getattr(self, "tray_icon", None)
        if tray is not None:
            tray.setToolTip(tr("tray.running"))
            actions = tray.contextMenu().actions()
            actions[0].setText(tr("tray.open"))
            actions[1].setText(tr("tray.quit"))
        for orb in (self.orb, self.mascot):
            orb.setToolTip(name)
        chat = self.findChild(QPushButton, "chatNav")
        if chat is not None:
            chat.setToolTip(name)
        self.host.command_palette.refresh_language()
        self.task_progress.refresh_language(language)
        self.activity_trail.refresh_language(language)
        self.refresh_settings_workspaces()
        self.attachment_tray.refresh()
        self.set_status(self.status_key)
        self.update_send_button()
        if self.showing_greeting:
            self.update_subtitles(self.startup_greeting)


    def refresh_settings_workspaces(self):
        for view in self.workspace.findChildren(SettingsView):
            if view.property("session_id") != self.session.session_id:
                continue
            with QSignalBlocker(view.mute_switch):
                view.mute_switch.setChecked(self.muted)
            with QSignalBlocker(view.subtitles_switch):
                view.subtitles_switch.setChecked(self.subtitles_enabled)
            with QSignalBlocker(view.orb_pulse_switch):
                view.orb_pulse_switch.setChecked(
                    self.settings.value("orb_speech_pulse", True, type=bool))
            with QSignalBlocker(view.ephemeral_steps_switch):
                view.ephemeral_steps_switch.setChecked(
                    self.settings.value("ephemeral_steps", True, type=bool))
            view.refresh_language()


    def refresh_privacy_indicator(self):
        private = self.worker.session.private
        self.privacy_indicator.setVisible(private)


    def refresh_directory_indicators(self):
        directory = self.session.working_directory
        self.directory_indicator.set_directory(directory)
        self.branch_indicator.set_directory(directory)


    @Slot()
    def on_ready(self):
        self.ready = True
        self.set_status("")
        self.set_orbs_visual_state(Orb.State.IDLE)
        self.set_enabled(True)
        self._reveal_startup_controls()

        if self.host.session_manager.focused_session is self.session and self.host.isVisible():
            self.input.setFocus()


    def _reveal_startup_controls(self):
        """Slide the composer and subtitles into view after startup."""
        for animation in self._startup_reveal_animations:
            animation.stop()
            animation.deleteLater()
        self._startup_reveal_animations.clear()

        self.input_group.setVisible(True)
        self.indicator_row.setVisible(True)
        self.send.setVisible(True)
        self.subtitles.setVisible(self.subtitles_enabled)
        self.subtitles.setMaximumHeight(0)

        indicator_target = self.indicator_row.sizeHint().height()
        input_target = max(self.input_group.sizeHint().height()
                           + indicator_target, 48)
        subtitle_target = 90
        targets = (
            (self.input_group, input_target),
            (self.indicator_row, indicator_target),
            (self.subtitles, subtitle_target),
        )
        for widget, target in targets:
            animation = QPropertyAnimation(widget, b"maximumHeight", self)
            animation.setDuration(260)
            animation.setStartValue(0)
            animation.setEndValue(target)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            animation.finished.connect(
                lambda widget=widget: widget.setMaximumHeight(16777215))
            animation.start()
            self._startup_reveal_animations.append(animation)


    @Slot(bool)
    def toggle_subtitles(self, enabled: bool):
        self.subtitles_enabled = enabled
        self.subtitles.setVisible(enabled and self.ready)
        self.sync_mascot_subtitle()
        self.settings.setValue("subtitles", enabled)
        self.refresh_settings_workspaces()


    @Slot(bool)
    def toggle_mute(self, muted: bool):
        self.muted = bool(muted)
        self.settings.setValue("muted", self.muted)
        try:
            self.worker.set_muted(self.muted)
        except Exception as error:
            QMessageBox.warning(self, tr("ui.mute"), str(error))
        if self.muted:
            self.on_speaking(self.turn_id, False)
            self.orb.clear()
            self.mascot.clear()
        self.refresh_settings_workspaces()


    def toggle_orb_speech_pulse(self, enabled: bool):
        for orb in (self.orb, self.mascot):
            orb.set_speech_pulse_enabled(enabled)
        self.settings.setValue("orb_speech_pulse", enabled)
        self.refresh_settings_workspaces()


    @Slot(bool)
    def toggle_ephemeral_steps(self, enabled: bool):
        self.activity_trail.set_steps_enabled(enabled)
        self.settings.setValue("ephemeral_steps", enabled)
        self.refresh_settings_workspaces()


    def set_orbs_speaking(self, speaking: bool):
        for orb in (self.orb, self.mascot):
            orb.set_speaking(speaking)
        self.sync_mascot_subtitle()


    def set_orbs_listening(self, listening: bool):
        for orb in (self.orb, self.mascot):
            orb.set_listening(listening)


    def set_orbs_visual_state(self, state, *, fade_in=180, fade_out=180):
        for orb in (self.orb, self.mascot):
            orb.set_visual_state(state, fade_in=fade_in, fade_out=fade_out)


    def sync_mascot_subtitle(self):
        self.mascot_subtitles.set_subtitle(
            self.subtitle_text,
            self.subtitles_enabled and self.speaking)


    def update_subtitles(self, text):
        from PySide6.QtGui import QTextLayout
        self.subtitle_text = text
        font = self.subtitles.font()
        metrics = QFontMetrics(font)
        max_width = metrics.horizontalAdvance("M" * 56)
        available = max(1, self.subtitles.contentsRect().width() - 24)

        width = min(max_width, available)
        lines = []

        for paragraph in text.split("\n"):
            if not paragraph:
                lines.append("")
                continue

            layout = QTextLayout(paragraph, font)
            layout.beginLayout()
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break

                line.setLineWidth(width)
                start = line.textStart()
                end = start + line.textLength()
                lines.append(paragraph[start:end])
            layout.endLayout()

        self.subtitles.setText(self.render_subtitle("\n".join(lines[-3:])))
        self.sync_mascot_subtitle()


    @staticmethod
    def render_subtitle(text: str) -> str:
        """Enbold the font without rendering Markdown **"""
        escaped = html.escape(text)
        return (re.sub(r"\*\*(.+?)\*\*",
                       r"<b>\1</b>", escaped, flags=re.DOTALL, )
                .replace("\n", "<br>"))


    @Slot()
    def send_message(self):
        if not self.ready or self.voice_thread is not None:
            return

        if self.submitting is not None or not self.attachment_tray.can_send:
            return
        message = DesktopMessage(
            self.input.toPlainText().strip(), self.attachment_tray.snapshot())
        if not message.text and not message.attachments:
            return
        if self.busy and self.stopping:
            return
        self.submitting = message
        self.update_send_button()
        if self.busy:
            self.pending_prompt = message
            self.stop_response()
            return
        self.start_prompt(message)


    @Slot(int)
    def on_request_accepted(self, turn_id):
        if turn_id != self.turn_id or self.submitting is None:
            return

        self.input.clear()
        self.attachment_tray.clear()
        self.submitting = None
        self.update_send_button()


    @Slot(int, str)
    def on_request_rejected(self, turn_id, error):
        if turn_id != self.turn_id:
            return

        self._reset_response_timer()
        self.task_presentation.finish(turn_id, failed=True)
        self.finish_wake_command("failed", error)
        self.submitting = None
        self.busy = False
        if self.voice_thread is None:
            self.host.audio.release(self.session)
        self.current_reply = None
        if self.voice_thread is not None and self.voice_thread.live:
            self.voice_thread.stop_event.set()
        self.update_send_button()
        QMessageBox.warning(self, tr("ui.attach_files"), error)


    @Slot()
    def on_mascot_record(self):
        """Start or stop microphone recording from compact mode."""
        if self.recording or self.voice_thread is not None:
            self.on_send_clicked()
            return

        if self.busy and self.speaking and not self.stopping:
            self.pending_voice_barge = True
            self.stop_response()
            return

        if (not self.ready or self.busy or
                self.voice_thread is not None):
            return

        self.start_recording()


    def start_prompt(self, prompt):
        self.active_prompt = prompt
        self.paused_prompt = None
        self.task_stop_requested = False
        self.set_status("")
        self.turn_id += 1
        self.session.turn_id = self.turn_id
        if self.host.session_manager.focused_session is self.session or self.host.session_manager.desktop_session is self.session:
            self.host.session_manager.acquire_voice(self.session)
        self.task_presentation.begin(self.turn_id)
        self.showing_greeting = False
        self.worker.cancel_event = threading.Event()
        self.stopping = False
        self.permission_denied_state = False
        self.speaking = False

        self.command_output.hide()
        self.command_output.clear()

        self.current_reply = ""
        self.current_response_view = None
        self._start_response_timer()
        self.update_subtitles(prompt.display_text)

        self.busy = True
        self.set_enabled(True)

        try:
            if not self.thread.isRunning():
                raise RuntimeError(tr("ui.worker_unavailable"))
            self.request.emit(self.turn_id, prompt)
        except Exception as error:
            self.on_request_rejected(self.turn_id, str(error))


    @Slot()
    def on_send_clicked(self):
        if self.voice_thread is not None and self.voice_thread.live:
            self.voice_thread.stop_event.set()
            if isinstance(self.pending_prompt, DesktopVoiceMessage):
                self.pending_prompt = None
            if self.busy and not self.stopping:
                self.stop_response()
            self.recording = False
            self.set_orbs_listening(False)
            self.update_send_button()
        elif self.recording:
            self.voice_thread.stop_event.set()
            self.recording = False
            self.update_send_button()
        elif self.voice_thread is not None:
            return
        elif self.busy:
            if self.speaking and not self.stopping:
                self.pending_voice_barge = True
                self.stop_response()
        elif self.has_text:
            self.send_message()
        else:
            self.start_recording()


    def start_recording(self, *, automatic=False):
        if (not self.ready or self.busy or self.submitting is not None or
                self.voice_thread is not None):
            return
        if not self.host.session_manager.acquire_voice(self.session):
            self.set_status("sessions.audio_busy")
            return
        if not self.worker.assistant.voice.supports_playback_reference:
            self.host.audio.release(self.session)
            self.status.setText(tr("voice.restart"))
            self.status.show()
            return
        try:
            self.worker.assistant.voice.set_playback_reference(True)
        except RuntimeError as error:
            self.host.audio.release(self.session)
            self.status.setText(str(error))
            self.status.show()
            return
        self.voice_thread = VoiceInputWorker(self, automatic=True, live=True)
        self.worker.live_capture = self.voice_thread
        self.voice_thread.levels.connect(self.on_voice_levels)
        self.voice_thread.processing.connect(self.on_voice_processing)
        self.voice_thread.speech_started.connect(self.on_voice_started)
        self.voice_thread.utterance.connect(self.on_voice_utterance)
        self.voice_thread.finished.connect(self.on_voice_finished)
        self.recording = True
        self.set_orbs_visual_state(Orb.State.WRITING)
        self.set_orbs_listening(True)
        self.input.hide()
        self.input_meter.clear()
        self.input_meter.show()
        self.set_orbs_thinking(False)
        self.update_send_button()
        self.voice_thread.start()


    @Slot(object)
    def on_voice_levels(self, levels):
        if not self.busy or self.stopping:
            self.input_meter.set_levels(levels)
            self.mascot.set_levels(levels)
            self.orb.set_levels(levels)


    @Slot()
    def on_voice_started(self):
        if self.voice_thread is None or self.voice_thread.stop_event.is_set():
            return
        if self.busy and not self.stopping:
            self.stop_response()
        self.recording = True
        self.set_orbs_listening(True)
        self.set_orbs_visual_state(Orb.State.WRITING)
        self.input.hide()
        self.input_meter.show()


    @Slot(object)
    def on_voice_utterance(self, message):
        if (self.quitting or self.voice_thread is None or
                self.voice_thread.stop_event.is_set()):
            return
        if self.busy:
            self.pending_prompt = message
            if not self.stopping:
                self.stop_response()
        else:
            self.start_prompt(message)


    def resume_live_listening(self):
        if (self.voice_thread is None or not self.voice_thread.live or
                self.voice_thread.stop_event.is_set() or self.busy or self.quitting):
            return
        self.voice_thread.waiting_response.clear()
        self.recording = True
        self.set_orbs_visual_state(Orb.State.WRITING)
        self.set_orbs_listening(True)
        self.input.hide()
        self.input_meter.show()
        self.update_send_button()


    @Slot()
    def on_voice_processing(self):
        self.recording = False
        self.set_orbs_visual_state(Orb.State.PROCESSING)
        self.set_orbs_listening(False)
        self.input_meter.hide()
        self.mascot.clear()
        self.input.show()
        self.update_send_button()


    @Slot()
    def on_voice_finished(self):
        worker = self.voice_thread
        if worker is None:
            return
        self.voice_thread = None
        self.worker.live_capture = None
        try:
            self.worker.assistant.voice.set_playback_reference(False)
        except RuntimeError:
            logging.getLogger("assistant.voice").exception("Unable to stop playback reference")
        self.recording = False
        self.set_orbs_listening(False)
        self.input_meter.hide()
        self.input_meter.clear()
        self.mascot.clear()
        self.input.show()
        worker.deleteLater()
        self.update_send_button()
        if self.closing_after_voice:
            self.host.close_session(self.session)
            return
        if not self.busy:
            self.host.audio.release(self.session)
        if worker.error:
            self.status.setText(worker.error)
            self.status.show()
        elif worker.audio_wav and not worker.live:
            self.start_prompt(DesktopVoiceMessage(worker.audio_wav,
                                                  worker.transcript))

        if self.host.session_manager.focused_session is self.session and self.host.isVisible():
            self.input.setFocus()


    def can_resume_task(self):
        return (self.ready and self.paused_prompt is not None and not self.busy
                and not self.stopping and not self.recording and self.voice_thread is None
                and self.submitting is None and self.pending_prompt is None and not self.quitting)


    def pause_current_task(self):
        if not self.ready or not self.busy or self.stopping:
            return
        self.paused_prompt = self.active_prompt
        self.stop_response()


    def cancel_current_task(self):
        from src.init.task_state import Lifecycle

        controller = getattr(self.worker.assistant, "_active_task_controller", None)
        if controller is not None and controller.state.status in {
                Lifecycle.INTERRUPTED, Lifecycle.WAITING, Lifecycle.BLOCKED, Lifecycle.LIMIT_REACHED}:
            controller.state.suspend(Lifecycle.CANCELLED, "Stopped by the user.")
            self.worker.assistant._active_task_controller = None
        self.task_stop_requested = False


    def stop_current_task(self):
        if not self.ready or not (self.busy or self.paused_prompt is not None):
            return
        self.paused_prompt = None
        self.task_stop_requested = True
        self.set_status("")
        if self.busy:
            if not self.stopping:
                self.stop_response()
        else:
            self.cancel_current_task()


    def resume_current_task(self):
        if not self.can_resume_task():
            return
        prompt = self.paused_prompt
        controller = getattr(self.worker.assistant, "_active_task_controller", None)
        if (controller is not None and controller.state.requests
                and controller.state.status in {"interrupted", "waiting", "blocked", "limit_reached"}):
            prompt = DesktopMessage(tr("palette.resume_prompt"), prompt.attachments)
        self.start_prompt(prompt)


    def stop_response(self):
        self._stop_response_timer()
        self.stopping = True
        self.task_presentation.finish(self.turn_id, interrupted=True)
        self.worker.interrupt()
        self.speaking = False
        self.orb.clear()
        self.set_orbs_speaking(False)
        self.set_orbs_thinking(False)
        self.update_send_button()


    @Slot()
    def capture_screen(self):
        try:
            success = capture_to_clipboard()
            if success:
                self.mascot.setToolTip("Check!")
            else:
                self.mascot.setToolTip(":(")

        except Exception as error:
            self.mascot.setToolTip(f"{error}")


    @Slot(object)
    def render_task_view(self, view):
        self.set_orbs_thinking(view.active and view.orb_state == Orb.State.PROCESSING)
        self.set_orbs_visual_state(view.orb_state)


    @Slot(int)
    def on_permission_denied(self, turn_id):
        if turn_id == self.turn_id:
            self.permission_denied_state = True
            self.task_presentation.permission_denied(turn_id)


    @Slot(int, str)
    def on_chunk(self, turn_id, chunk):
        if turn_id != self.turn_id or self.current_reply is None:
            return

        self.current_reply += chunk
        if not self.speaking:
            self.update_subtitles(self.current_reply)
        if self.current_response_view is not None:
            self.current_response_view.append_chunk(chunk)
        self.task_presentation.writing(turn_id)


    def _forget_response_view(self, response_view):
        if self.current_response_view is response_view:
            self.current_response_view = None


    @Slot(int, str)
    def on_subtitle(self, turn_id, text):
        if turn_id == self.turn_id and not self.stopping:
            self.update_subtitles(text)


    @Slot(int, object)
    def on_audio(self, turn_id, levels):
        if self.muted:
            return
        if (turn_id == self.turn_id and (self.busy or not self.ready)
                and not self.stopping):
            self.mascot.set_levels(levels)
            self.orb.set_levels(levels)


    @Slot(int, bool)
    def on_speaking(self, turn_id, speaking):
        if turn_id != self.turn_id:
            return
        self.speaking = (speaking and not self.muted and (self.busy or not self.ready)
                         and not self.stopping)
        if not self.ready:
            self.set_orbs_visual_state(Orb.State.READING if self.speaking else Orb.State.IDLE)
        else:
            self.task_presentation.speaking(turn_id, self.speaking)

        self.set_orbs_speaking(self.speaking)

        self.update_send_button()


    @Slot(str)
    def on_finished(self, reply):
        self._stop_response_timer()
        interrupted = self.stopping
        if self.current_response_view is not None:
            self.current_response_view.finish(reply)
        self.task_presentation.finish(self.turn_id, interrupted=interrupted,
                                      failed=self.permission_denied_state)
        task_state = getattr(self.worker.assistant, "task_state", None)
        if self.paused_prompt is not None and (
                task_state is not None and task_state.status == "complete" or task_state is None and reply):
            self.paused_prompt = None
        if self.task_stop_requested:
            self.cancel_current_task()
        task_failed = self.task_presentation.view.state in {"error", "waiting", "stopped"}
        self.finish_wake_command("failed" if interrupted or task_failed else "completed",
                                 "Interrupted" if interrupted else
                                 task_state.notice if task_failed and task_state is not None else
                                 tr("task_progress.error") if task_failed else "")
        if self.worker.command_reply:
            self.command_output.setPlainText(reply)
            self.command_output.show()
            self.update_subtitles(reply.splitlines()[0])
        elif not self.current_reply:
            self.update_subtitles(reply or tr("status.paused" if self.paused_prompt is not None else
                                              "status.stopped" if interrupted else "ui.no_response"))
        else:
            self.update_subtitles("")

        self.current_reply = None
        self.current_response_view = None
        self.busy = False
        if self.voice_thread is None:
            self.host.audio.release(self.session)
        self.speaking = False
        self.stopping = False
        if self.paused_prompt is not None:
            self.set_status("status.paused")
        self.orb.clear()
        self.set_orbs_speaking(False)
        self.set_orbs_thinking(False)
        QTimer.singleShot(700, lambda turn_id=self.turn_id: self.task_presentation.settle(turn_id) if not self.session.closing else None)
        self.refresh_privacy_indicator()
        self.set_enabled(True)
        if self.host.session_manager.focused_session is self.session and self.host.isVisible():
            self.input.setFocus()

        if self.worker.assistant.shutdown_requested.is_set():
            self.quitting = True
            QTimer.singleShot(0, self.request_quit)
            return

        snapshot, self._completed_git_diff = self._completed_git_diff, None
        if snapshot is not None and not interrupted and not task_failed:
            from src.init.visuals.diff_workspace import DiffWorkspacePanel
            directory, diff = snapshot
            self.host.open_owned_panel(self.session.session_id, self.turn_id,
                tr("git_workspace.title"), DiffWorkspacePanel(directory, diff), "git_diff")

        if self.pending_wake_barge:
            self.pending_wake_barge = False
            self.start_recording(automatic=True)
            self.finish_wake_command(
                "completed" if self.recording else "failed",
                "" if self.recording else "Recording was unavailable",
            )
        elif self.pending_voice_barge:
            self.pending_voice_barge = False
            QTimer.singleShot(0, self.start_recording)
        else:
            self.resume_pending_prompt()
            self.resume_live_listening()
        if self.quitting:
            QTimer.singleShot(0, lambda: self.host.close_session(self.session))


    @Slot(str, str)
    def on_git_diff_ready(self, directory, diff):
        self._completed_git_diff = (directory, diff)


    def resume_pending_prompt(self):
        if self.worker.assistant.shutdown_requested.is_set():
            self.pending_prompt = None
            return
        prompt, self.pending_prompt = self.pending_prompt, None
        if prompt:
            self.start_prompt(prompt)


    @Slot(str)
    def on_error(self, error):
        if self.voice_thread is not None and self.voice_thread.live:
            self.voice_thread.stop_event.set()
        if self.task_stop_requested:
            self.cancel_current_task()
        if not self.ready:
            self.status_key = ""
            self.status.setText(tr("ui.error", error=error))
            self.status.show()

        self._reset_response_timer()
        self.task_presentation.finish(self.turn_id, failed=True)
        self.finish_wake_command("failed", error)
        self.showing_greeting = False
        self.update_subtitles(tr("ui.error", error=error))
        self.current_reply = None
        if self.current_response_view is not None:
            self.current_response_view.finish()
        self.current_response_view = None
        self.busy = False
        if self.voice_thread is None:
            self.host.audio.release(self.session)
        self.speaking = False
        self.stopping = False
        self.orb.clear()
        self.set_orbs_speaking(False)
        self.set_orbs_thinking(False)
        if not self.ready:
            self.set_orbs_visual_state(Orb.State.DENIED_ERROR, fade_in=100, fade_out=300)
        QTimer.singleShot(700, lambda turn_id=self.turn_id: self.task_presentation.settle(turn_id) if not self.session.closing else None)

        self.set_enabled(self.ready)
        if self.pending_wake_barge:
            self.pending_wake_barge = False
            self.start_recording(automatic=True)
            self.finish_wake_command(
                "completed" if self.recording else "failed",
                "" if self.recording else "Recording was unavailable",
            )
        elif self.pending_voice_barge:
            self.pending_voice_barge = False
            QTimer.singleShot(0, self.start_recording)
        else:
            self.resume_pending_prompt()
        if self.quitting:
            QTimer.singleShot(0, lambda: self.host.close_session(self.session))

    def build_worker(self):
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.initialize)
        self.request.connect(self.worker.ask)
        self.worker.event.connect(self.on_worker_event)
        self.thread.finished.connect(lambda: self.host.finish_session_close(self.session))
        self.worker.stopped.connect(self.on_worker_stopped)
        self.thread.start()

    @Slot(str)
    def on_worker_stopped(self, session_id):
        if session_id == self.session.session_id:
            self.thread.quit()

    @Slot(str, int, str, object)
    def on_worker_event(self, session_id, turn_id, name, values):
        if not self.session.accepts(session_id, turn_id):
            return
        handlers = {
            "chunk": lambda: self.on_chunk(turn_id, *values),
            "audio": lambda: self.on_audio(turn_id, *values),
            "speaking": lambda: self.on_speaking(turn_id, *values),
            "subtitle": lambda: self.on_subtitle(turn_id, *values),
            "phase": lambda: self.task_presentation.on_phase(turn_id, *values),
            "activity": lambda: self.task_presentation.on_activity(turn_id, *values),
            "task_title": lambda: self.task_presentation.set_task_title(turn_id, *values),
            "permission_denied": lambda: self.on_permission_denied(turn_id),
            "accepted": lambda: self.on_request_accepted(turn_id),
            "rejected": lambda: self.on_request_rejected(turn_id, *values),
            "finished": lambda: self.on_finished(*values),
            "failed": lambda: self.on_error(*values),
            "directory": lambda: self.directory_indicator.set_directory(*values),
            "git_diff_ready": lambda: self.on_git_diff_ready(*values),
            "ready": self.on_ready,
            "confirmation_requested": lambda: self.on_confirmation_requested(turn_id, *values),
            "exit_requested": self.host.request_quit,
        }
        handler = handlers.get(name)
        if handler is not None:
            handler()

    def focus_main_workspace(self):
        self.host.focus_session(self.session)

    def open_command_palette(self):
        self.host.open_command_palette()

    def show_mascot(self):
        self.host.show_mascot(self.session)

    def restore_from_mascot(self):
        self.host.focus_session(self.session)

    def request_quit(self):
        self.host.request_quit()

    def poll_wake_commands(self):
        if self.host.session_manager.desktop_session is self.session:
            self._poll_wake_commands()

    def dispose(self):
        self.host.close_session(self.session)

    def stop_for_close(self):
        self.language_timer.stop()
        self.response_timer_tick.stop()
        for dialog in tuple(self._dialogs.values()):
            dialog.reject()
        self._dialogs.clear()
        self.worker.interrupt()
        if self.voice_thread is not None:
            self.voice_thread.stop_event.set()
            self.voice_thread.requestInterruption()
        QMetaObject.invokeMethod(self.worker, "shutdown", Qt.QueuedConnection)
