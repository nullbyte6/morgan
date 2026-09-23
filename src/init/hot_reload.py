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
"""Reload live Arlo source modules while preserving process-owned state."""
from __future__ import annotations

import importlib
import re
import sys
import unicodedata
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STYLESHEET_PATH = PROJECT_ROOT / "assets" / "arlo.qss"
_stylesheet_bridge = None

# These modules own live threads, locks, GUI bridges, open sessions, or context
# variables. Recreating those globals would disconnect the running application.
_PRESERVED = {
    "src.init.hot_reload",
    "src.init.identity",
    "src.init.voice_ipc",
    "src.init.commands",
    "src.init.notifications",
    "src.init.session_log",
    "src.init.attachments",
    "src.init.app_manager",
    "src.init.steam",
    "src.init.desktop.capture",
    "src.init.desktop.clipboard",
    "src.init.visuals.bridge",
    "src.init.visuals.schema",
}
_PRESERVED_PREFIXES = ("src.init.memory.",)
_RELOAD_LAST = ("src.init.brain", "src.init.rules", "src.init.tools")


def is_reload_command(text: str) -> bool:
    """Recognize explicit reload requests without sending them to the model."""
    normalized = "".join(
        character for character in unicodedata.normalize(
            "NFKD", str(text).casefold())
        if not unicodedata.combining(character))
    normalized = re.sub(r"\s+", " ", normalized.strip(" \t\r\n.!?"))
    if normalized in {"ref", "reload", "/reload", "recarga", "/recarga",
                      "recargar", "/recargar", "hot reload",
                      "actualiza modulos", "actualizar modulos",
                      "actualiza los modulos", "actualizar los modulos",
                      "actualiza todos los modulos",
                      "actualizar todos los modulos",
                      "actualiza sus modulos", "actualizar sus modulos",
                      "update modules", "update all modules",
                      "reload modules", "reload all modules"}:
        return True
    return re.fullmatch(
        r"(?:reload|recarga|recargar|actualiza|actualizar|update|refresh) (?:(?:los|todos los|sus|all|the) )?(?:"
        r"modulos|modules|archivos|ficheros|files)"
        r"(?: de (?:arlo|init(?: y diagnostics)?|diagnostics)|"
        r" in (?:arlo|init(?: and diagnostics)?))?|"
        r"(?:reload|recarga|recargar|actualiza|actualizar|update|refresh) (?:(?:el|the) )?(?:"
        r"arlo|codigo|source|the source|"
        r"la hoja de estilos|hoja de estilos|los estilos|estilos|stylesheet)",
        normalized,
    ) is not None


def _is_project_source(module) -> bool:
    filename = getattr(module, "__file__", None)
    if not filename or not str(filename).lower().endswith(".py"):
        return False
    try:
        Path(filename).resolve().relative_to(PROJECT_ROOT)
    except (OSError, ValueError):
        return False
    return True


def _reload_stylesheet(errors: list[str]) -> bool:
    """Queue the global stylesheet update on Qt's application thread."""
    if "PySide6.QtWidgets" not in sys.modules:
        return False

    from PySide6.QtCore import QObject, Qt, Signal, Slot
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return False

    try:
        stylesheet = STYLESHEET_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        errors.append(f"{STYLESHEET_PATH}: {error}")
        return False

    class StylesheetBridge(QObject):
        requested = Signal(str)

        def __init__(self, application):
            super().__init__()
            self.application = application
            self.requested.connect(
                self.apply, Qt.ConnectionType.QueuedConnection)

        @Slot(str)
        def apply(self, value: str):
            self.application.setStyleSheet(value)
            for widget in self.application.topLevelWidgets():
                if widget.styleSheet():
                    widget.setStyleSheet(value)

    global _stylesheet_bridge
    if (_stylesheet_bridge is None
            or _stylesheet_bridge.application is not app):
        _stylesheet_bridge = StylesheetBridge(app)
        _stylesheet_bridge.moveToThread(app.thread())
    _stylesheet_bridge.requested.emit(stylesheet)
    return True


def reload_project_modules() -> tuple[list[str], list[str]]:
    """Reload loaded project modules in dependency-friendly order.

    Process-owned infrastructure is intentionally retained so timers, Qt signal
    bridges, locks, active attachments, and open logs remain valid. Tool modules
    are reloaded last and the caller rebuilds the model's tool registry.
    """
    importlib.invalidate_caches()
    modules = {
        name: module for name, module in tuple(sys.modules.items())
        if (module is not None and name.startswith("src.")
            and name not in _PRESERVED
            and not name.startswith(_PRESERVED_PREFIXES)
            and _is_project_source(module))
    }
    deferred = [name for name in _RELOAD_LAST if name in modules]
    ordinary = sorted(
        (name for name in modules if name not in deferred),
        key=lambda name: (name.count("."), name),
        reverse=True,
    )
    reloaded = []
    errors = []
    for name in ordinary + deferred:
        try:
            importlib.reload(modules[name])
            reloaded.append(name)
        except Exception as error:
            errors.append(f"{name}: {error}")
    if _reload_stylesheet(errors):
        reloaded.append("assets/arlo.qss")
    return reloaded, errors
