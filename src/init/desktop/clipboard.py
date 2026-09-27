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
"""Thread-safe bridge between assistant tools and Qt's system clipboard."""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from ..config import HOME_PATH
from typing import Callable, Optional


@dataclass
class ClipboardRequest:
    """One clipboard read request and its completion state."""

    completed: threading.Event = field(default_factory=threading.Event)
    success: bool = False
    error: str = ""
    value: Optional[str] = None


_bridge_lock = threading.Lock()
_bridge_handler: Optional[Callable[[ClipboardRequest], None]] = None


def register_clipboard_handler(handler: Callable[[ClipboardRequest], None]):
    """Register the desktop GUI's clipboard request handler."""
    global _bridge_handler
    with _bridge_lock:
        _bridge_handler = handler


def unregister_clipboard_handler(
        handler: Optional[Callable[[ClipboardRequest], None]] = None):
    """Remove a handler without affecting a newer desktop instance."""
    global _bridge_handler
    with _bridge_lock:
        if handler is None or _bridge_handler == handler:
            _bridge_handler = None


def read_clipboard(timeout: float = 10.0) -> str:
    """Read the current system clipboard.

    Use when the user asks to inspect, paste, summarize, or act on clipboard
    content. Text is returned directly, copied file paths are returned as JSON,
    and a copied image is saved locally and returned as an absolute path.
    """
    with _bridge_lock:
        handler = _bridge_handler
    if handler is None:
        return "Clipboard access is available only while the desktop app is open."

    request = ClipboardRequest()
    try:
        handler(request)
    except Exception as error:
        return f"Clipboard request failed: {error}"
    if not request.completed.wait(timeout):
        return "Clipboard request timed out."
    if not request.success:
        return request.error or "The clipboard is empty or unsupported."
    return request.value or "The clipboard is empty."


def request_clipboard_paste(timeout: float = 10.0) -> str:
    """Backward-compatible alias for clipboard reads."""
    return read_clipboard(timeout)


def read_clipboard_on_gui_thread() -> Optional[str]:
    """Read clipboard content with Qt. Must run on the GUI thread."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication is not running.")
    mime = app.clipboard().mimeData()
    if mime is None:
        return None

    if mime.hasUrls():
        paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
        if paths:
            return json.dumps({"clipboard_files": paths}, ensure_ascii=False)

    if mime.hasImage():
        image = app.clipboard().image()
        if not image.isNull():
            directory = HOME_PATH / "clipboard"
            directory.mkdir(parents=True, exist_ok=True)
            path = (directory / f"clipboard-{uuid.uuid4().hex}.png").resolve()
            if not image.save(str(path), "PNG"):
                raise RuntimeError("Unable to save the clipboard image.")
            return json.dumps({"clipboard_image": str(path)}, ensure_ascii=False)

    if mime.hasText():
        text = mime.text()
        return text if text else None
    return None


def is_valid_clipboard_content() -> bool:
    """Return whether the active Qt clipboard contains supported content."""
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return False
        mime = app.clipboard().mimeData()
        return bool(mime and (mime.hasText() or mime.hasImage()
                              or mime.hasUrls()))
    except (ImportError, RuntimeError):
        return False
