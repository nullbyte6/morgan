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
"""Translations for frequent redraws, reading the settings file once per second."""
import time

from src.init.lang import catalog, get_language
from src.init.identity import get_assistant_name

_state = {"at": -10.0, "language": "spanish", "name": "Arlo"}


def refresh() -> bool:
    """Reload language and assistant name; report whether either changed."""
    language, name = get_language(), get_assistant_name()
    changed = (language, name) != (_state["language"], _state["name"])
    _state.update(at=time.monotonic(), language=language, name=name)
    return changed


def language() -> str:
    return _state["language"]


def assistant_name() -> str:
    return _state["name"]


def t(key: str, /, **values) -> str:
    if time.monotonic() - _state["at"] > 1.0:
        refresh()
    template = catalog(_state["language"]).get(key)
    if template is None:
        template = catalog("english")[key]
    if "{assistant_name}" in template:
        values.setdefault("assistant_name", _state["name"])
    return template.format(**values) if values else template
