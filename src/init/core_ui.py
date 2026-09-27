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

from src.init.identity import register_assistant
from src.init.utils import *

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"
os.environ["TORCH_LOGS"] = "-all"
ARLO_INSTANCE_SERVER = "Diego.Arlo.Desktop"

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
from src.init.config import load_dev_file, load_config
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
from src.init.desktop.window import DesktopWindow
from src.init.desktop.zoom import ZoomView
from src.init.desktop.file_drop import FileDropRouter
from src.init.visuals.bridge import FlowchartBridge
from src.init.visuals.browser_bridge import BrowserBridge
from src.init.terminal import TerminalBridge

# noinspection PyBroadException
class ArloWindow(DesktopWindow):
    """Arlo window class, not its brain, which is somewhere else"""
    request = Signal(int, object)
    username = getuser().capitalize()

    def __init__(self):
        super().__init__()
        log_path = Path(tempfile.gettempdir()) / "arlo" / "agent.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        root_logger = logging.getLogger()
        if not any(isinstance(handler, logging.FileHandler)
                and Path(handler.baseFilename) == log_path
                for handler in root_logger.handlers):
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            ))
            root_logger.addHandler(handler)

        root_logger.setLevel(logging.INFO)
        logging.getLogger("arlo.desktop").info(
            "Desktop backend logging initialized")

        self.settings = QSettings("ARLO", "desktop")
        self.muted = self.settings.value("muted", False, type=bool)
        subtitles_enabled = self.settings.value("subtitles", True, type=bool)
        orb_speech_pulse = self.settings.value("orb_speech_pulse", True, type=bool)
        self.setWindowTitle(f"ARLO {load_dev_file()["version"]}")
        icon_path = (Path(__file__).resolve().parent.parent.parent / "assets" / "arlo.ico")
        self.setWindowIcon(QIcon(str(icon_path)))

        self.mascot = Orb(size=120, floating=True, line_width=4.2, fill_ratio=0.54)
        self.mascot.set_speech_pulse_enabled(orb_speech_pulse)
        self.mascot.hide()
        self.mascot_subtitles = MascotSubtitleBubble(self.mascot)
        self.subtitles_enabled = subtitles_enabled

        self.mascot.record_requested.connect(self.on_mascot_record)
        self.mascot.restore_requested.connect(self.restore_from_mascot)
        self.mascot_shortcut = QShortcut(QKeySequence("Ctrl+Shift+M"), self)
        self.mascot_shortcut.activated.connect(self.show_mascot)

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

        self.worker = AssistantWorker(self.startup_greeting, muted=self.muted)
        register_assistant(lambda: self.worker.assistant)

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
        self.command_output = QPlainTextEdit()
        self.active_language = None
        self.subtitles = QLabel(self.startup_greeting)

        self.orb = Orb(self, fill_ratio=0.54)
        self.orb.set_speech_pulse_enabled(orb_speech_pulse)

        self.capture_handler = self.worker.screenshot_requested.emit
        register_capture_handler(self.capture_handler)
        self.clipboard_handler = self.worker.clipboard_requested.emit
        register_clipboard_handler(self.clipboard_handler)
        self.flowchart_bridge = FlowchartBridge(self)
        self.browser_bridge = BrowserBridge(self)
        self.terminal_bridge = TerminalBridge(self)
        self.response_bridge = ResponseBridge(self)
        self.thread = QThread(self)

        self.log_dir = Path.home() / ".arlo" / ".log"

        self.busy = False
        self.ready = False
        self.speaking = False
        self.stopping = False
        self.pending_prompt = None
        self.turn_id = 0
        self.status_key = "status.waking"
        self.showing_greeting = True
        self.current_reply = None
        self.current_response_view = None
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
        self.build_command_palette()

        self._workspace_shortcut_map = {
            options["shortcut"].rsplit("+", 1)[-1]: view_key
            for view_key, options in WORKSPACE_VIEW_CONFIG.items()
        }
        self._workspace_shortcuts = []
        for view_key, options in WORKSPACE_VIEW_CONFIG.items():
            shortcut = QShortcut(QKeySequence(options["shortcut"]), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(
                lambda view_key=view_key: self.open_workspace_view(view_key))
            self._workspace_shortcuts.append(shortcut)

        self._workspace_chord_pending = False
        self._workspace_chord_timer = QTimer(self)
        self._workspace_chord_timer.setSingleShot(True)
        self._workspace_chord_timer.setInterval(700)
        self._workspace_chord_timer.timeout.connect(
            self._open_pending_workspace)
        QApplication.instance().installEventFilter(self)

        self.build_worker()
        self.set_status("status.waking")
        self.language_timer = QTimer(self)
        self.language_timer.setInterval(500)
        self.language_timer.timeout.connect(self.refresh_language)
        self.language_timer.start()
        self.directory_timer = QTimer(self)
        self.directory_timer.setInterval(250)
        self.directory_timer.timeout.connect(
            self.refresh_directory_indicators)
        self.directory_timer.start()
        self.wake_timer = QTimer(self)
        self.wake_timer.setInterval(250)
        self.wake_timer.timeout.connect(self.poll_wake_commands)
        self.wake_timer.start()

    def poll_wake_commands(self):
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
            logging.getLogger("arlo.wake").exception(
                "Wake inbox unavailable; will retry")
            return
        if command is None:
            return
        command_id, text = command
        if text == WAKE_RECORD_REQUEST:
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
                logging.getLogger("arlo.wake").exception(
                    "Wake acknowledgement failed")

    def build_ui(self):
        container = QWidget()
        container.setObjectName("windowContainer")

        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        root = CompositionSurface()
        root.setObjectName("root")

        main = CompositionLayout(root)
        main.addWidget(self.orb)

        self.status.setObjectName("status")
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

        self.workspace = Workspace()
        self.workspace.manual_content_factory = (
            self.workspace_content
        )

        main_content = QWidget()
        main_content.setObjectName("mainWorkspaceContent")
        main_layout = QVBoxLayout(main_content)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.task_progress = TaskProgressPill(main_content)
        main_layout.addWidget(root, 1)
        root.minimum_changed.connect(self._update_main_workspace_minimum)
        self.main_workspace_panel_id = self.workspace.open_panel(
            title=f"Arlo {load_dev_file()["version"]}",
            content=main_content,
            panel_id="main",
        )
        self.workspace.set_primary_panel(self.main_workspace_panel_id)
        self.file_drop_router = FileDropRouter(
            self.workspace, self.composer_widget, self.attachment_tray, self)

        self.workspace.panel_opened.connect(self.on_workspace_opened)
        self.workspace.panel_closed.connect(self.on_workspace_closed)

        container_layout.addWidget(self.workspace, 1)

        self.zoom_view = ZoomView(
            container, self, self.settings.value("ui_zoom", 100, type=int))
        self.setCentralWidget(self.zoom_view)
        self.zoom_view.zoom_changed.connect(
            lambda percent: self.settings.setValue("ui_zoom", percent))

        self.set_enabled(False)
        self.load_stylesheet()
        self.refresh_language()
        self.set_status("")

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

        buttons = [("󰭹", "chatNav", "Arlo", None)]
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

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "workspace"):
            self._workspace_hiding = False
            self.workspace.animate_visibility(True, restart=True)

    def _update_main_workspace_minimum(self, size):
        panel = self.workspace.get_panel(self.main_workspace_panel_id)
        if panel is not None:
            margins = panel.layout().contentsMargins()
            minimum = QSize(size.width() + margins.left() + margins.right(),
                            size.height() + panel.header.height() + panel.layout().spacing()
                            + margins.top() + margins.bottom())
            if panel.minimumSize() != minimum:
                panel.setMinimumSize(minimum)

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

    def build_command_palette(self):
        commands = [
            Command("workspace.new", "palette.new_workspace", self.open_workspace,
                    ("new workspace", "nuevo espacio")),
            Command("workspace.chat", "palette.chat", self.focus_main_workspace,
                    ("chat", "home", "inicio"),
                    lambda: self.workspace.get_panel(self.main_workspace_panel_id) is not None),
        ]
        commands.extend(
            Command(f"workspace.{key}", f"palette.{key}",
                    lambda key=key: self.open_workspace_view(key), (key,))
            for key in WORKSPACE_VIEW_CONFIG)
        self.command_palette = CommandPalette(CommandRegistry(commands), self)
        self.workspace.panel_focused.connect(
            lambda _panel_id: self.command_palette.dismiss(restore_focus=False))
        self.workspace.panel_closed.connect(
            lambda _panel_id: self.command_palette.dismiss(restore_focus=False))

    def open_command_palette(self):
        if self.quitting or self._workspace_hiding or not self.isVisible():
            return
        panel = self.workspace.get_panel(self.workspace.active_panel_id)
        if panel is not None:
            self._workspace_chord_timer.stop()
            self._workspace_chord_pending = False
            self.command_palette.open(panel.content_host)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.WindowDeactivate and watched is self:
            self._workspace_chord_timer.stop()
            self._workspace_chord_pending = False
        if (event.type() == QEvent.ShortcutOverride and
                QApplication.activeWindow() == self and
                ((event.key() in (Qt.Key_N, Qt.Key_K) and event.modifiers() == Qt.ControlModifier)
                 or (self._workspace_chord_pending and
                     event.modifiers() in (Qt.NoModifier, Qt.ControlModifier) and
                     event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
                                     *range(Qt.Key_0, Qt.Key_9 + 1))))):
            event.accept()
            return True
        if (event.type() == QEvent.KeyPress and
                QApplication.activeWindow() == self):
            modifiers = event.modifiers()
            if event.key() == Qt.Key_K and modifiers == Qt.ControlModifier:
                if not event.isAutoRepeat():
                    self.open_command_palette()
                event.accept()
                return True
            if event.key() == Qt.Key_N and modifiers == Qt.ControlModifier:
                if event.isAutoRepeat():
                    return True
                self._workspace_chord_pending = True
                self._workspace_chord_timer.start()
                event.accept()
                return True
            if (self._workspace_chord_pending and
                    modifiers in (Qt.NoModifier, Qt.ControlModifier)):
                if event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
                    self._workspace_chord_timer.stop()
                    self._workspace_chord_pending = False
                    self.open_workspace(direction=event.key())
                    event.accept()
                    return True
                key_code = int(event.key())
                key = str(key_code - int(Qt.Key_0))
                view_key = self._workspace_shortcut_map.get(key)
                if key == "0":
                    view_key = None
                if view_key is not None or key == "0":
                    self._workspace_chord_timer.stop()
                    self._workspace_chord_pending = False
                    if view_key is None:
                        self.open_workspace()
                    else:
                        self.open_workspace_view(view_key)
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def _open_pending_workspace(self):
        pending = self._workspace_chord_pending
        self._workspace_chord_pending = False
        if pending and QApplication.activeWindow() == self:
            self.open_workspace()

    def load_stylesheet(self):
        stylesheet = get_stylesheet()
        self.setStyleSheet(stylesheet)
        self.zoom_view.content.setStyleSheet(stylesheet)

    @property
    def startup_greeting(self) -> str:
        return tr(self.greeting_key, username=self.username, name="Arlo")

    def set_orbs_thinking(self, thinking: bool):
        for orb in (self.orb, self.mascot):
            orb.set_thinking(thinking)

    def build_worker(self):
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.initialize)
        self.request.connect(self.worker.ask)
        self.worker.ready.connect(self.on_ready)
        self.worker.directory.connect(
            self.directory_indicator.set_directory
        )

        self.worker.accepted.connect(self.on_request_accepted)
        self.worker.rejected.connect(self.on_request_rejected)
        self.worker.chunk.connect(self.on_chunk)
        self.worker.audio.connect(self.on_audio)
        self.worker.speaking.connect(self.on_speaking)
        self.worker.phase.connect(self.on_phase)
        self.worker.phase.connect(self.task_progress.on_phase)
        self.worker.task_title.connect(self.task_progress.set_task_title)
        self.worker.permission_denied.connect(self.on_permission_denied)
        self.worker.subtitle.connect(self.on_subtitle)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_error)
        self.worker.screenshot_requested.connect(self.on_screenshot_requested)
        self.worker.clipboard_requested.connect(self.on_clipboard_requested)
        self.worker.exit_requested.connect(self.request_quit)

        self.thread.finished.connect(self.worker.shutdown)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()

        self.worker.confirmation_requested.connect(
            self.on_confirmation_requested)

    @Slot()
    def open_workspace(self, direction: Qt.Key | None = None) -> None:
        """Open a manually created workspace from the main window."""
        try:
            self.workspace._open_shortcut_panel(direction=direction)
        except Exception:
            logging.getLogger("arlo.workspace").exception(
                "Failed to open a workspace")
            raise

    def _workspace_view_factory(self, view_key: str) -> QWidget:
        """Create a fresh view instance for one workspace panel."""
        if view_key == "logs":
            return LogView(self.log_dir)
        if view_key == "editor":
            return EditorView()
        if view_key == "terminal":
            from src.init.terminal import TerminalView
            return TerminalView()
        if view_key == "browser":
            from src.init.visuals.browser import BrowserView
            return BrowserView()
        if view_key == "settings":
            view = SettingsView(
                self.subtitles_enabled,
                self.settings.value("orb_speech_pulse", True, type=bool),
                muted=self.muted)
            view.mute_changed.connect(self.toggle_mute)
            view.subtitles_changed.connect(self.toggle_subtitles)
            view.orb_pulse_changed.connect(self.toggle_orb_speech_pulse)
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
            except Exception:
                logging.getLogger("arlo.workspace").exception(
                    "Failed to replace workspace view %s", view_key)
            return
        count = getattr(self, "_workspace_view_counts", {}).get(view_key, 0) + 1
        if not hasattr(self, "_workspace_view_counts"):
            self._workspace_view_counts = {}
        self._workspace_view_counts[view_key] = count
        title = options["title"] if count == 1 else f"{options['title']} {count}"
        try:
            self.workspace.open_registered_panel(
                view_key,
                title,
                lambda: self._workspace_view_factory(view_key))
        except Exception:
            logging.getLogger("arlo.workspace").exception(
                "Failed to open workspace view %s", view_key)
            return

    @Slot(str)
    def on_workspace_opened(self, panel_id: str) -> None:
        """Focus a panel after it has been added to the main workspace."""
        self.workspace.focus_panel(panel_id)

    @Slot(str)
    def on_workspace_closed(self, panel_id: str) -> None:
        """Keep the permanent main panel available after other panels close."""
        if self.workspace.active_panel_id is None:
            self.workspace.focus_panel(self.main_workspace_panel_id)


    @Slot(object)
    def on_screenshot_requested(self, request: CaptureRequest):
        """Run a screenshot request on the GUI thread."""
        if request.completed.is_set():
            return

        mascot_visible = self.mascot.isVisible()
        if mascot_visible:
            self.mascot.hide()

        QTimer.singleShot(180,
                          lambda: self.finish_screenshot(request,
                                                         mascot_visible))

    def finish_screenshot(self, request: CaptureRequest, mascot_visible: bool):
        """Capture the screen, restore the mascot and report the result."""
        try:
            result = capture_to_clipboard(return_image=request.return_image)
            if request.return_image:
                request.image_data = result if isinstance(result,
                                                          bytes) else None
                request.success = request.image_data is not None
            else:
                request.success = result is True

        except Exception as error:
            request.error = str(error)
            request.success = False
        finally:
            request.completed.set()

    @Slot(object)
    def on_clipboard_requested(self, request: ClipboardRequest):
        """Read Qt's clipboard on the GUI thread for an assistant tool call."""
        if request.completed.is_set():
            return
        try:
            request.value = read_clipboard_on_gui_thread()
            request.success = request.value is not None
            if not request.success:
                request.error = "The clipboard is empty or unsupported."
        except Exception as error:
            request.error = str(error)
        finally:
            request.completed.set()

    @Slot(int, str)
    def on_confirmation_requested(self, turn_id, message):
        if turn_id != self.turn_id:
            return
        if self.stopping:
            self.worker.resolve_confirmation(False)
            return
        self.task_progress.awaiting_permission(turn_id)
        self.set_orbs_visual_state(Orb.State.AWAITING_PERMISSION)
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("command.title"))
        dialog.setIcon(QMessageBox.Question)
        dialog.setText(tr("command.request"))
        dialog.setInformativeText(message)
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dialog.button(QMessageBox.Yes).setText(tr("command.yes"))
        dialog.button(QMessageBox.No).setText(tr("command.no"))
        dialog.setDefaultButton(QMessageBox.No)

        accepted = dialog.exec() == QMessageBox.Yes
        self.task_progress.awaiting_permission(turn_id, waiting=False)
        self.worker.resolve_confirmation(accepted)

    def set_status(self, key):
        self.status_key = key
        self.status.setText(tr(key) if key else "")

    def set_enabled(self, enabled):
        self.input.setEnabled(enabled and self.submitting is None)
        self.update_send_button()

    def update_send_button(self):
        self.has_text = bool(self.input.toPlainText().strip())
        voice_active = self.voice_thread is not None
        stopping_available = self.busy and self.speaking and not self.stopping
        self.send.setText("" if stopping_available or self.recording else
                          "" if self.has_text else "")

        font = self.send.font()
        font.setPointSize(32 if self.send.text() == "" or "" else 12)
        self.send.setFont(font)

        self.send.setEnabled(
            self.ready and (self.recording or stopping_available or (
                    not voice_active and not self.busy and
                    self.submitting is None and self.attachment_tray.can_send)))
        editable = self.ready and self.submitting is None and not voice_active
        self.attach.setEnabled(editable)
        self.attachment_tray.setEnabled(editable)
        self.input.setEnabled(editable)
        self.attach.setToolTip(tr("ui.attach_files"))
        self.attach.setAccessibleName(tr("ui.attach_files"))
        key = ("ui.stop" if stopping_available or self.recording else
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
        if language == self.active_language:
            return
        self.active_language = language
        if hasattr(self, "command_palette"):
            self.command_palette.refresh_language()
        self.task_progress.refresh_language(language)
        self.refresh_settings_workspaces()
        self.attachment_tray.refresh()
        self.set_status(self.status_key)
        self.update_send_button()
        if self.showing_greeting:
            self.update_subtitles(self.startup_greeting)

    def refresh_settings_workspaces(self):
        for view in self.workspace.findChildren(SettingsView):
            with QSignalBlocker(view.mute_switch):
                view.mute_switch.setChecked(self.muted)
            with QSignalBlocker(view.subtitles_switch):
                view.subtitles_switch.setChecked(self.subtitles_enabled)
            with QSignalBlocker(view.orb_pulse_switch):
                view.orb_pulse_switch.setChecked(
                    self.settings.value("orb_speech_pulse", True, type=bool))
            view.refresh_language()

    def refresh_privacy_indicator(self):
        private = self.worker.session.private
        self.privacy_indicator.setVisible(private)

    def refresh_directory_indicators(self):
        directory = Path.cwd()
        self.directory_indicator.set_directory(directory)
        self.branch_indicator.set_directory(directory)

    @Slot()
    def on_ready(self):
        self.ready = True
        self.set_status("")
        self.set_orbs_visual_state(Orb.State.IDLE)
        self.set_enabled(True)
        self._reveal_startup_controls()

        if self.isVisible():
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
        self.task_progress.finish(turn_id, failed=True)
        self.set_orbs_visual_state(Orb.State.DENIED_ERROR, fade_in=100, fade_out=300)
        self.finish_wake_command("failed", error)
        self.submitting = None
        self.busy = False
        self.current_reply = None
        self.update_send_button()
        QMessageBox.warning(self, tr("ui.attach_files"), error)

    @Slot()
    def on_mascot_record(self):
        """Start or stop microphone recording from compact mode."""
        if self.recording:
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

    def show_mascot(self):
        """Switch to compact desktop mode."""
        if self.quitting or self._workspace_hiding:
            return
        self.command_palette.dismiss(restore_focus=False)
        if not self.mascot.isVisible():
            self.mascot.move_mascot()
        self.mascot.pop_in()
        if self.isVisible():
            self._workspace_hiding = True
            self.workspace.animate_visibility(False, on_finished=self._hide_workspace)

    def _hide_workspace(self):
        self._workspace_hiding = False
        self.hide()
        if self.quitting:
            self.close()

    def restore_from_mascot(self):
        """Restore the full Arlo interface."""
        if self.quitting:
            return
        self.mascot.pop_out()
        if self._workspace_hiding:
            self._workspace_hiding = False
            self.workspace.animate_visibility(True)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.zoom_view.setFocus(Qt.OtherFocusReason)

    @Slot()
    def request_quit(self):
        """Explicitly stop Arlo; ordinary window closes only hide it."""
        if self.quitting:
            return
        self.quitting = True
        kill_self()
        self.close()

    def start_prompt(self, prompt):
        self.turn_id += 1
        self.task_progress.begin(self.turn_id)
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
        self.set_orbs_visual_state(Orb.State.PROCESSING)
        self.set_enabled(True)
        self.set_orbs_thinking(True)

        try:
            if not self.thread.isRunning():
                raise RuntimeError(tr("ui.worker_unavailable"))
            self.request.emit(self.turn_id, prompt)
        except Exception as error:
            self.on_request_rejected(self.turn_id, str(error))

    @Slot()
    def on_send_clicked(self):
        if self.recording:
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
        self.voice_thread = VoiceInputWorker(self, automatic=automatic)
        self.voice_thread.levels.connect(self.input_meter.set_levels)
        self.voice_thread.levels.connect(self.mascot.set_levels)
        self.voice_thread.levels.connect(self.orb.set_levels)
        self.voice_thread.processing.connect(self.on_voice_processing)
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
        self.voice_thread = None
        self.recording = False
        self.set_orbs_listening(False)
        self.input_meter.hide()
        self.input_meter.clear()
        self.mascot.clear()
        self.input.show()
        worker.deleteLater()
        self.update_send_button()
        if self.closing_after_voice:
            self.close()
            return
        if worker.error:
            self.status.setText(worker.error)
        elif worker.audio_wav:
            self.start_prompt(DesktopVoiceMessage(worker.audio_wav,
                                                  worker.transcript))

        if self.isVisible():
            self.input.setFocus()

    def stop_response(self):
        self._stop_response_timer()
        self.stopping = True
        self.task_progress.finish(self.turn_id, interrupted=True)
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

    @Slot(int, str)
    def on_phase(self, turn_id, phase):
        if turn_id != self.turn_id or self.stopping:
            return
        if phase == "executing":
            self.set_orbs_visual_state(Orb.State.EXECUTING)
        elif phase == "processing" and not self.speaking:
            self.set_orbs_visual_state(Orb.State.PROCESSING)

    @Slot(int)
    def on_permission_denied(self, turn_id):
        if turn_id == self.turn_id:
            self.permission_denied_state = True
            self.set_orbs_visual_state(Orb.State.DENIED_ERROR,
                                        fade_in=100, fade_out=300)

    @Slot(int, str)
    def on_chunk(self, turn_id, chunk):
        if turn_id != self.turn_id or self.current_reply is None:
            return

        self.current_reply += chunk
        if self.current_response_view is not None:
            self.current_response_view.append_chunk(chunk)
        if not self.speaking:
            self.set_orbs_visual_state(Orb.State.WRITING)

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
        if self.speaking:
            self.set_orbs_visual_state(Orb.State.READING)
        elif self.busy and not self.stopping:
            self.set_orbs_visual_state(Orb.State.PROCESSING)
        self.set_orbs_thinking(
            self.busy and not self.speaking and not self.stopping)

        self.set_orbs_speaking(self.speaking)

        if not self.stopping and self.busy:
            self.set_orbs_thinking(False)

        self.update_send_button()

    @Slot(str)
    def on_finished(self, reply):
        self._stop_response_timer()
        interrupted = self.stopping
        if self.current_response_view is not None:
            self.current_response_view.finish(reply)
        self.task_progress.finish(self.turn_id, interrupted=interrupted,
                                  failed=self.permission_denied_state)
        task_state = getattr(self.worker.assistant, "task_state", None)
        task_failed = self.task_progress.state in {"error", "waiting", "stopped"} or (
            task_state is not None and task_state.status != "complete")
        self.finish_wake_command("failed" if interrupted or task_failed else "completed",
                                 "Interrupted" if interrupted else
                                 task_state.notice if task_failed and task_state is not None else
                                 tr("task_progress.error") if task_failed else "")
        if self.worker.command_reply:
            self.command_output.setPlainText(reply)
            self.command_output.show()
            self.update_subtitles(reply.splitlines()[0])
        elif not self.current_reply:
            self.update_subtitles(reply or tr("status.stopped"
                                              if interrupted else "ui.no_response"))
        else:
            self.update_subtitles("")

        self.current_reply = None
        self.current_response_view = None
        self.busy = False
        self.speaking = False
        self.stopping = False
        self.orb.clear()
        self.set_orbs_speaking(False)
        self.set_orbs_thinking(False)
        result_state = (Orb.State.DENIED_ERROR if self.permission_denied_state
                        else Orb.State.SUCCESS)
        self.set_orbs_visual_state(result_state, fade_in=120, fade_out=260)
        QTimer.singleShot(700, lambda: self.set_orbs_visual_state(
            Orb.State.IDLE) if not self.busy else None)
        self.refresh_privacy_indicator()
        self.set_enabled(True)
        if self.isVisible():
            self.input.setFocus()

        if self.worker.assistant.shutdown_requested.is_set():
            self.quitting = True
            QTimer.singleShot(0, self.request_quit)
            return

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
            QTimer.singleShot(0, self.close)

    def resume_pending_prompt(self):
        if self.worker.assistant.shutdown_requested.is_set():
            self.pending_prompt = None
            return
        prompt, self.pending_prompt = self.pending_prompt, None
        if prompt:
            self.start_prompt(prompt)

    @Slot(str)
    def on_error(self, error):
        if not self.ready:
            self.status_key = ""
            self.status.setText(tr("ui.error", error=error))

        self._reset_response_timer()
        self.task_progress.finish(self.turn_id, failed=True)
        self.finish_wake_command("failed", error)
        self.showing_greeting = False
        self.update_subtitles(tr("ui.error", error=error))
        self.current_reply = None
        if self.current_response_view is not None:
            self.current_response_view.finish()
        self.current_response_view = None
        self.busy = False
        self.speaking = False
        self.stopping = False
        self.orb.clear()
        self.set_orbs_speaking(False)
        self.set_orbs_thinking(False)
        self.set_orbs_visual_state(Orb.State.DENIED_ERROR, fade_in=100, fade_out=300)

        QTimer.singleShot(700, lambda: self.set_orbs_visual_state(
            Orb.State.IDLE) if not self.busy else None)

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
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event):
        if not self.quitting:
            event.ignore()
            self.show_mascot()
            return

        unregister_capture_handler(self.capture_handler)
        unregister_clipboard_handler(self.clipboard_handler)
        self.flowchart_bridge.shutdown()
        self.browser_bridge.shutdown()
        self.terminal_bridge.shutdown()
        self.response_bridge.shutdown()
        if self.voice_thread is not None:
            self.closing_after_voice = True
            self.voice_thread.requestInterruption()
            self.voice_thread.stop_event.set()
            event.ignore()
            return
        if self.thread.isRunning() and self.busy:
            event.ignore()
            return

        if self.isVisible() and not self._workspace_exit_ready:
            event.ignore()
            if not self._workspace_hiding:
                self._workspace_hiding = True
                self.workspace.animate_visibility(False, on_finished=self._finish_workspace_exit)
            return

        kill_self()
        if self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()

        self.mascot.close()
        event.accept()
        QTimer.singleShot(0, QApplication.instance().quit)

    def _finish_workspace_exit(self):
        self._workspace_hiding = False
        self._workspace_exit_ready = True
        self.close()


def set_windows_app_id():
    """Identify Arlo as an independent Windows application."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Diego.Arlo.Desktop")


def notify_running_instance(timeout_ms: int = 1500) -> bool:
    """Ask an existing desktop process to bring its window to the front."""
    socket = QLocalSocket()
    socket.connectToServer(
        ARLO_INSTANCE_SERVER,
        QIODevice.OpenModeFlag.WriteOnly,
    )
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(b"activate\n")
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    return True


def acquire_instance_lock() -> QLockFile | None:
    """Keep initialization races from creating two desktop processes."""
    lock_path = (Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.TempLocation)) /
                 f"arlo-desktop-{getuser()}.lock")
    lock = QLockFile(str(lock_path))
    return lock if lock.tryLock(100) else None


def start_instance_server() -> QLocalServer:
    """Open the local activation endpoint for the lock-owning process."""
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if server.listen(ARLO_INSTANCE_SERVER):
        return server

    QLocalServer.removeServer(ARLO_INSTANCE_SERVER)
    if not server.listen(ARLO_INSTANCE_SERVER):
        raise RuntimeError(server.errorString())
    return server


def install_tray_icon(app: QApplication, window: ArloWindow, icon: QIcon):
    """Install the system tray UI where the desktop environment supports it."""
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None

    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip(tr("tray.running"))
    menu = QMenu(window)
    open_action = menu.addAction(tr("tray.open"))
    quit_action = menu.addAction(tr("tray.quit"))
    open_action.triggered.connect(window.restore_from_mascot)
    quit_action.triggered.connect(window.request_quit)
    tray.setContextMenu(menu)

    def activate(reason):
        if reason in (
                QSystemTrayIcon.ActivationReason.Trigger,
                QSystemTrayIcon.ActivationReason.DoubleClick):
            window.restore_from_mascot()

    tray.activated.connect(activate)
    tray.show()
    return tray

def main():
    set_windows_app_id()
    os.chdir(Path.home())
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    instance_lock = acquire_instance_lock()
    if instance_lock is None:
        for _ in range(12):
            if notify_running_instance(250):
                break
            QThread.msleep(100)
        return

    running_lock = ProcessLock("desktop-running")
    if not running_lock.acquire():
        instance_lock.unlock()
        return

    instance_server = start_instance_server()

    try:
        app.setStyle("Fusion")
        assets = Path(__file__).resolve().parent.parent.parent / "assets"
        app_icon = QIcon(str(assets / "arlo.ico"))
        app.setWindowIcon(app_icon)
        fonts = assets / "fonts"

        def load_font(filename: str) -> str:
            path = resource_path(fonts, filename)
            if not path.is_file():
                raise FileNotFoundError(
                    f"Font file not found: {path}"
                )

            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id == -1:
                raise RuntimeError(
                    f"Qt could not load font: {path}")

            families = QFontDatabase.applicationFontFamilies(font_id)
            if not families:
                raise RuntimeError(
                    f"No font families found in: {path}")

            return families[0]

        main_font = load_font("Inter_24pt-Regular.ttf")
        nerd_font = load_font("JetBrainsMonoNLNerdFontMono-Medium.ttf")
        
        font = QFont(main_font, 11)
        font.setKerning(True)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100)
        app.setFont(font)
        window = ArloWindow()
        window.show()
        icon_font = QFont(nerd_font, 18)

        for button in (
                window.send,
                window.attach):
            button.setFont(icon_font)

        def activate_existing_window():
            while instance_server.hasPendingConnections():
                connection = instance_server.nextPendingConnection()
                connection.readAll()
                connection.disconnectFromServer()
                connection.deleteLater()
            window.restore_from_mascot()

        instance_server.newConnection.connect(activate_existing_window)
        if instance_server.hasPendingConnections():
            QTimer.singleShot(0, activate_existing_window)

        tray_icon = install_tray_icon(app, window, app_icon)
        window.tray_icon = tray_icon
        QTimer.singleShot(0, window.show_mascot)
        sys.exit(app.exec())
    finally:
        instance_server.close()
        QLocalServer.removeServer(ARLO_INSTANCE_SERVER)
        instance_lock.unlock()
        running_lock.release()
