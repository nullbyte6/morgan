"""Persistent launch targets; keyed by the user's normalized application name."""
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unicodedata

from .config import HOME_PATH

APPS_FILE = HOME_PATH / "json" / "apps.json"
_lock = threading.RLock()


def _normalize_name(value):
    name = Path(str(value).strip()).stem
    name = unicodedata.normalize("NFKD", name.casefold())
    name = "".join(character for character in name
                   if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", name))


def _normalized_target(app):
    """Return the cached launch target, accepting older cache shapes.
    Early versions wrote executable paths under ``AppID`` even when the
    source was ``file``.  Keep those entries usable and normalize them to the
    shape expected by the launcher instead of invalidating a valid cache.
    """
    source = app.get("Source")
    if source == "registered":
        app_id = app.get("AppID")
        if isinstance(app_id, str) and app_id.strip():
            if Path(app_id).is_file():
                return "file", app_id
            return "registered", app_id
        return None, None

    path = app.get("Path")
    if not isinstance(path, str) or not path.strip():
        path = app.get("AppID")
    if isinstance(path, str) and path.strip():
        return "file", path
    return None, None


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
            data = _read()
            app = data.get(query)
            if not isinstance(app, dict):
                for candidate in data.values():
                    if not isinstance(candidate, dict) or not isinstance(candidate.get("Name"), str):
                        continue
                    target_path = candidate.get("Path") or candidate.get("AppID")
                    aliases = (candidate["Name"],
                               Path(target_path).name if isinstance(target_path, str) else "")
                    if any(_normalize_name(alias) == query for alias in aliases):
                        app = candidate
                        break
            if not isinstance(app, dict) or not isinstance(app.get("Name"), str):
                return None
            source, target = _normalized_target(app)
            if not isinstance(target, str) or not target.strip() or any(ord(c) < 32 for c in target):
                return None
            if source == "file":
                path = Path(target)
                if not path.is_absolute() or not path.is_file():
                    return None
                return {"Name": app["Name"], "Source": "file", "Path": target}
            return {"Name": app["Name"], "Source": "registered", "AppID": target}
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
