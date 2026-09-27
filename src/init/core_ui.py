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

from src.init.sessions import SessionManager
from src.init.ollama_backend import SharedOllamaBackend
from src.init.voice_client import SharedVoiceChannel
from src.init.desktop.chat_workspace import ChatWorkspace

class SessionProjection:
    def __init__(self, host, session, target):
        self.host = host
        self.session = session
        self.target = target

    def __getattr__(self, name):
        value = getattr(self.target, name)
        if not callable(value):
            return value
        def projected(*args, **kwargs):
            if self.host.session_manager.desktop_session is self.session:
                return value(*args, **kwargs)
            if name == "isVisible":
                return False
        return projected


class AssistantWindow(DesktopWindow):
    capture_requested = Signal(object)
    clipboard_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.settings = QSettings(DEFAULTS["assistant"]["name"].upper(), "desktop")
        self.session_manager = SessionManager(SharedOllamaBackend())
        self.audio = SharedVoiceChannel(self.session_manager)
        self.session_manager.audio = self.audio
        register_assistant(lambda: self.session_manager)
        self.quitting = False
        self._workspace_hiding = False
        self._workspace_exit_ready = False
        self.workspace = Workspace()
        self.workspace.manual_content_factory = self.workspace_content
        self.workspace.panel_focused.connect(self.on_panel_focused)
        self.workspace.panel_closed.connect(self.on_panel_closed)
        self.mascot = Orb(size=120, floating=True, line_width=4.2, fill_ratio=0.54)
        self.mascot.hide()
        self.mascot_subtitles = MascotSubtitleBubble(self.mascot)
        self.mascot.record_requested.connect(self.on_mascot_record)
        self.mascot.restore_requested.connect(self.restore_from_mascot)
        self.mascot.setContextMenuPolicy(Qt.CustomContextMenu)
        self.mascot.customContextMenuRequested.connect(self.mascot_menu)
        self.zoom_view = ZoomView(self.workspace, self, self.settings.value("ui_zoom", 100, type=int))
        self.zoom_view.zoom_changed.connect(lambda value: self.settings.setValue("ui_zoom", value))
        self.setCentralWidget(self.zoom_view)
        self.setWindowTitle(f"{get_assistant_name()} {load_dev_file()['version']}")
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parents[2] / "assets" / "arlo.ico")))
        self.build_command_palette()
        self.new_session_shortcut = QShortcut(QKeySequence("Ctrl+Shift+N"), self)
        self.new_session_shortcut.activated.connect(self.create_session)
        self.mascot_shortcut = QShortcut(QKeySequence("Ctrl+Shift+M"), self)
        self.mascot_shortcut.activated.connect(self.show_mascot)
        self._workspace_shortcut_map = {
            value["shortcut"].rsplit("+", 1)[-1]: key for key, value in WORKSPACE_VIEW_CONFIG.items()}
        self._workspace_shortcuts = []
        for key, value in WORKSPACE_VIEW_CONFIG.items():
            shortcut = QShortcut(QKeySequence(value["shortcut"]), self)
            shortcut.activated.connect(lambda key=key: self.open_workspace_view(key))
            self._workspace_shortcuts.append(shortcut)
        self._workspace_chord_pending = False
        self._workspace_chord_timer = QTimer(self)
        self._workspace_chord_timer.setSingleShot(True)
        self._workspace_chord_timer.setInterval(700)
        self._workspace_chord_timer.timeout.connect(self._open_pending_workspace)
        QApplication.instance().installEventFilter(self)
        self.capture_requested.connect(self.on_screenshot_requested, Qt.QueuedConnection)
        self.clipboard_requested.connect(self.on_clipboard_requested, Qt.QueuedConnection)
        self.capture_handler = self.capture_requested.emit
        self.clipboard_handler = self.clipboard_requested.emit
        register_capture_handler(self.capture_handler)
        register_clipboard_handler(self.clipboard_handler)
        self.flowchart_bridge = FlowchartBridge(self)
        self.browser_bridge = BrowserBridge(self)
        self.terminal_bridge = TerminalBridge(self)
        self.response_bridge = ResponseBridge(self)
        self.setStyleSheet(get_stylesheet())
        self.create_session()
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(250)
        self.poll_timer.timeout.connect(self.poll_sessions)
        self.poll_timer.start()

    @property
    def name(self):
        return get_assistant_name()

    def create_session(self):
        session = self.session_manager.create()
        if session is None:
            self.status_message(tr("sessions.limit"))
            return None
        self.session_manager.focus(session)
        self.session_manager.acquire_voice(session)
        try:
            chat = ChatWorkspace(session, self)
            panel_id = self.workspace.open_panel(
                title=f"{get_assistant_name()} {load_dev_file()['version']}",
                content=chat, panel_id=session.session_id)
            session.panel_id = panel_id
            panel = self.workspace.get_panel(panel_id)
            panel.setProperty("session_id", session.session_id)
            panel.setToolTip(session.session_id[:8])
            if not hasattr(self, "file_drop_router"):
                self.file_drop_router = FileDropRouter(
                    self.workspace, chat.input, chat.attachment_tray, self)
            else:
                self.file_drop_router.register_composer(chat.input, chat.attachment_tray)
            self.focus_session(session)
            return session
        except Exception:
            self.close_session(session)
            raise

    def status_message(self, message):
        session = self.session_manager.focused_session
        if session is not None and session.workspace is not None:
            session.workspace.status.setText(message)
            session.workspace.status.show()

    def focus_session(self, session):
        if session is None or session.closing or session.closed:
            return
        self.session_manager.focus(session)
        self.workspace.focus_panel(session.panel_id)
        if session.workspace.ready:
            session.workspace.input.setFocus()

    def on_panel_focused(self, panel_id):
        panel = self.workspace.get_panel(panel_id)
        if panel is not None:
            session = self.session_manager.get(panel.property("session_id") or panel_id)
            if session is not None:
                self.session_manager.focus(session)
        if hasattr(self, "command_palette"):
            self.command_palette.dismiss(restore_focus=False)

    def on_panel_closed(self, panel_id):
        session = self.session_manager.get(panel_id)
        if session is not None:
            self.close_session(session)

    def focused_chat(self):
        session = self.session_manager.focused_session
        return session.workspace if session is not None else None

    def workspace_content(self):
        chat = self.focused_chat()
        return chat.workspace_content() if chat is not None else QWidget()

    def focus_main_workspace(self):
        self.focus_session(self.session_manager.focused_session)

    def open_workspace(self, direction=None):
        chat = self.focused_chat()
        if chat is not None:
            chat.open_workspace(direction)

    def open_workspace_view(self, key, source=None):
        chat = self.focused_chat()
        if chat is not None:
            chat.open_workspace_view(key, source)

    def open_terminal_command(self, command):
        chat = self.focused_chat()
        if chat is None:
            raise RuntimeError("No Arlo session is focused")
        chat.open_terminal_command(command)

    def _open_pending_workspace(self):
        self._workspace_chord_pending = False
        self.open_workspace()

    def build_command_palette(self):
        commands = [
            Command("session.new", "sessions.new", self.create_session, ("new session", "nueva sesión")),
            Command("workspace.new", "palette.new_workspace", self.open_workspace),
            Command("workspace.chat", "palette.chat", self.focus_main_workspace),
            Command("task.stop", "palette.stop_task", lambda: self.focused_chat().stop_current_task(),
                    available=lambda: self.focused_chat() is not None and self.focused_chat().busy),
            Command("task.pause", "palette.pause_task", lambda: self.focused_chat().pause_current_task(),
                    available=lambda: self.focused_chat() is not None and self.focused_chat().busy),
            Command("task.resume", "palette.resume_task", lambda: self.focused_chat().resume_current_task(),
                    available=lambda: self.focused_chat() is not None and self.focused_chat().can_resume_task()),
            Command("session.select", "sessions.select", self.session_menu),
            Command("session.desktop", "sessions.desktop", lambda: self.session_menu(desktop=True)),
            Command("session.close", "sessions.close",
                    lambda: self.close_session(self.session_manager.focused_session)),
        ]
        commands.extend(Command(f"workspace.{key}", f"palette.{key}",
                                lambda key=key: self.open_workspace_view(key)) for key in WORKSPACE_VIEW_CONFIG)
        self.command_palette = CommandPalette(CommandRegistry(commands), self)

    def open_command_palette(self):
        if not self.quitting:
            self.command_palette.open(self.workspace)

    def session_menu(self, desktop=False):
        menu = QMenu(self)
        for session in tuple(self.session_manager.sessions.values()):
            if session.closing:
                continue
            view = session.workspace.task_presentation.view
            label = view.title or tr("sessions.idle")
            action = menu.addAction(f"{get_assistant_name()} · {label} · {view.lifecycle} · {session.session_id[:6]}")
            action.triggered.connect(
                lambda checked=False, session=session: self.project_session(session) if desktop else self.focus_session(session))
        menu.popup(QCursor.pos())
        self._session_menu = menu

    def mascot_menu(self, position):
        self.session_menu(desktop=True)

    def mascot_projection(self, session):
        return SessionProjection(self, session, self.mascot)

    def subtitle_projection(self, session):
        return SessionProjection(self, session, self.mascot_subtitles)

    def project_session(self, session):
        if not self.session_manager.project(session):
            return
        self.sync_mascot()
        self.mascot.pop_in()

    def sync_mascot(self):
        session = self.session_manager.desktop_session
        if session is None or session.workspace is None:
            self.mascot_subtitles.set_subtitle("", False)
            return
        chat = session.workspace
        view = chat.task_presentation.view
        self.mascot.set_thinking(view.active and view.orb_state == Orb.State.PROCESSING)
        self.mascot.set_visual_state(view.orb_state)
        self.mascot.set_listening(chat.recording)
        self.mascot.set_speaking(chat.speaking)
        self.mascot.setToolTip(view.title or get_assistant_name())
        chat.sync_mascot_subtitle()

    def show_mascot(self, session=None):
        if self.quitting or self._workspace_hiding:
            return
        if not isinstance(session, type(self.session_manager.focused_session)):
            session = None
        session = session or self.session_manager.focused_session
        if session is None:
            return
        self.project_session(session)
        self.command_palette.dismiss(restore_focus=False)
        if self.isVisible():
            self._workspace_hiding = True
            self.workspace.animate_visibility(False, on_finished=self._hide_workspace)

    def _hide_workspace(self):
        self._workspace_hiding = False
        self.hide()

    def restore_from_mascot(self):
        if self.quitting:
            return
        session = self.session_manager.desktop_session or self.session_manager.focused_session
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._workspace_hiding = False
        self.workspace.animate_visibility(True)
        self.focus_session(session)

    def on_mascot_record(self):
        session = self.session_manager.desktop_session
        if session is not None:
            session.workspace.on_mascot_record()

    def poll_sessions(self):
        for session in tuple(self.session_manager.sessions.values()):
            if session.closing:
                self.finish_session_close(session)
            elif session.workspace is not None:
                session.workspace.poll_wake_commands()
        self.sync_mascot()

    def open_owned_panel(self, session_id, turn_id, title, content, key=None):
        session = self.session_manager.get(session_id)
        if session is None or not session.accepts(session_id, turn_id):
            content.deleteLater()
            raise RuntimeError("The originating session or turn is unavailable")
        if key:
            content.setProperty("workspaceViewKey", key)
        panel_id = self.workspace.open_panel(title=title, content=content,
                    target_id=session.panel_id, focus=False)
        panel = self.workspace.get_panel(panel_id)
        panel.setProperty("session_id", session_id)
        panel.setProperty("turn_id", turn_id)
        return panel_id

    def close_session(self, session):
        if session is None or not self.session_manager.begin_close(session):
            return
        if self.session_manager.desktop_session is None:
            self.mascot.hide()
            self.mascot_subtitles.hide()
        from .app_manager import cancel_session_operations
        from .notifications import close_session_timers
        cancel_session_operations(session.session_id)
        close_session_timers(session.session_id)
        if session.workspace is not None:
            session.workspace.setParent(self)
            session.workspace.hide()
            session.workspace.stop_for_close()
        self.terminal_bridge.cancel_session(session.session_id)
        for bridge in (self.flowchart_bridge, self.browser_bridge, self.response_bridge):
            bridge.cancel_session(session.session_id)
        for request in tuple(session.pending_requests):
            request.error = "Session closed"
            request.completed.set()
        for panel_id in tuple(self.workspace.panel_ids):
            panel = self.workspace.get_panel(panel_id)
            if panel_id == session.panel_id or panel.property("session_id") == session.session_id:
                self.workspace.close_panel(panel_id)
        for candidate in self.session_manager.sessions.values():
            if not candidate.closing:
                self.focus_session(candidate)
                break

    def finish_session_close(self, session):
        if not session.closing:
            return
        if any(panel_id == session.panel_id or
               self.workspace.get_panel(panel_id).property("session_id") == session.session_id
               for panel_id in self.workspace.panel_ids):
            return
        from .app_manager import close_session_operations
        if self.terminal_bridge.session_running(session.session_id):
            return
        if not close_session_operations(session.session_id):
            return
        if not self.session_manager.complete_close(session):
            return
        if session.workspace is not None:
            session.workspace.deleteLater()
        if session.worker is not None:
            session.worker.deleteLater()
        if session.thread is not None:
            session.thread.deleteLater()
        if self.quitting and not self.session_manager.sessions:
            self.close()

    def request_quit(self):
        if self.quitting:
            return
        self.quitting = True
        self.session_manager.shutdown_requested.set()
        for session in tuple(self.session_manager.sessions.values()):
            self.close_session(session)
        if not self.session_manager.sessions:
            self.close()

    def closeEvent(self, event):
        if not self.quitting:
            event.ignore()
            self.show_mascot()
            return
        if self.session_manager.sessions:
            event.ignore()
            return
        unregister_capture_handler(self.capture_handler)
        unregister_clipboard_handler(self.clipboard_handler)
        for bridge in (self.flowchart_bridge, self.browser_bridge, self.terminal_bridge, self.response_bridge):
            bridge.shutdown()
        self.audio.close()
        self.mascot.close()
        self.mascot_subtitles.close()
        self.poll_timer.stop()
        event.accept()
        QTimer.singleShot(0, QApplication.instance().quit)

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


    @Slot(object)
    def on_screenshot_requested(self, request: CaptureRequest):
        """Run a screenshot request on the GUI thread."""
        if request.completed.is_set():
            return
        identity = request.identity
        if identity is None or not identity.session.accepts(identity.session_id, identity.turn_id):
            request.error = "Session closed"
            request.completed.set()
            return
        identity.session.pending_requests.add(request)

        mascot_visible = self.mascot.isVisible()
        if mascot_visible:
            self.mascot.hide()

        QTimer.singleShot(180,
                          lambda: self.finish_screenshot(request,
                                                         mascot_visible))


    def finish_screenshot(self, request: CaptureRequest, mascot_visible: bool):
        """Capture the screen, restore the mascot and report the result."""
        try:
            identity = request.identity
            if request.completed.is_set() or not identity.session.accepts(identity.session_id, identity.turn_id):
                return
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
            request.identity.session.pending_requests.discard(request)
            if mascot_visible and self.session_manager.desktop_session is not None and not self.quitting:
                self.mascot.show()


    @Slot(object)
    def on_clipboard_requested(self, request: ClipboardRequest):
        """Read Qt's clipboard on the GUI thread for an assistant tool call."""
        if request.completed.is_set():
            return
        identity = request.identity
        if identity is None or not identity.session.accepts(identity.session_id, identity.turn_id):
            request.error = "Session closed"
            request.completed.set()
            return
        identity.session.pending_requests.add(request)
        try:
            request.value = read_clipboard_on_gui_thread()
            request.success = request.value is not None
            if not request.success:
                request.error = "The clipboard is empty or unsupported."
        except Exception as error:
            request.error = str(error)
        finally:
            request.completed.set()
            identity.session.pending_requests.discard(request)



def set_windows_app_id():
    """Identify the assistant as an independent Windows application."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            ASSISTANT_INSTANCE_SERVER)


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
    set_windows_app_id()
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
        window = AssistantWindow()
        window.show()
        icon_font = QFont(nerd_font, 18)

        for button in (
                window.focused_chat().send,
                window.focused_chat().attach):
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
        QLocalServer.removeServer(ASSISTANT_INSTANCE_SERVER)
        instance_lock.unlock()
        running_lock.release()
