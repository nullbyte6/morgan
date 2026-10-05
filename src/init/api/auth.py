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
"""Device tokens and one-time pairing codes for the phone API."""
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
import uuid
from pathlib import Path

from src.init.config import HOME_PATH

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_LIFETIME = 300
MAX_CODE_ATTEMPTS = 5
LAST_SEEN_INTERVAL = 60


def api_directory() -> Path:
    path = HOME_PATH / "api"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write(path: Path, data: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False) as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _public(device: dict) -> dict:
    return {key: device.get(key) for key in ("id", "name", "created_at", "last_seen")}


class DeviceStore:
    """Paired devices; only a SHA-256 digest of each token is ever stored."""

    def __init__(self, directory: Path | None = None):
        self.path = (directory or api_directory()) / "devices.json"
        self._lock = threading.Lock()
        self._stamp = None
        self._devices = []
        self._flushed = {}

    def _load(self):
        try:
            stamp = self.path.stat().st_mtime_ns
        except OSError:
            stamp = None
        if stamp != self._stamp:
            devices = _read(self.path).get("devices", [])
            self._devices = [device for device in devices if isinstance(device, dict)
                             and isinstance(device.get("token_hash"), str)]
            self._stamp = stamp

    def _save(self):
        _write(self.path, {"devices": self._devices})
        self._stamp = self.path.stat().st_mtime_ns

    def list(self) -> list[dict]:
        with self._lock:
            self._load()
            return [_public(device) for device in self._devices]

    def add(self, name: str) -> tuple[str, str]:
        name = " ".join(str(name).split())[:60] or "Phone"
        token = secrets.token_urlsafe(32)
        device = {"id": uuid.uuid4().hex[:12], "name": name, "token_hash": _digest(token),
                  "created_at": int(time.time()), "last_seen": None}
        with self._lock:
            self._load()
            self._devices.append(device)
            self._save()
        return device["id"], token

    def verify(self, token: str) -> dict | None:
        if not token:
            return None
        digest = _digest(token)
        with self._lock:
            self._load()
            for device in self._devices:
                if hmac.compare_digest(device["token_hash"], digest):
                    now = int(time.time())
                    if now - self._flushed.get(device["id"], 0) >= LAST_SEEN_INTERVAL:
                        device["last_seen"] = now
                        self._flushed[device["id"]] = now
                        self._save()
                    return _public(device)
        return None

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            self._load()
            kept = [device for device in self._devices if device.get("id") != device_id]
            if len(kept) == len(self._devices):
                return False
            self._devices = kept
            self._save()
            return True


class PairingCodes:
    """A single short-lived code, created on the PC and redeemed once by a phone."""

    def __init__(self, directory: Path | None = None):
        self.path = (directory or api_directory()) / "pairing.json"
        self._lock = threading.Lock()

    @staticmethod
    def _normalize(code: str) -> str:
        return "".join(character for character in str(code).upper()
                       if character in CODE_ALPHABET)

    def create(self) -> tuple[str, int]:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        expires = int(time.time()) + CODE_LIFETIME
        with self._lock:
            _write(self.path, {"hash": _digest(code), "expires": expires, "failures": 0})
        return code, expires

    def redeem(self, code: str) -> bool:
        code = self._normalize(code)
        with self._lock:
            pending = _read(self.path)
            if not pending or pending.get("expires", 0) < time.time():
                self.path.unlink(missing_ok=True)
                return False
            if code and hmac.compare_digest(str(pending.get("hash", "")), _digest(code)):
                self.path.unlink(missing_ok=True)
                return True
            failures = int(pending.get("failures", 0)) + 1
            if failures >= MAX_CODE_ATTEMPTS:
                self.path.unlink(missing_ok=True)
            else:
                _write(self.path, {**pending, "failures": failures})
            return False
