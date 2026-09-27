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
"""Shared, persistent Chromium session for all Arlo browser panels."""

from src.init.identity import get_assistant_name
from pathlib import Path
from ..config import HOME_PATH
from ..identity import get_assistant_identifier
from weakref import WeakSet

from PySide6.QtCore import QObject, QThread
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile,
                                     QWebEngineSettings)
from PySide6.QtWidgets import QApplication
from shiboken6 import delete, isValid


# noinspection PyUnusedImports
class BrowserSession(QObject):
    """Own the profile until every page has been destroyed and data flushed."""

    def __init__(self, parent, *, data_path=None):
        super().__init__(parent)
        self.data_path = Path(data_path or HOME_PATH / 'browser')
        self.data_path.mkdir(parents=True, exist_ok=True)
        try:
            from PySide6.QtWebEngineCore import QWebEngineProfileBuilder
        except ImportError:
            builder = None
            settings = QWebEngineProfile(f'{get_assistant_identifier()}-browser', self)
        else:
            builder = QWebEngineProfileBuilder()
            settings = builder
        settings.setPersistentStoragePath(str(self.data_path / 'storage'))
        settings.setCachePath(str(self.data_path / 'cache'))
        settings.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
        settings.setHttpCacheMaximumSize(512 * 1024 * 1024)
        settings.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        self.profile = builder.createProfile(f'{get_assistant_identifier()}-browser', self) if builder else settings

        web_settings = self.profile.settings()
        web_settings.setAttribute(QWebEngineSettings.DnsPrefetchEnabled, True)
        web_settings.setAttribute(QWebEngineSettings.BackForwardCacheEnabled, True)
        web_settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
        web_settings.setAttribute(QWebEngineSettings.WebGLEnabled, True)

        from PySide6.QtWebEngineCore import qWebEngineChromiumVersion
        chromium_major = qWebEngineChromiumVersion().split(".")[0]
        self.profile.setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chromium_major}.0.0.0 Safari/537.36"
        )

        if self.profile is None:
            raise RuntimeError(f'The {get_assistant_name()} browser profile is already in use')
        self._pages = WeakSet()
        self._closed = False
        from .browser_extensions import BrowserExtensions
        self.extensions = (BrowserExtensions(self)
                           if hasattr(self.profile, 'extensionManager') else None)
        parent.aboutToQuit.connect(self.shutdown)

    def create_page(self, parent):
        if self._closed:
            raise RuntimeError('The browser session is closed')
        page = QWebEnginePage(self.profile, parent)
        self._pages.add(page)
        return page

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        if self.extensions is not None:
            self.extensions.shutdown()
        for page in tuple(self._pages):
            if isValid(page):
                delete(page)
        self._pages.clear()
        # Destroy the disk profile while Qt's event dispatcher still exists.
        delete(self.profile)


def get_browser_session():
    """Return one application-owned session, never an off-the-record profile."""
    app = QApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        raise RuntimeError('Browser sessions require the QApplication GUI thread')
    session = getattr(app, '_assistant_browser_session', None)
    if session is None:
        session = BrowserSession(app)
        app._assistant_browser_session = session
    return session
