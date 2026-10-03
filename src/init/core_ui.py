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
import itertools
import logging
import os
import re
import sys
import threading
import tempfile
from datetime import datetime, timedelta
from getpass import getuser
from types import SimpleNamespace

from shiboken6 import isValid

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
from src.init.core import Assistant
from src.init.worker import AssistantWorker, VoiceInputWorker
from src.init.chat import ChatInput
from src.init.indicators import (GitBranchIndicator, ModelSelector, PermissionSelector,
                                 PrivacyIndicator, WorkingDirectory)
from src.init.visuals.workspace import Workspace, WorkspacePanel
from src.init.visuals.response import ResponseBridge
from src.init.nova import formatting as nova_formatting
from src.init.nova.navigation import WorkspaceNavigation
from src.init.nova.sections import Section
from src.init.nova.store import NovaStore
from src.init.nova.tools import use_store as use_nova_store
from src.init.nova.view import NovaView
from src.init.notifications import ask_notification, send_notification
from src.init.song.monitor import SongMonitor
from src.init.song.view import SongView


WORKSPACE_VIEW_CONFIG = {
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
    "nova": {
        "title": "Nova",
        "shortcut": "Ctrl+Alt+N",
        "icon": "󰫢",
    },
}

from src.init.attachment_widgets import AttachmentTray
from src.init.attachments import DesktopMessage, DesktopVoiceMessage
from src.init.choice_dialog import ChoiceDialog, NEUTRAL_BUTTON
from src.init.brain import MODEL_OVERRIDE, get_version, is_cloud_model, kill_self
from src.init.config import DEFAULTS, load_dev_file, load_config, save_config
from src.init.editor.live import EditorView
from src.init.lang import get_language, set_language, tr
from src.init.settings import SettingsView
from src.init.theme import on_theme_changed

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
from src.init.desktop.health_view import HealthView
from src.init.health import collect as collect_health, new_version_seen
from src.init.desktop.update_view import HEIGHT as UPDATE_HEIGHT, UpdateView
from src.init.updates import available_releases, install as install_update, relaunch_command
from src.platforms import current_platform
from src.init.desktop.session import DesktopSession
from src.init.desktop.window import DesktopWindow
from src.init.desktop.zoom import ZoomView
from src.init.desktop.file_drop import FileDropRouter
from src.init.visuals.bridge import FlowchartBridge
from src.init.terminal import TerminalBridge

HEALTH_CHECK_DELAY_MS = 45_000
SONG_PANEL_WIDTH = 440

# noinspection PyBroadException
class AssistantWindow(DesktopWindow):
    """Assistant window class, not its brain, which is somewhere else"""
    MAX_SESSIONS = 2
    model_request = Signal(str)
    reminder_answered = Signal(object, str)
    health_checked = Signal(object)
    updates_checked = Signal(object, object)
    username = getuser().capitalize()

    def __init__(self):
        super().__init__()
        log_path = Path(tempfile.gettempdir()) / get_assistant_identifier() / "agent.log"
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
        logging.getLogger("assistant.desktop").info(
            "Desktop backend logging initialized")

        self.settings = QSettings(DEFAULTS["assistant"]["name"].upper(), "desktop")
        self.muted = self.settings.value("muted", False, type=bool)
        subtitles_enabled = self.settings.value("subtitles", True, type=bool)
        orb_speech_pulse = self.settings.value("orb_speech_pulse", True, type=bool)
        self.setWindowTitle(f"{get_assistant_name()} {load_dev_file()["version"]}")
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

        self.recording = False
        self.voice_thread = None
        self.voice_session = None
        self.closing_after_voice = False
        self.quitting = False
        self.model_switching = False
        self.active_language = None

        self.assistant = Assistant()
        register_assistant(lambda: self.assistant)
        self.sessions = []
        self.closing_sessions = []
        self._turn_ids = itertools.count(1)
        self.session = self.create_session(greet=True)
        self.session.worker.set_permission_mode(load_config()["permission_mode"])

        self.capture_handler = self.session.worker.screenshot_requested.emit
        register_capture_handler(self.capture_handler)
        self.clipboard_handler = self.session.worker.clipboard_requested.emit
        register_clipboard_handler(self.clipboard_handler)
        self.flowchart_bridge = FlowchartBridge(self)
        self.terminal_bridge = TerminalBridge(self)
        self.response_bridge = ResponseBridge(self)

        self.session.status_key = "status.waking"
        self.response_timer_tick = QTimer(self)
        self.response_timer_tick.setInterval(50)
        self.response_timer_tick.timeout.connect(self._update_response_timer)
        self._workspace_hiding = False
        self._workspace_exit_ready = False
        self.wake_inbox = None
        self.nova_store = None
        self._update_running = False
        self.updates_checked.connect(self.show_updates, Qt.ConnectionType.QueuedConnection)

        self.build_ui()
        self.build_command_palette()
        self.start_nova()
        self.start_song_monitor()
        self.check_health_after_update()

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

        self.diary_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        self.diary_shortcut.setContext(Qt.ApplicationShortcut)
        self.diary_shortcut.activated.connect(self.open_nova_diary)

        self._workspace_chord_pending = False
        self._workspace_chord_timer = QTimer(self)
        self._workspace_chord_timer.setSingleShot(True)
        self._workspace_chord_timer.setInterval(700)
        self._workspace_chord_timer.timeout.connect(
            self._open_pending_workspace)
        QApplication.instance().installEventFilter(self)

        self.session_shortcuts = []
        for sequence, action in (("Ctrl+Shift+N", self.new_session),
                                 ("Ctrl+Shift+W", lambda: self.close_session())):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(action)
            self.session_shortcuts.append(shortcut)

        self.build_worker(self.session)
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
        session = self.session
        barge_candidate = session.busy and not session.stopping
        if (not session.ready or (session.busy and not barge_candidate) or
                self.voice_thread is not None or session.submitting is not None or
                (session.pending_prompt is not None and not barge_candidate) or
                self.closing_after_voice or self.assistant.shutdown_requested.is_set()):
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
            session.wake_command_id = command_id
            if barge_candidate:
                session.pending_wake_barge = True
                session.pending_prompt = None
                self.stop_response(session)
                return
            self.start_recording(automatic=True, session=session)
            self.finish_wake_command(
                session, "completed" if self.recording else "failed",
                "" if self.recording else "Recording was unavailable",
            )
            return
        session.wake_command_id = command_id
        self.start_prompt(DesktopMessage(text), session)

    def finish_wake_command(self, session, state, detail=""):
        command_id, session.wake_command_id = session.wake_command_id, None
        if command_id is not None:
            try:
                self.wake_inbox.finish(command_id, state, detail)
            except Exception:
                logging.getLogger("assistant.wake").exception(
                    "Wake acknowledgement failed")

    def build_ui(self):
        container = QWidget()
        container.setObjectName("windowContainer")

        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self.workspace = Workspace()
        self.workspace.manual_content_factory = (
            self.workspace_content
        )

        session = self.session
        session.panel_id = "main"
        main_content = self.build_session_view(session)
        self.main_workspace_panel_id = self.workspace.open_panel(
            title=self._session_title(session),
            content=main_content,
            panel_id=session.panel_id,
        )
        self.workspace.set_primary_panel(self.main_workspace_panel_id)
        self.file_drop_router = FileDropRouter(
            self.workspace, session.ui.composer_widget, session.ui.attachment_tray, self)

        self.workspace.panel_opened.connect(self.on_workspace_opened)
        self.workspace.panel_closed.connect(self.on_workspace_closed)
        self.workspace.panel_focused.connect(self.on_workspace_focused)

        container_layout.addWidget(self.workspace, 1)

        self.zoom_view = ZoomView(
            container, self, self.settings.value("ui_zoom", 100, type=int))
        self.setCentralWidget(self.zoom_view)
        self.zoom_view.zoom_changed.connect(
            lambda percent: self.settings.setValue("ui_zoom", percent))

        self.set_enabled(False)
        self.load_stylesheet()
        on_theme_changed(self.apply_theme)
        self.refresh_language()
        self.set_status("")

    def build_session_view(self, session):
        """Create one session's chat surface; its widgets only ever show that session."""
        ui = SimpleNamespace(reveal_animations=[])
        session.ui = ui
        ui.orb = Orb(self, fill_ratio=0.54)
        ui.orb.set_speech_pulse_enabled(self.settings.value("orb_speech_pulse", True, type=bool))
        ui.activity_trail = ActivityTrail(
            session.presentation, steps_enabled=self.settings.value("ephemeral_steps", True, type=bool))
        ui.status = QLabel()
        ui.subtitles = QLabel()
        ui.command_output = QPlainTextEdit()
        ui.input = ChatInput(directory=lambda: session.worker.session.context.working_directory)
        ui.composer_widget = QWidget()
        ui.input_meter = AudioVisualizer()
        ui.input_meter.setMinimumWidth(0)
        ui.input_meter.setFixedHeight(48)
        ui.input_meter.hide()
        ui.attachment_tray = AttachmentTray(load_config()["attachments"])
        ui.attach = QPushButton("")
        ui.send = QPushButton("")
        ui.response_timer_display = QLabel()
        ui.directory_indicator = WorkingDirectory(self)
        ui.branch_indicator = GitBranchIndicator(self)
        ui.privacy_indicator = PrivacyIndicator(self)
        ui.model_selector = ModelSelector(self)
        ui.model_selector.model_selected.connect(self.request_model)
        ui.permission_selector = PermissionSelector(self)
        ui.permission_selector.set_mode(load_config()["permission_mode"])
        ui.permission_selector.mode_changed.connect(self.set_permission_mode)
        ui.privacy_indicator.clicked.connect(
            lambda: ui.privacy_indicator.private_toggle(session.worker))

        root = CompositionSurface()
        root.setObjectName("root")

        main = CompositionLayout(root)
        main.addWidget(ui.orb)
        main.addWidget(ui.activity_trail)

        ui.status.setObjectName("status")
        ui.status.setProperty("orbContext", True)
        ui.status.setAlignment(Qt.AlignCenter)
        main.addWidget(ui.status)

        ui.subtitles.setObjectName("subtitles")
        ui.subtitles.setAlignment(Qt.AlignCenter)
        ui.subtitles.setWordWrap(True)
        ui.subtitles.setTextFormat(Qt.RichText)
        ui.subtitles.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        ui.subtitles.setMinimumHeight(0)
        ui.subtitles.setMaximumHeight(0)
        ui.subtitles.setVisible(False)
        main.addWidget(ui.subtitles)

        ui.command_output.setObjectName("commandOutput")
        ui.command_output.setReadOnly(True)
        ui.command_output.setMinimumHeight(110)
        ui.command_output.setMaximumHeight(220)
        ui.command_output.hide()
        main.addWidget(ui.command_output)

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

        ui.input.submitted.connect(lambda: self.send_message(session))
        input_layout.addWidget(ui.input, 1, Qt.AlignVCenter)
        input_layout.addWidget(ui.input_meter)
        input_layout.addWidget(ui.attach, 0, Qt.AlignBottom)

        input_column = QVBoxLayout()
        input_column.setContentsMargins(0, 0, 0, 0)
        input_column.setSpacing(8)

        ui.attachment_tray.setMinimumWidth(0)
        ui.attachment_tray.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed)

        input_column.addWidget(ui.attachment_tray)
        indicator_row = QHBoxLayout()
        indicator_row.setContentsMargins(0, 0, 0, 0)
        indicator_row.setSpacing(6)
        indicator_row.setAlignment(Qt.AlignVCenter)
        ui.response_timer_display.setObjectName("responseTimer")
        ui.response_timer_display.setAlignment(Qt.AlignCenter)
        ui.response_timer_display.setText(session.response_timer_text)
        ui.response_timer_display.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Fixed)
        indicator_row.addWidget(ui.response_timer_display)
        indicator_row.addWidget(ui.directory_indicator)
        indicator_row.addWidget(ui.branch_indicator)
        indicator_row.addWidget(ui.privacy_indicator)
        indicator_row.addStretch()
        indicator_row.addWidget(ui.permission_selector)
        indicator_row.addWidget(ui.model_selector)
        ui.indicator_row = QWidget()
        ui.indicator_row.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        ui.indicator_row.setLayout(indicator_row)
        ui.indicator_row.setMaximumHeight(0)
        input_column.addWidget(ui.indicator_row)
        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(12)
        input_row.addWidget(input_frame, 1)
        input_row.addWidget(ui.send, 0, Qt.AlignVCenter)
        input_column.addLayout(input_row)

        input_group = QWidget()
        input_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        ui.attachment_tray.changed.connect(lambda *_: self.update_send_button(session))

        ui.attach.setObjectName("attach")
        ui.attach.setFixedSize(48, 48)
        ui.attach.clicked.connect(ui.attachment_tray.choose_files)

        ui.send.setObjectName("send")
        ui.send.setFixedSize(48, 48)
        ui.send.clicked.connect(lambda: self.on_send_clicked(session))
        ui.send.hide()
        indicator_row.setContentsMargins(
            0, 0, ui.send.width() + input_row.spacing(), 0)

        input_group.setLayout(input_column)
        ui.input_group = input_group
        ui.input_group.setMaximumHeight(0)
        ui.input_group.setVisible(False)

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
        ui.composer_widget.setLayout(composer_area)
        main.addWidget(ui.composer_widget)

        ui.input.textChanged.connect(lambda: self.update_send_button(session))

        main_content = CompositionSurface()
        main_content.setObjectName("mainWorkspaceContent")
        main_layout = QGridLayout(main_content)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        ui.task_progress = TaskProgressPill(session.presentation, main_content)
        main_layout.addWidget(root, 0, 0)
        main_layout.addWidget(ui.task_progress, 0, 0, Qt.AlignLeft | Qt.AlignTop)
        main_content.minimum_changed.connect(
            lambda size: self._update_session_minimum(session, size))
        ui.orb.setToolTip(get_assistant_name())
        return main_content

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
        tray_buttons = []

        buttons = [(options["icon"], f"{view_key}Nav", options["title"], view_key)
                   for view_key, options in WORKSPACE_VIEW_CONFIG.items() if view_key != "nova"]

        for icon, object_name, tooltip, view_key in buttons:
            button = QPushButton(icon, content)
            button.setObjectName(object_name)
            button.setFixedSize(48, 48)
            button.setToolTip(tooltip)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, key=view_key, source=button:
                self.open_workspace_view(key, source))
            tray_buttons.append(button)

        workspace_navigation = WorkspaceNavigation(tray_buttons, content)
        workspace_navigation.nova_requested.connect(
            lambda source: self.open_workspace_view("nova", source))
        navigation.addWidget(workspace_navigation)
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

    def _update_session_minimum(self, session, size):
        panel = self.workspace.get_panel(session.panel_id) if session.panel_id else None
        if panel is not None:
            margins = panel.layout().contentsMargins()
            minimum = QSize(size.width() + margins.left() + margins.right(),
                            size.height() + panel.header.height() + panel.layout().spacing()
                            + margins.top() + margins.bottom())
            panel.set_minimum(minimum)

    def _update_response_timer(self):
        for session in self._views():
            if session.response_timer_running:
                session.response_timer_text = self._response_timer_text(session)
            session.ui.response_timer_display.setText(session.response_timer_text)
        if not any(item.response_timer_running for item in self.sessions):
            self.response_timer_tick.stop()

    def _views(self):
        return [session for session in self.sessions if session.ui is not None]

    @staticmethod
    def _response_timer_text(session):
        total_seconds = session.response_timer.elapsed() // 1000
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"

    def _start_response_timer(self, session):
        session.response_timer.start()
        session.response_timer_running = True
        session.response_timer_text = "0s"
        self.response_timer_tick.start()
        self._update_response_timer()

    def _stop_response_timer(self, session):
        if session.response_timer_running:
            session.response_timer_text = self._response_timer_text(session)
        session.response_timer_running = False
        self._update_response_timer()

    def _reset_response_timer(self, session):
        session.response_timer_running = False
        session.response_timer_text = "0s"
        self._update_response_timer()

    def build_command_palette(self):
        commands = [
            Command("workspace.new", "palette.new_workspace", self.open_workspace,
                    ("new workspace", "nuevo espacio")),
            Command("session.new", "palette.new_session", self.new_session,
                    ("new session", "nueva sesion", "nueva sesión"),
                    lambda: len(self.sessions) < self.MAX_SESSIONS),
            Command("session.close", "palette.close_session", lambda: self.close_session(),
                    ("close session", "cerrar sesion", "cerrar sesión"),
                    lambda: len(self.sessions) > 1),
            Command("task.stop", "palette.stop_task", self.stop_current_task,
                    ("stop task", "detener tarea", "cancelar"),
                    lambda: self.session.ready and (self.session.busy and not self.session.stopping
                                                    or self.session.paused_prompt is not None)),
            Command("task.pause", "palette.pause_task", self.pause_current_task,
                    ("pause task", "pausar tarea"),
                    lambda: self.session.ready and self.session.busy and not self.session.stopping),
            Command("task.resume", "palette.resume_task", self.resume_current_task,
                    ("resume task", "resumir tarea", "reanudar", "continuar"),
                    self.can_resume_task),
        ]
        commands.extend(
            Command(f"workspace.{key}", f"palette.{key}",
                    lambda key=key: self.open_workspace_view(key), (key,))
            for key in WORKSPACE_VIEW_CONFIG)
        commands.append(Command("workspace.diary", "palette.diary", self.open_nova_diary,
                                ("diary", "diario")))
        commands.append(Command("workspace.health", "palette.health", self.open_health_view,
                                ("health", "diagnostics", "salud", "diagnóstico", "estado")))
        commands.append(Command("app.update", "palette.update", self.check_for_updates,
                                ("update", "upgrade", "version", "release", "actualizar", "actualización",
                                 "versión", "更新"),
                                lambda: not self._update_running))
        commands.append(Command("session.private", "palette.private", self.toggle_private_mode,
                                ("private", "privacy", "privado", "privacidad", "incognito", "隐私")))
        commands.append(Command("app.reload", "palette.reload", self.reload_modules,
                                ("reload", "refresh", "modules", "recargar", "recarga", "modulos", "módulos", "重新加载"),
                                lambda: self.session.ready and not self.session.busy
                                and self.session.submitting is None))
        commands.append(Command("app.exit", "palette.exit", self.exit_app,
                                ("exit", "quit", "salir", "cerrar arlo", "退出")))
        self.command_palette = CommandPalette(CommandRegistry(commands), self)
        self.workspace.panel_focused.connect(
            lambda _panel_id: self.command_palette.dismiss(restore_focus=False))
        self.workspace.panel_closed.connect(
            lambda _panel_id: self.command_palette.dismiss(restore_focus=False))
        self.workspace.palette_requested.connect(self.open_command_palette_from_panel)

    def open_command_palette(self):
        if self.quitting or self._workspace_hiding or not self.isVisible():
            return
        panel = self.workspace.get_panel(self.workspace.active_panel_id)
        if panel is not None:
            self._workspace_chord_timer.stop()
            self._workspace_chord_pending = False
            self.command_palette.open(panel.content_host)

    def open_command_palette_from_panel(self, panel_id):
        self.workspace.focus_panel(panel_id)
        self.open_command_palette()

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
        QApplication.instance().setStyleSheet(get_stylesheet())

    def apply_theme(self, theme):
        self.load_stylesheet()
        self.apply_frame_theme(theme)

    def _orbs(self, session=None):
        session = session or self.session
        orbs = [session.ui.orb] if session.ui is not None else []
        if session is self.session:
            orbs.append(self.mascot)
        return orbs

    def clear_orbs(self, session=None):
        for orb in self._orbs(session):
            orb.clear()

    def set_orbs_thinking(self, thinking: bool, session=None):
        for orb in self._orbs(session):
            orb.set_thinking(thinking)

    def create_session(self, greet=False):
        index = len(self.sessions)
        worker = AssistantWorker(greet, muted=self.muted, session_key=index,
                                 primary=not index)
        session = DesktopSession(self, index, worker)
        self.sessions.append(session)
        return session

    def session_for(self, key):
        return next((session for session in self.sessions if session.index == key), self.session)

    def build_worker(self, session):
        worker = session.worker
        session.bind()
        if session.index == 0:
            self.model_request.connect(worker.select_model)
            worker.screenshot_requested.connect(self.on_screenshot_requested)
            worker.clipboard_requested.connect(self.on_clipboard_requested)
        worker.model_changed.connect(self.on_model_changed)
        worker.model_failed.connect(self.on_model_failed)
        worker.exit_requested.connect(self.request_quit)
        session.worker_thread.start()

    def on_session_directory(self, session, directory):
        if session.ui is not None:
            session.ui.directory_indicator.set_directory(directory)
            session.ui.branch_indicator.set_directory(directory)

    @Slot()
    def new_session(self):
        if self.quitting:
            return
        if len(self.sessions) >= self.MAX_SESSIONS:
            logging.getLogger("assistant.sessions").info(
                "Rejected a new session; the limit of %d is reached", self.MAX_SESSIONS)
            self.session.ui.status.setText(tr("session.limit", count=self.MAX_SESSIONS))
            self.session.ui.status.show()
            return
        session = self.create_session()
        session.worker.set_permission_mode(self.sessions[0].ui.permission_selector.mode)
        session.panel_id = f"session-{session.worker.session.session_id}"
        content = self.build_session_view(session)
        self._refresh_view_language(session)
        self.set_status("", session)
        self.workspace.open_panel(
            title=self._session_title(session),
            content=content,
            panel_id=session.panel_id,
            target_id=self.main_workspace_panel_id,
            direction=Qt.Key_Right,
        )
        self.file_drop_router.add_composer(session.ui.composer_widget, session.ui.attachment_tray)
        self.build_worker(session)
        self.refresh_session_titles()
        self.update_send_button()
        logging.getLogger("assistant.sessions").info("Created session %d", session.index + 1)

    def close_session(self, session=None):
        """Close the second session; a running task is cancelled and its worker released."""
        if len(self.sessions) < 2 or self.quitting:
            return
        session = session or self.sessions[-1]
        if session.index == 0 or session.closing or session not in self.sessions:
            return
        session.closing = True
        session.pending_prompt = None
        session.paused_prompt = None
        session.pending_voice_barge = False
        session.pending_wake_barge = False
        if self.voice_session is session and self.voice_thread is not None:
            self.voice_session = None
            self.voice_thread.stop_event.set()
        self.sessions.remove(session)
        self.closing_sessions = [item for item in self.closing_sessions if isValid(item.worker_thread)]
        self.closing_sessions.append(session)
        if self.session is session:
            self.session = self.sessions[0]
        for request in tuple(session.confirmation_dialogs.values()):
            request.cancel()
        self.file_drop_router.remove_composer(session.ui.composer_widget)
        session.ui = None
        session.current_response_view = None
        if session.busy:
            session.stopping = True
            session.worker.interrupt()
        else:
            self.release_session(session)
        if self.workspace.get_panel(session.panel_id) is not None:
            self.workspace.close_panel(session.panel_id)
        self.workspace.focus_panel(self.session.panel_id)
        logging.getLogger("assistant.sessions").info("Closed session %d", session.index + 1)
        self.sync_mascot()
        self.refresh_session_titles()
        self._update_response_timer()
        self.update_send_button()

    def release_session(self, session):
        if session.released:
            return
        session.released = True
        thread = session.worker_thread
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(session.deleteLater)
        thread.quit()

    def refresh_session_titles(self):
        if not hasattr(self, "workspace"):
            return
        for session in self.sessions:
            panel = self.workspace.get_panel(session.panel_id) if session.panel_id else None
            if panel is not None:
                panel.set_title(self._session_title(session))

    def _session_title(self, session):
        title = f"{get_assistant_name()} {load_dev_file()['version']}"
        if len(self.sessions) > 1:
            title += " · " + tr("session.label", index=session.index + 1, count=len(self.sessions))
        return title

    def on_session_view(self, session, view):
        self.set_orbs_thinking(view.active and view.orb_state == Orb.State.PROCESSING, session)
        self.set_orbs_visual_state(view.orb_state, session)

    @Slot(str)
    def on_workspace_focused(self, panel_id):
        session = next((item for item in self.sessions if item.panel_id == panel_id), None)
        if session is None or session is self.session:
            return
        self.session = session
        self.sync_mascot()

    def sync_mascot(self):
        session = self.session
        view = session.presentation.view
        self.mascot.clear()
        self.mascot.set_thinking(view.active and view.orb_state == Orb.State.PROCESSING)
        if session.ready:
            self.mascot.set_visual_state(view.orb_state)
        self.mascot.set_speaking(session.speaking)
        self.mascot.set_listening(self.recording and self.voice_session is session)
        self.sync_mascot_subtitle()

    @Slot()
    def open_workspace(self, direction: Qt.Key | None = None) -> None:
        """Open a manually created workspace from the main window."""
        try:
            self.workspace._open_shortcut_panel(direction=direction)
        except Exception:
            logging.getLogger("assistant.workspace").exception(
                "Failed to open a workspace")
            raise

    def _workspace_view_factory(self, view_key: str) -> QWidget:
        """Create a fresh view instance for one workspace panel."""
        if view_key == "editor":
            return EditorView()
        if view_key == "terminal":
            from src.init.terminal import TerminalView
            return TerminalView()
        if view_key == "nova":
            return NovaView(self.get_nova_store())
        if view_key == "settings":
            view = SettingsView(
                self.subtitles_enabled,
                self.settings.value("orb_speech_pulse", True, type=bool),
                muted=self.muted,
                ephemeral_steps_enabled=self.settings.value("ephemeral_steps", True, type=bool),
                song_panel_enabled=self.settings.value("song_panel", True, type=bool),
                orb_enabled=self.orb_enabled)
            view.mute_changed.connect(self.toggle_mute)
            view.subtitles_changed.connect(self.toggle_subtitles)
            view.orb_pulse_changed.connect(self.toggle_orb_speech_pulse)
            view.ephemeral_steps_changed.connect(self.toggle_ephemeral_steps)
            view.song_panel_changed.connect(self.toggle_song_panel)
            view.orb_enabled_changed.connect(self.toggle_orb_enabled)
            view.language_changed.connect(self.change_language)
            view.update_requested.connect(self.check_for_updates)
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
                logging.getLogger("assistant.workspace").exception(
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
            logging.getLogger("assistant.workspace").exception(
                "Failed to open workspace view %s", view_key)
            return

    def open_health_view(self, checks=None) -> None:
        """Open the health view, which checks Ollama, the model, the GPU and the voice service."""
        try:
            self.workspace.open_registered_panel("health", tr("health.title"),
                                                 lambda: HealthView(checks=checks))
        except Exception:
            logging.getLogger("assistant.workspace").exception("Failed to open the health view")

    def check_health_after_update(self) -> None:
        """On the first start of a new version, run the health checks once the services had time
        to start, and open the health view when one of them fails."""
        try:
            if not new_version_seen():
                return
        except Exception:
            logging.getLogger("assistant.health").exception("The running version could not be recorded")
            return
        self.health_checked.connect(self.show_failed_health, Qt.ConnectionType.QueuedConnection)

        def run():
            checks = collect_health()
            try:
                self.health_checked.emit(checks)
            except RuntimeError:
                pass

        QTimer.singleShot(HEALTH_CHECK_DELAY_MS,
                          lambda: threading.Thread(target=run, name="health-after-update", daemon=True).start())

    @Slot(object)
    def show_failed_health(self, checks) -> None:
        if not self.quitting and any(check.status == "error" for check in checks):
            self.open_health_view(checks)

    def check_for_updates(self) -> None:
        """Look for newer releases in the repository and offer to install one."""
        if self._update_running or self.quitting:
            return
        self._update_running = True

        def run():
            try:
                result, error = available_releases(), None
            except Exception as failure:
                logging.getLogger("assistant.update").exception("The releases could not be read")
                result, error = [], failure
            try:
                self.updates_checked.emit(result, error)
            except RuntimeError:
                pass

        threading.Thread(target=run, name="update-check", daemon=True).start()

    @Slot(object, object)
    def show_updates(self, releases, error) -> None:
        self._update_running = False
        if self.quitting:
            return
        title = tr("update.title")
        if error is not None:
            ChoiceDialog.of(self).notify(title, tr("update.check_failed", error=error))
            return
        if not releases:
            ChoiceDialog.of(self).notify(title, tr("update.up_to_date", version=get_version()))
            return
        choices = [(tr("update.choice", version=release.version, date=release.published or "?",
                       size=f"{release.size / 1024 ** 2:.0f}"), NEUTRAL_BUTTON,
                    lambda release=release: self.confirm_update(release)) for release in releases]
        choices.append((tr("ui.cancel"), NEUTRAL_BUTTON, None))
        ChoiceDialog.of(self).ask(title, tr("update.choose", version=get_version()), choices, columns=1)

    def confirm_update(self, release) -> None:
        ChoiceDialog.of(self).confirm(
            tr("update.title"), tr("update.confirm", version=release.version),
            lambda: self.start_update(release), danger=False)

    def start_update(self, release) -> None:
        self._update_running = True
        view = UpdateView(release)
        view.setProperty("workspaceViewKey", "update")
        view.ready.connect(self.install_update)
        view.failed.connect(lambda _message: setattr(self, "_update_running", False))
        view.destroyed.connect(lambda: setattr(self, "_update_running", False))
        try:
            self.workspace.open_panel(title=tr("update.title"), content=view,
                                      direction=Qt.Key_Down, size=UPDATE_HEIGHT)
        except Exception:
            self._update_running = False
            logging.getLogger("assistant.workspace").exception("Failed to open the update view")

    @Slot(object)
    def install_update(self, path) -> None:
        try:
            install_update(path, *relaunch_command())
        except Exception as error:
            self._update_running = False
            logging.getLogger("assistant.update").exception("The installer could not be started")
            ChoiceDialog.of(self).notify(tr("update.title"), tr("ui.error", error=error))
            return
        QTimer.singleShot(800, self.exit_app)

    def start_song_monitor(self) -> None:
        """Watch for songs in the background and open the song panel when one starts playing."""
        self.song_monitor = SongMonitor(self)
        self.song_panel_key = None
        self.song_monitor.updated.connect(self.on_song_update, Qt.ConnectionType.QueuedConnection)
        self.song_monitor.start()

    @Slot(object)
    def on_song_update(self, song) -> None:
        """Open the song panel once for each song that plays, unless the user closed it for that song."""
        if song is None:
            self.song_panel_key = None
            return
        if (not song.playing or song.key == self.song_panel_key or self.quitting or not self.isVisible()
                or not self.settings.value("song_panel", True, type=bool)
                or self.workspace.findChildren(SongView)):
            return
        self.song_panel_key = song.key
        view = SongView(self.song_monitor)
        view.setProperty("workspaceViewKey", "song")
        try:
            self.workspace.open_panel(title=tr("song.title"), content=view, direction=Qt.Key_Right,
                                      size=SONG_PANEL_WIDTH)
        except Exception:
            view.deleteLater()
            logging.getLogger("assistant.workspace").exception("Failed to open the song view")

    def open_nova_diary(self) -> None:
        """Show the Nova diary, reusing an open Nova panel when there is one."""
        self.open_nova_section(Section.DIARY)

    def open_nova_section(self, section: Section) -> None:
        """Show one section of Nova, reusing an open Nova panel when there is one."""
        view = next(iter(self.workspace.findChildren(NovaView)), None)
        if view is None:
            self.open_workspace_view("nova")
            panel = self.workspace.get_panel(self.workspace.active_panel_id)
            view = panel.content if panel is not None else None
        else:
            panel = view.parentWidget()
            while panel is not None and not isinstance(panel, WorkspacePanel):
                panel = panel.parentWidget()
            if panel is not None:
                self.workspace.focus_panel(panel.panel_id)
        if isinstance(view, NovaView):
            view.show_section(section)

    def get_nova_store(self) -> NovaStore:
        """Open Nova's databases on first use and keep one store for every Nova view."""
        if self.nova_store is None:
            self.nova_store = NovaStore(parent=self)
            use_nova_store(self.nova_store)
        return self.nova_store

    def start_nova(self) -> None:
        """Open Nova's storage and start announcing reminders as they become due."""
        try:
            self.get_nova_store()
        except Exception:
            logging.getLogger("assistant.nova").exception("Nova storage is unavailable")
            return
        self.reminder_answered.connect(self.answer_reminder, Qt.ConnectionType.QueuedConnection)
        self.nova_timer = QTimer(self)
        self.nova_timer.setInterval(30_000)
        self.nova_timer.timeout.connect(self.notify_due_reminders)
        self.nova_timer.start()
        QTimer.singleShot(3_000, self.notify_due_reminders)

    def notify_due_reminders(self) -> None:
        try:
            due = self.nova_store.pop_due()
        except Exception:
            logging.getLogger("assistant.nova").exception("Unable to read due reminders")
            return
        title = f"{get_assistant_name()} · {tr('nova.reminder')}"[:63]
        today = datetime.now().date()
        messages = [f"{nova_formatting.time_text(reminder.remind_at)} · {reminder.title}"
                    if reminder.remind_at.date() == today else
                    f"{nova_formatting.date_time_text(reminder.remind_at)} · {reminder.title}"
                    for reminder in due]
        if len(messages) > 3:
            message = tr('nova.due_reminders', count=len(due), titles=", ".join(reminder.title for reminder in due))
            threading.Thread(target=send_notification, args=(message[:255], title), daemon=True).start()
            return
        actions = [(action, tr(f"nova.toast.{action}")) for action in ("snooze", "tomorrow", "done")]
        for reminder, message in zip(due, messages):
            threading.Thread(target=self.ask_reminder, args=(reminder, message[:255], title, actions),
                             daemon=True).start()

    def ask_reminder(self, reminder, message: str, title: str, actions: list[tuple[str, str]]) -> None:
        try:
            choice = ask_notification(title, message, actions)
        except Exception:
            logging.getLogger("assistant.nova").exception("Unable to show the reminder notification")
            return
        if choice:
            self.reminder_answered.emit(reminder, choice)

    @Slot(object, str)
    def answer_reminder(self, reminder, choice: str) -> None:
        """Apply the button pressed on a due reminder's notification."""
        now = datetime.now().replace(second=0, microsecond=0)
        try:
            if choice in ("snooze", "tomorrow"):
                until = (now + timedelta(minutes=10) if choice == "snooze" else
                         datetime.combine((now + timedelta(days=1)).date(), reminder.remind_at.time()))
                try:
                    self.nova_store.snooze_reminder(reminder.id, until)
                except ValueError:
                    self.confirm_reminder(tr("nova.snoozed_missing", title=reminder.title))
                    raise
                when = (nova_formatting.time_text(until) if until.date() == now.date()
                        else nova_formatting.date_time_text(until))
                self.confirm_reminder(tr("nova.snoozed", title=reminder.title, when=when))
            elif choice == "done":
                if not reminder.is_recurring:
                    self.nova_store.set_reminder_completed(reminder.id, True)
            elif choice == "open":
                self.showNormal()
                self.raise_()
                self.activateWindow()
                self.open_nova_section(Section.AGENDA)
        except (ValueError, OSError):
            logging.getLogger("assistant.nova").exception("Unable to apply the reminder action %s", choice)

    def confirm_reminder(self, message: str) -> None:
        title = f"{get_assistant_name()} · {tr('nova.reminder')}"[:63]
        threading.Thread(target=send_notification, args=(message[:255], title), daemon=True).start()

    def open_terminal_command(self, command: str) -> None:
        from src.init.terminal import TerminalView
        view = TerminalView(directory=self.session.worker.session.context.working_directory, command=command,
                            preserve_output=True, autostart=False)
        try:
            self.workspace.open_registered_panel("terminal", "Terminal", lambda: view)
            view.start_session()
        except Exception:
            view.dispose()
            if view.parentWidget() is None:
                view.deleteLater()
            raise

    @Slot(str)
    def on_workspace_opened(self, panel_id: str) -> None:
        """Focus a panel after it has been added to the main workspace."""
        self.workspace.focus_panel(panel_id)

    @Slot(str)
    def on_workspace_closed(self, panel_id: str) -> None:
        """Keep the permanent main panel available after other panels close."""
        session = next((item for item in self.sessions if item.panel_id == panel_id), None)
        if session is not None:
            self.close_session(session)
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

    def on_confirmation_requested(self, session, turn_id, message, request_id, timeout):
        if turn_id != session.turn_id:
            return
        if session.stopping:
            session.worker.resolve_confirmation(False, request_id)
            return
        session.presentation.awaiting_permission(turn_id)
        title = tr("command.title")
        if len(self.sessions) > 1:
            title += " · " + tr("session.label", index=session.index + 1, count=len(self.sessions))
        deadline = QDeadlineTimer(timeout * 1000)
        countdown = QTimer(self)
        countdown.setInterval(250)

        def answered(accepted):
            countdown.stop()
            countdown.deleteLater()
            session.confirmation_dialogs.pop(request_id, None)
            session.presentation.awaiting_permission(turn_id, waiting=False)
            session.worker.resolve_confirmation(accepted, request_id)

        request = ChoiceDialog.of(self).ask(
            title, f"{tr('command.request')}\n\n{message}",
            [(tr("command.no"), NEUTRAL_BUTTON, lambda: answered(False)),
             (tr("command.yes"), NEUTRAL_BUTTON, lambda: answered(True))],
            on_cancel=lambda: answered(False))

        def show_remaining():
            remaining = max(0, (deadline.remainingTime() + 999) // 1000)
            if request.buttons:
                request.buttons[0].setText(f"{tr('command.no')} · {remaining}s")

        countdown.timeout.connect(show_remaining)
        show_remaining()
        countdown.start()
        session.confirmation_dialogs[request_id] = request

    def set_status(self, key, session=None):
        session = session or self.session
        session.status_key = key
        if session.ui is None:
            return
        session.ui.status.setText(tr(key) if key else "")
        session.ui.status.setVisible(bool(key))

    def set_enabled(self, enabled):
        for session in self._views():
            session.ui.input.setEnabled(enabled and session.submitting is None)
        self.update_send_button()

    def update_send_button(self, session=None):
        if session is None:
            for item in self._views():
                self.update_send_button(item)
            return
        ui = session.ui
        if ui is None:
            return
        has_text = bool(ui.input.toPlainText().strip())
        voice_active = self.voice_thread is not None and self.voice_session is session
        recording = self.recording and voice_active
        live_active = voice_active and self.voice_thread.live
        stopping_available = session.busy and session.speaking and not session.stopping
        ui.send.setText("" if stopping_available or recording or live_active else
                          "" if has_text else "")
        mic = not (stopping_available or recording or live_active
                   or has_text)
        if ui.send.property("mic") != mic:
            ui.send.setProperty("mic", mic)
            ui.send.style().unpolish(ui.send)
            ui.send.style().polish(ui.send)

        ui.send.setEnabled(
            session.ready and (live_active or recording or stopping_available or (
                    not voice_active and not session.busy and
                    session.submitting is None and ui.attachment_tray.can_send)))
        editable = session.ready and session.submitting is None and not voice_active
        ui.attach.setEnabled(editable)
        ui.model_selector.setEnabled(
            editable and not any(item.busy for item in self.sessions)
            and not self.model_switching and not MODEL_OVERRIDE)
        ui.model_selector.setToolTip(tr("ui.model_locked" if MODEL_OVERRIDE else "ui.model_hint"))
        ui.model_selector.setAccessibleName(tr("ui.model"))
        ui.attachment_tray.setEnabled(editable)
        ui.input.setEnabled(editable)
        ui.attach.setToolTip(tr("ui.attach_files"))
        ui.attach.setAccessibleName(tr("ui.attach_files"))
        key = ("ui.stop" if stopping_available or recording or live_active else
               "ui.send" if has_text else "voice.record")
        label = tr(key)
        ui.send.setAccessibleName(label)
        ui.send.setToolTip(
            tr("ui.stop_hint") if stopping_available else label)
        ui.input.setPlaceholderText(
            tr("ui.steering_input" if session.busy else "ui.input"))

    @Slot(str)
    def change_language(self, language):
        try:
            set_language(language)
        except (OSError, ValueError) as error:
            self.refresh_settings_workspaces()
            ChoiceDialog.of(self).notify(tr("ui.settings"), tr("ui.error", error=error))
            return
        self.refresh_language()

    def refresh_language(self):
        language = get_language()
        name = get_assistant_name()
        if language == self.active_language and name == getattr(self, "active_assistant_name", None):
            return
        self.active_language = language
        self.active_assistant_name = name
        self.setWindowTitle(f"{name} {load_dev_file()['version']}")
        self.refresh_session_titles()
        tray = getattr(self, "tray_icon", None)
        if tray is not None:
            tray.setToolTip(tr("tray.running"))
            actions = tray.contextMenu().actions()
            actions[0].setText(tr("tray.open"))
            actions[1].setText(tr("tray.quit"))
        for orb in (self.mascot, *(session.ui.orb for session in self._views())):
            orb.setToolTip(name)
        if hasattr(self, "command_palette"):
            self.command_palette.refresh_language()
        for panel in self.workspace.findChildren(WorkspacePanel):
            panel.refresh_language()
        for session in self._views():
            self._refresh_view_language(session)
        self.refresh_settings_workspaces()
        for view in self.workspace.findChildren(NovaView):
            view.refresh_language()
        for view in self.workspace.findChildren(HealthView):
            view.refresh_language()
        for view in self.workspace.findChildren(SongView):
            view.refresh_language()
        for navigation in self.workspace.findChildren(WorkspaceNavigation):
            navigation.refresh_language()
        self.update_send_button()

    def refresh_settings_workspaces(self):
        for view in self.workspace.findChildren(SettingsView):
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
            with QSignalBlocker(view.song_panel_switch):
                view.song_panel_switch.setChecked(
                    self.settings.value("song_panel", True, type=bool))
            with QSignalBlocker(view.orb_enabled_switch):
                view.orb_enabled_switch.setChecked(self.orb_enabled)
            view.refresh_language()

    def _refresh_view_language(self, session):
        ui = session.ui
        language = get_language()
        ui.task_progress.refresh_language(language)
        ui.activity_trail.refresh_language(language)
        ui.permission_selector.refresh_language()
        ui.attachment_tray.refresh()
        self.set_status(session.status_key, session)

    def refresh_privacy_indicator(self, session=None):
        for item in ([session] if session is not None else self._views()):
            if item.ui is not None:
                item.ui.privacy_indicator.setVisible(item.worker.session.private)

    def refresh_directory_indicators(self):
        for session in self._views():
            directory = session.worker.session.context.working_directory
            session.ui.directory_indicator.set_directory(directory)
            session.ui.branch_indicator.set_directory(directory)
            session.ui.input.refresh_file_tags()

    def on_ready(self, session):
        session.ready = True
        self.set_status("", session)
        self.set_orbs_visual_state(Orb.State.IDLE, session)
        self.set_enabled(True)
        session.ui.model_selector.refresh(self.assistant.selected_model)
        self._reveal_startup_controls(session)

        if self.isVisible() and session is self.session:
            session.ui.input.setFocus()

    @Slot(str)
    def request_model(self, model):
        if (not model or model == self.assistant.selected_model
                or any(session.busy for session in self.sessions) or self.model_switching):
            self._set_model_selectors(self.assistant.selected_model)
            return
        if is_cloud_model(model):
            def restore():
                self._set_model_selectors(self.assistant.selected_model)

            ChoiceDialog.of(self).ask(
                tr("ui.model"), tr("ui.cloud_model_confirm", model=model),
                [(tr("ui.cancel"), NEUTRAL_BUTTON, restore),
                 (tr("command.yes"), NEUTRAL_BUTTON, lambda: self.switch_model(model))],
                on_cancel=restore)
            return
        self.switch_model(model)

    def switch_model(self, model):
        self.model_switching = True
        self.update_send_button()
        self.model_request.emit(model)

    def _set_model_selectors(self, model):
        for session in self._views():
            session.ui.model_selector.set_current(model)

    @Slot(str)
    def on_model_changed(self, model):
        self.model_switching = False
        self._set_model_selectors(model)
        self.update_send_button()

    @Slot(str)
    def on_model_failed(self, error):
        self.model_switching = False
        self._set_model_selectors(self.assistant.selected_model)
        self.update_send_button()
        ChoiceDialog.of(self).notify(tr("ui.model"), error)

    def _reveal_startup_controls(self, session):
        """Slide the composer and subtitles into view after startup."""
        ui = session.ui
        for animation in ui.reveal_animations:
            animation.stop()
            animation.deleteLater()
        ui.reveal_animations.clear()

        ui.input_group.setVisible(True)
        ui.indicator_row.setVisible(True)
        ui.send.setVisible(True)
        ui.subtitles.setVisible(self.subtitles_enabled)
        ui.subtitles.setMaximumHeight(0)

        indicator_target = ui.indicator_row.sizeHint().height()
        input_target = max(ui.input_group.sizeHint().height()
                           + indicator_target, 48)
        subtitle_target = 90
        targets = (
            (ui.input_group, input_target),
            (ui.indicator_row, indicator_target),
            (ui.subtitles, subtitle_target),
        )
        for widget, target in targets:
            animation = QPropertyAnimation(widget, b"maximumHeight", widget)
            animation.setDuration(260)
            animation.setStartValue(0)
            animation.setEndValue(target)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            animation.finished.connect(
                lambda widget=widget: widget.setMaximumHeight(16777215))
            animation.start()
            ui.reveal_animations.append(animation)

    @Slot(bool)
    def toggle_subtitles(self, enabled: bool):
        self.subtitles_enabled = enabled
        for session in self._views():
            session.ui.subtitles.setVisible(enabled and session.ready)
        self.sync_mascot_subtitle()
        self.settings.setValue("subtitles", enabled)
        self.refresh_settings_workspaces()

    @Slot(bool)
    def toggle_mute(self, muted: bool):
        self.muted = bool(muted)
        self.settings.setValue("muted", self.muted)
        try:
            for session in self.sessions:
                session.worker.set_muted(self.muted)
        except Exception as error:
            ChoiceDialog.of(self).notify(tr("ui.mute"), str(error))
        if self.muted:
            for session in self.sessions:
                self.on_speaking(session, session.turn_id, False)
            for session in self._views():
                session.ui.orb.clear()
            self.mascot.clear()
        self.refresh_settings_workspaces()

    def toggle_orb_speech_pulse(self, enabled: bool):
        for orb in (self.mascot, *(session.ui.orb for session in self._views())):
            orb.set_speech_pulse_enabled(enabled)
        self.settings.setValue("orb_speech_pulse", enabled)
        self.refresh_settings_workspaces()

    @Slot(str)
    def set_permission_mode(self, mode):
        for session in self.sessions:
            session.worker.set_permission_mode(mode)
            if session.ui is not None and session.ui.permission_selector.mode != mode:
                with QSignalBlocker(session.ui.permission_selector):
                    session.ui.permission_selector.set_mode(mode)
        try:
            config = load_config()
            config["permission_mode"] = mode
            save_config(config)
        except (OSError, ValueError):
            logging.getLogger("assistant.permissions").exception(
                "Unable to persist permission mode")

    @Slot(bool)
    def toggle_ephemeral_steps(self, enabled: bool):
        for session in self._views():
            session.ui.activity_trail.set_steps_enabled(enabled)
        self.settings.setValue("ephemeral_steps", enabled)
        self.refresh_settings_workspaces()

    @Slot(bool)
    def toggle_song_panel(self, enabled: bool):
        self.settings.setValue("song_panel", enabled)
        self.song_panel_key = None
        self.refresh_settings_workspaces()

    @Slot(bool)
    def toggle_orb_enabled(self, enabled: bool):
        self.settings.setValue("orb_enabled", enabled)
        if not enabled:
            self.mascot.pop_out()
        self.refresh_settings_workspaces()

    def set_orbs_speaking(self, speaking: bool, session=None):
        for orb in self._orbs(session):
            orb.set_speaking(speaking)
        self.sync_mascot_subtitle()

    def set_orbs_listening(self, listening: bool, session=None):
        for orb in self._orbs(session):
            orb.set_listening(listening)

    def set_orbs_visual_state(self, state, session=None, *, fade_in=180, fade_out=180):
        for orb in self._orbs(session):
            orb.set_visual_state(state, fade_in=fade_in, fade_out=fade_out)

    def sync_mascot_subtitle(self):
        self.mascot_subtitles.set_subtitle(
            self.session.subtitle_text,
            self.subtitles_enabled and self.session.speaking)

    def update_subtitles(self, text, session=None):
        from PySide6.QtGui import QTextLayout
        session = session or self.session
        session.subtitle_text = text
        if session.ui is None:
            return
        subtitles = session.ui.subtitles
        font = subtitles.font()
        metrics = QFontMetrics(font)
        max_width = metrics.horizontalAdvance("M" * 56)
        available = max(1, subtitles.contentsRect().width() - 24)

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

        subtitles.setText(self.render_subtitle("\n".join(lines[-3:])))
        if session is self.session:
            self.sync_mascot_subtitle()

    @staticmethod
    def render_subtitle(text: str) -> str:
        """Enbold the font without rendering Markdown **"""
        escaped = html.escape(text)
        return (re.sub(r"\*\*(.+?)\*\*",
                       r"<b>\1</b>", escaped, flags=re.DOTALL, )
                .replace("\n", "<br>"))

    def toggle_private_mode(self):
        session = self.session.worker.session
        session.private = not session.private
        self.refresh_privacy_indicator(self.session)

    def reload_modules(self):
        session = self.session
        if session.ready and not session.busy and session.submitting is None:
            self.start_prompt(DesktopMessage("reload"), session)

    def exit_app(self):
        if self.quitting:
            return
        for session in self.sessions:
            if session.busy and not session.stopping:
                self.stop_response(session)
        self.request_quit()

    def send_message(self, session=None):
        session = session or self.session
        ui = session.ui
        if ui is None or not session.ready or (
                self.voice_thread is not None and self.voice_session is session):
            return

        if session.submitting is not None or not ui.attachment_tray.can_send:
            return
        controller = session.worker.session.context.task_controller if session.busy else None
        message = DesktopMessage(
            ui.input.toPlainText().strip(), ui.attachment_tray.snapshot(),
            resume_task_id=controller.state.id if controller is not None and controller.state.status == "active" else "")
        if not message.text and not message.attachments:
            return
        if session.busy and session.stopping:
            return
        session.submitting = message
        self.update_send_button(session)
        if session.busy:
            session.pending_prompt = message
            self.stop_response(session)
            return
        self.start_prompt(message, session)

    def on_request_accepted(self, session, turn_id):
        if turn_id != session.turn_id or session.submitting is None:
            return

        session.ui.input.remember()
        session.ui.input.clear()
        session.ui.attachment_tray.clear()
        session.submitting = None
        self.update_send_button()

    def on_request_rejected(self, session, turn_id, error):
        if turn_id != session.turn_id:
            return

        self._reset_response_timer(session)
        session.presentation.finish(turn_id, failed=True)
        self.finish_wake_command(session, "failed", error)
        session.submitting = None
        session.busy = False
        session.current_reply = None
        if (self.voice_thread is not None and self.voice_thread.live
                and self.voice_session is session):
            self.voice_thread.stop_event.set()
        self.update_send_button()
        ChoiceDialog.of(self).notify(tr("ui.attach_files"), error)

    @Slot()
    def on_mascot_record(self):
        """Start or stop microphone recording from compact mode."""
        session = self.session
        if self.recording or self.voice_thread is not None:
            self.on_send_clicked(self.voice_session or session)
            return

        if session.busy and session.speaking and not session.stopping:
            session.pending_voice_barge = True
            self.stop_response(session)
            return

        if (not session.ready or session.busy or
                self.voice_thread is not None):
            return

        self.start_recording(session=session)

    @property
    def orb_enabled(self) -> bool:
        return self.settings.value("orb_enabled", True, type=bool)

    def show_mascot(self):
        """Switch to compact desktop mode when the orb is enabled."""
        if self.orb_enabled:
            self.enter_background()

    def enter_background(self):
        """Hide the window, leaving the orb on screen when it is enabled."""
        if self.quitting or self._workspace_hiding:
            return
        self.command_palette.dismiss(restore_focus=False)
        if self.orb_enabled:
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
        """Restore the full assistant interface."""
        if self.quitting:
            return
        self.mascot.pop_out()
        if self._workspace_hiding:
            self._workspace_hiding = False
            self.workspace.animate_visibility(True)
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.show()
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

    def start_prompt(self, prompt, session=None):
        session = session or self.session
        session.active_prompt = prompt
        session.paused_prompt = None
        session.task_stop_requested = False
        self.set_status("", session)
        session.turn_id = next(self._turn_ids)
        session.presentation.begin(session.turn_id)
        session.worker.cancel_event = threading.Event()
        session.stopping = False
        session.permission_denied_state = False
        session.speaking = False

        self.set_command_output(session, "", False)

        session.current_reply = ""
        session.current_response_view = None
        self._start_response_timer(session)
        self.update_subtitles(prompt.display_text, session)

        session.busy = True
        self.set_enabled(True)

        try:
            if not session.worker_thread.isRunning():
                raise RuntimeError(tr("ui.worker_unavailable"))
            session.request.emit(session.turn_id, prompt)
        except Exception as error:
            self.on_request_rejected(session, session.turn_id, str(error))

    def set_command_output(self, session, text, visible):
        session.command_output = text
        session.command_output_visible = visible
        if session.ui is not None:
            session.ui.command_output.setPlainText(text)
            session.ui.command_output.setVisible(visible)

    def on_send_clicked(self, session=None):
        session = session or self.session
        if self.voice_thread is not None and self.voice_thread.live and self.voice_session in (session, None):
            voice_session = self.voice_session or session
            self.voice_thread.stop_event.set()
            if isinstance(voice_session.pending_prompt, DesktopVoiceMessage):
                voice_session.pending_prompt = None
            if voice_session.busy and not voice_session.stopping:
                self.stop_response(voice_session)
            self.recording = False
            self.set_orbs_listening(False, voice_session)
            self.update_send_button()
        elif self.recording and self.voice_session in (session, None):
            self.voice_thread.stop_event.set()
            self.recording = False
            self.update_send_button()
        elif self.voice_thread is not None and self.voice_session in (session, None):
            return
        elif session.busy:
            if session.speaking and not session.stopping:
                session.pending_voice_barge = True
                self.stop_response(session)
        elif session.ui is not None and session.ui.input.toPlainText().strip():
            self.send_message(session)
        else:
            self.start_recording(session=session)

    def start_recording(self, *, automatic=False, session=None):
        session = session or self.session
        ui = session.ui
        if (ui is None or not session.ready or session.busy or session.submitting is not None or
                self.voice_thread is not None):
            return
        if not self.assistant.voice.supports_playback_reference:
            ui.status.setText(tr("voice.restart"))
            ui.status.show()
            return
        try:
            self.assistant.voice.set_playback_reference(True)
        except RuntimeError as error:
            ui.status.setText(str(error))
            ui.status.show()
            return
        self.voice_thread = VoiceInputWorker(self, automatic=True, live=True)
        self.voice_session = session
        session.worker.live_capture = self.voice_thread
        self.voice_thread.levels.connect(self.on_voice_levels)
        self.voice_thread.processing.connect(self.on_voice_processing)
        self.voice_thread.speech_started.connect(self.on_voice_started)
        self.voice_thread.utterance.connect(self.on_voice_utterance)
        self.voice_thread.finished.connect(self.on_voice_finished)
        self.recording = True
        self.set_orbs_visual_state(Orb.State.WRITING, session)
        self.set_orbs_listening(True, session)
        ui.input.hide()
        ui.input_meter.clear()
        ui.input_meter.show()
        self.set_orbs_thinking(False, session)
        self.update_send_button()
        self.voice_thread.start()

    @Slot(object)
    def on_voice_levels(self, levels):
        session = self.voice_session or self.session
        if session.ui is not None and (not session.busy or session.stopping):
            session.ui.input_meter.set_levels(levels)
            for orb in self._orbs(session):
                orb.set_levels(levels)

    @Slot()
    def on_voice_started(self):
        if self.voice_thread is None or self.voice_thread.stop_event.is_set():
            return
        session = self.voice_session or self.session
        if session.busy and not session.stopping:
            self.stop_response(session)
        self.recording = True
        self.set_orbs_listening(True, session)
        self.set_orbs_visual_state(Orb.State.WRITING, session)
        if session.ui is not None:
            session.ui.input.hide()
            session.ui.input_meter.show()

    @Slot(object)
    def on_voice_utterance(self, message):
        if (self.quitting or self.voice_thread is None or
                self.voice_thread.stop_event.is_set()):
            return
        session = self.voice_session or self.session
        if session.busy:
            session.pending_prompt = message
            if not session.stopping:
                self.stop_response(session)
        else:
            self.start_prompt(message, session)

    def resume_live_listening(self, session):
        if (self.voice_thread is None or not self.voice_thread.live or
                self.voice_thread.stop_event.is_set() or self.voice_session is not session
                or session.busy or self.quitting or session.ui is None):
            return
        self.voice_thread.waiting_response.clear()
        self.recording = True
        self.set_orbs_visual_state(Orb.State.WRITING, session)
        self.set_orbs_listening(True, session)
        session.ui.input.hide()
        session.ui.input_meter.show()
        self.update_send_button()

    @Slot()
    def on_voice_processing(self):
        session = self.voice_session or self.session
        self.recording = False
        self.set_orbs_visual_state(Orb.State.PROCESSING, session)
        self.set_orbs_listening(False, session)
        self.mascot.clear()
        if session.ui is not None:
            session.ui.input_meter.hide()
            session.ui.input.show()
        self.update_send_button()

    @Slot()
    def on_voice_finished(self):
        worker = self.voice_thread
        if worker is None:
            return
        session = self.voice_session or self.session
        self.voice_thread = None
        self.voice_session = None
        session.worker.live_capture = None
        try:
            self.assistant.voice.set_playback_reference(False)
        except RuntimeError:
            logging.getLogger("assistant.voice").exception("Unable to stop playback reference")
        self.recording = False
        self.set_orbs_listening(False, session)
        self.mascot.clear()
        ui = session.ui
        if ui is not None:
            ui.input_meter.hide()
            ui.input_meter.clear()
            ui.input.show()
        worker.deleteLater()
        self.update_send_button()
        if self.closing_after_voice:
            self.close()
            return
        if ui is None:
            return
        if worker.error:
            ui.status.setText(worker.error)
            ui.status.show()
        elif worker.audio_wav and not worker.live:
            self.start_prompt(DesktopVoiceMessage(worker.audio_wav,
                                                  worker.transcript), session)

        if self.isVisible():
            ui.input.setFocus()

    def can_resume_task(self):
        session = self.session
        controller = session.worker.session.context.task_controller
        suspended = controller is not None and controller.state.status in {
            "interrupted", "waiting", "blocked", "limit_reached"}
        return (session.ready and (session.paused_prompt is not None or suspended) and not session.busy
                and not session.stopping and not self.recording and self.voice_thread is None
                and session.submitting is None and session.pending_prompt is None and not self.quitting)

    def pause_current_task(self):
        session = self.session
        if not session.ready or not session.busy or session.stopping:
            return
        session.paused_prompt = session.active_prompt
        self.stop_response(session)

    def cancel_current_task(self, session):
        from src.init.task_state import Lifecycle

        context = session.worker.session.context
        controller = context.task_controller
        if (controller is not None and controller.state is context.task_state
                and controller.state.status in {
                Lifecycle.INTERRUPTED, Lifecycle.WAITING, Lifecycle.BLOCKED, Lifecycle.LIMIT_REACHED}):
            controller.state.suspend(Lifecycle.CANCELLED, "Stopped by the user.")
            controller.context.task_controller = controller.pending_task
        session.task_stop_requested = False

    def stop_current_task(self):
        session = self.session
        if not session.ready or not (session.busy or session.paused_prompt is not None):
            return
        session.paused_prompt = None
        session.task_stop_requested = True
        self.set_status("", session)
        if session.busy:
            if not session.stopping:
                self.stop_response(session)
        else:
            self.cancel_current_task(session)

    def resume_current_task(self):
        if not self.can_resume_task():
            return
        session = self.session
        prompt = session.paused_prompt
        context = session.worker.session.context
        controller = context.task_controller
        if (controller is not None and (prompt is None
                or controller.state is context.task_state)
                and controller.state.status in {"interrupted", "waiting", "blocked", "limit_reached"}):
            prompt = DesktopMessage(tr("palette.resume_prompt"), prompt.attachments if prompt is not None else (),
                                    resume_task_id=controller.state.id)
        self.start_prompt(prompt, session)

    def stop_response(self, session=None):
        session = session or self.session
        self._stop_response_timer(session)
        session.stopping = True
        session.presentation.finish(session.turn_id, interrupted=True)
        session.worker.interrupt()
        session.speaking = False
        self.clear_orbs(session)
        self.set_orbs_speaking(False, session)
        self.set_orbs_thinking(False, session)
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

    def on_permission_denied(self, session, turn_id):
        if turn_id == session.turn_id:
            session.permission_denied_state = True
            session.presentation.permission_denied(turn_id)

    def on_chunk(self, session, turn_id, chunk):
        if turn_id != session.turn_id or session.current_reply is None:
            return

        session.current_reply += chunk
        if session.current_response_view is not None:
            session.current_response_view.append_chunk(chunk)
        session.presentation.writing(turn_id)

    def _forget_response_view(self, response_view):
        for session in self.sessions:
            if session.current_response_view is response_view:
                session.current_response_view = None

    def on_subtitle(self, session, turn_id, text):
        if turn_id == session.turn_id and not session.stopping:
            self.update_subtitles(text, session)

    def on_audio(self, session, turn_id, levels):
        if self.muted:
            return
        if (turn_id == session.turn_id and (session.busy or not session.ready)
                and not session.stopping):
            for orb in self._orbs(session):
                orb.set_levels(levels)

    def on_speaking(self, session, turn_id, speaking):
        if turn_id != session.turn_id:
            return
        session.speaking = (speaking and not self.muted and (session.busy or not session.ready)
                            and not session.stopping)
        if not session.ready:
            self.set_orbs_visual_state(Orb.State.READING if session.speaking else Orb.State.IDLE, session)
        else:
            session.presentation.speaking(turn_id, session.speaking)

        self.set_orbs_speaking(session.speaking, session)

        self.update_send_button()

    def on_finished(self, session, reply):
        self._stop_response_timer(session)
        interrupted = session.stopping
        if session.current_response_view is not None:
            session.current_response_view.finish(reply)
        session.presentation.finish(session.turn_id, interrupted=interrupted,
                                    failed=session.permission_denied_state)
        task_state = session.worker.session.context.task_state
        if session.paused_prompt is not None and (
                task_state is not None and task_state.status == "complete" or task_state is None and reply):
            session.paused_prompt = None
        if session.task_stop_requested:
            self.cancel_current_task(session)
        task_failed = session.presentation.view.state in {"error", "waiting", "stopped"}
        self.finish_wake_command(session, "failed" if interrupted or task_failed else "completed",
                                 "Interrupted" if interrupted else
                                 task_state.notice if task_failed and task_state is not None else
                                 tr("task_progress.error") if task_failed else "")
        if session.worker.command_reply:
            self.set_command_output(session, reply, True)
            self.update_subtitles(reply.splitlines()[0], session)
        elif not session.current_reply:
            self.update_subtitles(reply or tr("status.paused" if session.paused_prompt is not None else
                                              "status.stopped" if interrupted else "ui.no_response"), session)
        else:
            self.update_subtitles("", session)

        session.current_reply = None
        session.current_response_view = None
        session.busy = False
        session.speaking = False
        session.stopping = False
        if session.paused_prompt is not None:
            self.set_status("status.paused", session)
        self.clear_orbs(session)
        self.set_orbs_speaking(False, session)
        self.set_orbs_thinking(False, session)
        QTimer.singleShot(700, session.presentation,
                          lambda turn_id=session.turn_id, presentation=session.presentation:
                          presentation.settle(turn_id))
        self.refresh_privacy_indicator(session)
        self.set_enabled(True)
        if self.isVisible() and session is self.session:
            session.ui.input.setFocus()

        if self.assistant.shutdown_requested.is_set():
            self.quitting = True
            QTimer.singleShot(0, self.close)
            return

        snapshot, session.completed_git_diff = session.completed_git_diff, None
        if snapshot is not None and not interrupted and not task_failed:
            from src.init.visuals.diff_workspace import DiffWorkspacePanel
            directory, diff = snapshot
            self.workspace.open_registered_panel(
                "git_diff", tr("git_workspace.title"), lambda: DiffWorkspacePanel(directory, diff))

        self.resume_after_turn(session)
        if self.quitting:
            QTimer.singleShot(0, self.close)

    def resume_after_turn(self, session, *, live=True):
        if session.pending_wake_barge:
            session.pending_wake_barge = False
            self.start_recording(automatic=True, session=session)
            self.finish_wake_command(
                session, "completed" if self.recording else "failed",
                "" if self.recording else "Recording was unavailable",
            )
        elif session.pending_voice_barge:
            session.pending_voice_barge = False
            QTimer.singleShot(0, lambda: self.start_recording(session=session))
        else:
            self.resume_pending_prompt(session)
            if live:
                self.resume_live_listening(session)

    def resume_pending_prompt(self, session):
        if self.assistant.shutdown_requested.is_set():
            session.pending_prompt = None
            return
        prompt, session.pending_prompt = session.pending_prompt, None
        if prompt:
            self.start_prompt(prompt, session)

    def on_error(self, session, error):
        if (self.voice_thread is not None and self.voice_thread.live
                and self.voice_session is session):
            self.voice_thread.stop_event.set()
        if session.task_stop_requested:
            self.cancel_current_task(session)
        if not session.ready:
            session.status_key = ""
            if session.ui is not None:
                session.ui.status.setText(tr("ui.error", error=error))
                session.ui.status.show()

        self._reset_response_timer(session)
        session.presentation.finish(session.turn_id, failed=True)
        self.finish_wake_command(session, "failed", error)
        self.update_subtitles(tr("ui.error", error=error), session)
        session.current_reply = None
        if session.current_response_view is not None:
            session.current_response_view.finish()
        session.current_response_view = None
        session.busy = False
        session.speaking = False
        session.stopping = False
        self.clear_orbs(session)
        self.set_orbs_speaking(False, session)
        self.set_orbs_thinking(False, session)
        if not session.ready:
            self.set_orbs_visual_state(Orb.State.DENIED_ERROR, session, fade_in=100, fade_out=300)
        QTimer.singleShot(700, session.presentation,
                          lambda turn_id=session.turn_id, presentation=session.presentation:
                          presentation.settle(turn_id))

        self.set_enabled(True)
        self.resume_after_turn(session, live=False)
        if self.quitting:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event):
        if not self.quitting:
            event.ignore()
            self.enter_background()
            return

        unregister_capture_handler(self.capture_handler)
        unregister_clipboard_handler(self.clipboard_handler)
        self.flowchart_bridge.shutdown()
        self.terminal_bridge.shutdown()
        self.response_bridge.shutdown()
        self.song_monitor.stop()
        if self.voice_thread is not None:
            self.closing_after_voice = True
            self.voice_thread.requestInterruption()
            self.voice_thread.stop_event.set()
            event.ignore()
            return
        if any(session.worker_thread.isRunning() and session.busy for session in self.sessions):
            event.ignore()
            return

        if self.isVisible() and not self._workspace_exit_ready:
            event.ignore()
            if not self._workspace_hiding:
                self._workspace_hiding = True
                self.workspace.animate_visibility(False, on_finished=self._finish_workspace_exit)
            return

        kill_self()
        threads = [session.worker_thread for session in (*self.sessions, *self.closing_sessions)
                   if isValid(session.worker_thread)]
        for thread in threads:
            if thread.isRunning():
                thread.quit()
        for thread in threads:
            thread.wait()

        self.mascot.close()
        event.accept()
        QTimer.singleShot(0, QApplication.instance().quit)

    def _finish_workspace_exit(self):
        self._workspace_hiding = False
        self._workspace_exit_ready = True
        self.close()


def set_app_id():
    """Identify the assistant as an independent application to the desktop shell."""
    current_platform().set_app_id(ASSISTANT_INSTANCE_SERVER)


def notify_running_instance(timeout_ms: int = 1500) -> bool:
    """Ask an existing desktop process to bring its window to the front."""
    socket = QLocalSocket()
    socket.connectToServer(
        ASSISTANT_INSTANCE_SERVER,
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
                 f"{get_assistant_identifier()}-desktop-{getuser()}.lock")
    lock = QLockFile(str(lock_path))
    return lock if lock.tryLock(100) else None


def start_instance_server() -> QLocalServer:
    """Open the local activation endpoint for the lock-owning process."""
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if server.listen(ASSISTANT_INSTANCE_SERVER):
        return server

    QLocalServer.removeServer(ASSISTANT_INSTANCE_SERVER)
    if not server.listen(ASSISTANT_INSTANCE_SERVER):
        raise RuntimeError(server.errorString())
    return server


def install_tray_icon(app: QApplication, window: AssistantWindow, icon: QIcon):
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
    set_app_id()
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
        app.setProperty("codeFontFamily", nerd_font)
        
        font = QFont(main_font, 11)
        font.setKerning(True)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100)
        app.setFont(font)
        app.setEffectEnabled(Qt.UIEffect.UI_AnimateCombo, False)
        window = AssistantWindow()
        window.show()

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
        QLocalServer.removeServer(ASSISTANT_INSTANCE_SERVER)
        instance_lock.unlock()
        running_lock.release()
