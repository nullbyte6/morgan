"""Integration check: real Chromium cookies/local storage survive a process restart.

Run: python scripts/test_browser_session.py
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def child(mode, data_path, origin):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWidgets import QApplication
    from src.init.visuals.browser_session import BrowserSession
    app = QApplication([])
    session = BrowserSession(app, data_path=data_path)
    assert not session.profile.isOffTheRecord()
    page = session.create_page(session)
    second = session.create_page(session)
    assert page.profile() is second.profile()
    outcome = []

    def loaded(ok):
        assert ok, 'Local test page did not load'
        script = "JSON.stringify({cookies: document.cookie, stored: localStorage.getItem('arlo_test')})"
        page.runJavaScript(script, lambda value: (outcome.append(json.loads(value)), QTimer.singleShot(500, app.quit)))

    page.loadFinished.connect(loaded)
    page.setUrl(QUrl(origin + '/' + mode))
    QTimer.singleShot(15000, app.quit)
    app.exec()
    session.shutdown()
    assert outcome, 'Chromium did not respond'
    assert 'arlo_session=retained' in outcome[0]['cookies'], outcome
    assert 'arlo_persistent=retained' in outcome[0]['cookies'], outcome
    assert outcome[0]['stored'] == 'retained', outcome
    print('PASS:', mode, 'shared profile, session cookies, persistent cookies, local storage')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        html = '<html><body>Arlo session test</body></html>'
        if self.path == '/write':
            html += "<script>document.cookie='arlo_session=retained; Path=/';document.cookie='arlo_persistent=retained; Max-Age=3600; Path=/';localStorage.setItem('arlo_test','retained');</script>"
        self.wfile.write(html.encode())

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    if len(sys.argv) > 1:
        child(*sys.argv[1:])
    else:
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory(prefix='arlo-browser-test-') as data:
                for mode in ('write', 'read'):
                    subprocess.run([sys.executable, __file__, mode, data,
                                    f'http://127.0.0.1:{server.server_port}'], check=True, timeout=25)
        finally:
            server.shutdown()
