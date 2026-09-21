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
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional, Callable
from pathlib import Path
from pywin32 import *

@dataclass
class ClipboardRequest:
    """One clipboard paste request and its completion state."""

    completed: threading.Event = field(default_factory=threading.Event)
    success: bool = False
    error: str = ""
    file_path: Optional[str] = None


_bridge_lock = threading.Lock()
_bridge_handler: Optional[Callable[[ClipboardRequest], None]] = None


def register_clipboard_handler(handler: Callable[[ClipboardRequest], None]):
    """Register the clipboard paste request handler."""
    global _bridge_handler
    with _bridge_lock:
        _bridge_handler = handler


def unregister_clipboard_handler(handler: Optional[Callable[[ClipboardRequest], None]] = None):
    """Remove a handler without affecting a newer desktop instance."""
    global _bridge_handler
    with _bridge_lock:
        if _bridge_handler == handler:
            _bridge_handler = None


def request_clipboard_paste(timeout: float = 10.0) -> Optional[str]:
    """Request clipboard paste and wait for its result.
    
    Returns the file path if a valid file was pasted, None otherwise.
    """
    global _bridge_handler

    with _bridge_lock:
        handler = _bridge_handler

    if handler is None:
        return None

    request = ClipboardRequest()

    try:
        handler(request)
    except Exception as error:
        return f"{error}"

    if not request.completed.wait(timeout):
        return None

    if not request.success:
        return f"{request.error}"

    return request.file_path


def handle_clipboard_paste() -> Optional[str]:
    """Handle clipboard paste and return file path if valid content was pasted.
    
    This function checks the clipboard for:
    - Text content (returns as string)
    - Image data (converts to PNG and returns path)
    - File paths (returns the path directly)
    
    Returns None if clipboard is empty or contains invalid content.
    """
    import win32clipboard
    from PIL import Image
    import io
    
    try:
        cf_hdrop = win32clipboard.GetClipboardData(win32.CF_HDROP)
        if cf_hdrop:
            files = cf_hdrop.get_filenames()
            if files:
                return files[0]
        
        image_formats = [win32.CF_DIB, win32.CF_TIFF, win32.CF_BITMAP]
        for fmt in image_formats:
            try:
                data = win32clipboard.GetClipboardData(fmt)
                # Convert to PIL Image and save as PNG
                image = Image.open(io.BytesIO(data))
                temp_path = Path(f"clipboard_image_{int(win32clipboard.GetClipboardData(win32.CF_HDROP))}.png") \
                    if "HDROP" in str(data) else Path("clipboard_image.png")
                image.save(temp_path, "PNG")
                return str(temp_path)
            except Exception:
                continue
        
        try:
            text = win32clipboard.GetClipboardData(win32.CF_TEXT)
            if text.strip():
                # Save text to a file
                temp_path = Path("clipboard_text.txt")
                with open(temp_path, "w", encoding="utf-8") as f:
                    f.write(text)
                return str(temp_path)
        except Exception:
            pass
        
        return None
        
    except Exception as e:
        return f"Error accessing clipboard: {str(e)}"


def is_valid_clipboard_content() -> bool:
    """Check if clipboard contains valid content."""
    try:
        win32clipboard.OpenClipboard()
        formats = win32clipboard.EnumClipboardFormats()
        win32clipboard.CloseClipboard()
        return len(formats) > 0
    except Exception:
        return False
