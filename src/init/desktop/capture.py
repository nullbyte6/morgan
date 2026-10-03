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
from __future__ import annotations

import threading
from dataclasses import dataclass, field



@dataclass
class CaptureRequest:
    """One screenshot request and its completion state."""
    completed: threading.Event = field(default_factory=threading.Event)
    success: bool = False
    error: str = ""
    return_image: bool = False
    image_data: bytes | None = None

_bridge_lock = threading.Lock()
_bridge_handler = None


def request_screen_image(timeout: float = 10.0) -> bytes:
    """Capture the primary screen and return PNG bytes."""
    with _bridge_lock:
        handler = _bridge_handler

    if handler is None:
        raise RuntimeError("Unavailable screenshot services")
    request = CaptureRequest(return_image=True)
    handler(request)
    if not request.completed.wait(timeout):
        raise TimeoutError("Request timed out")

    if not request.success:
        raise RuntimeError(request.error or "Couldn't take a screenshot")

    if not request.image_data:
        raise RuntimeError("Screenshot has no image data")

    return request.image_data

def register_capture_handler(handler):
    """Register the desktop GUI's screenshot request handler."""
    global _bridge_handler
    with _bridge_lock:
        _bridge_handler = handler


def unregister_capture_handler(handler):
    """Remove a handler without affecting a newer desktop instance."""
    global _bridge_handler
    with _bridge_lock:
        if _bridge_handler == handler:
            _bridge_handler = None


def request_screenshot(timeout: float = 10.0) -> str:
    """Request a screenshot from the Qt GUI and wait for its result."""
    with _bridge_lock:
        handler = _bridge_handler

    if handler is None:
        return None

    request = CaptureRequest()

    try:
        handler(request)
    except Exception as error:
        return f"{error}"

    if not request.completed.wait(timeout):
        return None

    if not request.success:
        return f"{request.error}"

    return "Clip!"


def capture_to_clipboard(return_image: bool = False) -> bytes | bool:
    """Capture the primary screen on the Qt GUI thread."""
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication is not running.")

    screen = QGuiApplication.primaryScreen()
    if screen is None:
        raise RuntimeError("No screen is available.")

    pixmap = screen.grabWindow(0)

    if pixmap.isNull():
        return False

    image = pixmap.toImage()
    if image.isNull():
        return False

    if return_image:
        buffer = QBuffer()

        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError("Couldn't open PNG buffer")

        if not image.save(buffer, "PNG"):
            raise RuntimeError("Couldn't decode the picture")

        return bytes(buffer.data())

    app.clipboard().setImage(image)
    return True