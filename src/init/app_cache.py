"""Persistent launch targets; keyed by the user's normalized application name."""
import json
import os
from pathlib import Path
import tempfile
import threading

from .config import HOME_PATH

APPS_FILE = HOME_PATH / "json" / "apps.json"
_lock = threading.RLock()


def _read():
    if not APPS_FILE.exists():
        return {}
    data = json.loads(APPS_FILE.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("apps.json must contain an object")
    return data


def cached_app(query):
    """Read fresh entries; invalid or unavailable cache files are optional."""
    with _lock:
        try:
            app = _read().get(query)
            if not isinstance(app, dict) or not isinstance(app.get("Name"), str):
                return None
            target_key = "AppID" if app.get("Source") == "registered" else "Path"
            target = app.get(target_key)
            if not isinstance(target, str) or not target.strip() or any(ord(c) < 32 for c in target):
                return None
            if target_key == "Path":
                path = Path(target)
                if not path.is_absolute() or not path.is_file():
                    forget_app(query)
                    return None
            return {"Name": app["Name"], "Source": "registered" if target_key == "AppID" else "file",
                    target_key: target}
        except (OSError, ValueError):
            return None


def _update(query, app):
    """Atomic replace; do not overwrite a malformed user-edited cache."""
    temporary = None
    with _lock:
        try:
            data = _read()
            if app is None:
                data.pop(query, None)
            else:
                data[query] = app
            APPS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=APPS_FILE.parent,
                                             delete=False) as file:
                temporary = Path(file.name)
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.write("\n")
            os.replace(temporary, APPS_FILE)
            return True
        except (OSError, ValueError):
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


def remember_app(query, app):
    return _update(query, {key: app[key] for key in ("Name", "Source", "Path", "AppID") if key in app})


def forget_app(query):
    return _update(query, None)
