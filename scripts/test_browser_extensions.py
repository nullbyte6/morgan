"""Real Qt WebEngine extension installation, execution and restart checks.

Run: python scripts/test_browser_extensions.py
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def child(mode, data_path, fixture, origin):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication
    from src.init.visuals.browser_session import BrowserSession
    app = QApplication([])
    session = BrowserSession(app, data_path=data_path)
    page = session.create_page(session)
    control = session.extensions
    manager = control.manager
    errors = []
    control.message.connect(errors.append)

    def wait(predicate):
        deadline = time.monotonic() + 12
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert predicate(), f'Timed out: {errors}'

    def installed():
        return [ext for ext in manager.extensions() if ext.isInstalled()]

    if mode == 'install':
        manager.installExtension(fixture)
        wait(lambda: len(installed()) == 1 and installed()[0].isEnabled())
    else:
        wait(lambda: len(installed()) == 1)
        if mode == 'restore':
            wait(lambda: installed()[0].isEnabled())
        else:
            assert not installed()[0].isEnabled(), 'Disabled state not restored'
    extension = installed()[0]
    loaded = []
    page.loadFinished.connect(loaded.append)
    page.setUrl(QUrl(origin))
    wait(lambda: loaded)
    assert loaded[-1]
    result = []
    page.runJavaScript("document.documentElement.dataset.arloExtension || 'disabled'", result.append)
    wait(lambda: result)
    assert result[0] == ('disabled' if mode == 'disabled' else 'working'), result
    if mode == 'install':
        assert not extension.actionPopupUrl().isEmpty()
        loaded.clear()
        page.setUrl(extension.actionPopupUrl())
        wait(lambda: loaded)
        assert loaded[-1]
        result.clear()
        page.runJavaScript('document.body.textContent.trim()', result.append)
        wait(lambda: result)
        assert result[0] == 'Arlo test popup'
    elif mode == 'restore':
        control.set_enabled(extension, False)
        assert not installed()[0].isEnabled()
    else:
        manager.uninstallExtension(extension)
        wait(lambda: not installed())
    session.shutdown()
    print('PASS:', mode, Path(fixture).name, 'extension state and content script')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<html><body>Extension integration test</body></html>')

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    if len(sys.argv) > 1:
        child(*sys.argv[1:])
    else:
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory(prefix='arlo-extensions-test-') as tmp:
                root = Path(tmp)
                fixture = root / 'fixture'
                fixture.mkdir()
                manifest = {'manifest_version': 3, 'name': 'Arlo integration test', 'version': '1.0',
                            'action': {'default_popup': 'popup.html'},
                            'content_scripts': [{'matches': ['http://127.0.0.1/*'], 'js': ['content.js'], 'run_at': 'document_end'}]}
                (fixture / 'manifest.json').write_text(json.dumps(manifest))
                (fixture / 'content.js').write_text("document.documentElement.dataset.arloExtension='working';")
                (fixture / 'popup.html').write_text('<html><body>Arlo test popup</body></html>')
                archive = root / 'fixture.zip'
                with zipfile.ZipFile(archive, 'w') as bundle:
                    for path in fixture.iterdir():
                        bundle.write(path, path.name)
                for source in (fixture, archive):
                    profile = root / ('profile-zip' if source == archive else 'profile-folder')
                    for mode in ('install', 'restore', 'disabled'):
                        subprocess.run([sys.executable, __file__, mode, str(profile), str(source),
                                        f'http://127.0.0.1:{server.server_port}'], check=True, timeout=30)
        finally:
            server.shutdown()
