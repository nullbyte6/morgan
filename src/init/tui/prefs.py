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
"""Interface preferences of the terminal version, kept next to config.json."""
import json
import logging
import os
import tempfile
from pathlib import Path

DEFAULTS = {"muted": False, "subtitles": True, "ephemeral_steps": True}


class Preferences:
    def __init__(self, path: Path | None = None):
        if path is None:
            from src.init.config import HOME_PATH
            path = HOME_PATH / "json" / "tui.json"
        self.path = path
        self.values = dict(DEFAULTS)
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            stored = {}
        if isinstance(stored, dict):
            self.values.update({key: stored[key] for key in DEFAULTS
                                if isinstance(stored.get(key), bool)})

    def __getitem__(self, key: str) -> bool:
        return self.values[key]

    def __setitem__(self, key: str, value: bool) -> None:
        if key not in DEFAULTS or self.values[key] == bool(value):
            return
        self.values[key] = bool(value)
        self._save()

    def _save(self) -> None:
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as file:
                temporary = Path(file.name)
                json.dump(self.values, file, indent=2)
                file.write("\n")
            os.replace(temporary, self.path)
        except OSError:
            logging.getLogger("assistant.tui").exception("Unable to save preferences")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
