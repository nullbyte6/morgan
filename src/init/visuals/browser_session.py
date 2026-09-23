"""Shared, persistent Chromium session for all Arlo browser panels."""

from pathlib import Path
from weakref import WeakSet

from PySide6.QtCore import QObject, QThread
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWidgets import QApplication
from shiboken6 import delete, isValid


class BrowserSession(QObject):
    """Own the profile until every page has been destroyed and data flushed."""

    def __init__(self, parent, *, data_path=None):
        super().__init__(parent)
        self.data_path = Path(data_path or Path.home() / '.arlo' / 'browser')
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.profile = QWebEngineProfile('arlo-browser', self)
        self.profile.setPersistentStoragePath(str(self.data_path / 'storage'))
        self.profile.setCachePath(str(self.data_path / 'cache'))
        self.profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        self._pages = WeakSet()
        self._closed = False
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
    session = getattr(app, '_arlo_browser_session', None)
    if session is None:
        session = BrowserSession(app)
        app._arlo_browser_session = session
    return session
