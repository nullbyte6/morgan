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
"""Resolve Arlo's semantic color roles from a theme definition."""
from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtGui import QColor

THEMES_DIR = Path(__file__).resolve().parents[2] / "assets" / "themes"
DEFAULT_THEME_ID = "catppuccin-macchiato"
THEME_FORMAT_VERSION = 1

ROLES = frozenset((
    "text", "text_secondary", "text_muted", "text_subtle", "text_disabled",
    "surface", "surface_sunken", "surface_raised", "surface_selected",
    "border", "border_strong", "selection", "scrollbar", "scrollbar_hover",
    "accent", "accent_hover", "on_accent",
    "success", "warning", "error",
    "private_indicator", "git_branch", "file_tag",
    "toggle_track_off", "toggle_track_on", "toggle_thumb",
    "orb_idle", "orb_processing", "orb_reading", "orb_writing",
    "orb_executing", "orb_awaiting_permission", "orb_error", "orb_success",
    "audio_wave_layer_1", "audio_wave_layer_2", "audio_wave_layer_3",
    "audio_wave_layer_4",
    "flowchart_background", "flowchart_node", "flowchart_node_border",
    "flowchart_node_selected", "flowchart_text", "flowchart_edge",
    "editor_gutter", "editor_current_line", "line_number",
    "syntax_keyword", "syntax_builtin", "syntax_function", "syntax_class",
    "syntax_string", "syntax_number", "syntax_comment", "syntax_decorator",
    "code_inline_text", "code_inline_background",
    "code_block_text", "code_block_background", "code_block_border",
    "table_border", "table_header_text", "table_header_background",
    "table_row_alternate",
    "terminal_foreground", "terminal_background",
    "terminal_cursor", "terminal_cursor_text",
    "terminal_black", "terminal_red", "terminal_green", "terminal_yellow",
    "terminal_blue", "terminal_magenta", "terminal_cyan", "terminal_white",
    "terminal_bright_black", "terminal_bright_red", "terminal_bright_green",
    "terminal_bright_yellow", "terminal_bright_blue",
    "terminal_bright_magenta", "terminal_bright_cyan", "terminal_bright_white",
))

_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
_TOKEN = re.compile(r"@([a-z][a-z0-9_]*)(?:/(\d{1,3}))?")


class Theme:
    """An immutable set of semantic color roles."""

    def __init__(self, theme_id: str, name: str, version: int, colors: dict[str, str]):
        if version != THEME_FORMAT_VERSION:
            raise ValueError(f"Unsupported theme format version: {version}")
        if not theme_id or not name:
            raise ValueError("Theme requires an id and a name")
        missing = ROLES.difference(colors)
        unknown = set(colors).difference(ROLES)
        if missing or unknown:
            raise ValueError(
                f"Theme {theme_id!r} roles mismatch: "
                f"missing={sorted(missing)} unknown={sorted(unknown)}")
        for role, value in colors.items():
            if not isinstance(value, str) or not _HEX_COLOR.fullmatch(value):
                raise ValueError(f"Theme {theme_id!r} role {role!r} is not #rrggbb: {value!r}")
        self.id = theme_id
        self.name = name
        self.version = version
        self._colors = {role: value.lower() for role, value in colors.items()}
        self._qcolors = {role: QColor(value) for role, value in self._colors.items()}

    @classmethod
    def from_file(cls, path: Path) -> Theme:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data.get("id"), data.get("name"), data.get("version"), data.get("colors") or {})

    def hex(self, role: str) -> str:
        return self._colors[role]

    def color(self, role: str, alpha: int | None = None) -> QColor:
        color = QColor(self._qcolors[role])
        if alpha is not None:
            color.setAlpha(alpha)
        return color

    def css(self, role: str, alpha: int | None = None) -> str:
        if alpha is None:
            return self._colors[role]
        color = self._qcolors[role]
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {int(alpha)})"

    def render(self, template: str) -> str:
        """Replace @role and @role/alpha tokens (alpha 0-255) with CSS colors."""
        return _TOKEN.sub(
            lambda match: self.css(
                match.group(1),
                None if match.group(2) is None else min(255, int(match.group(2)))),
            template)


def load_builtin_theme(theme_id: str = DEFAULT_THEME_ID) -> Theme:
    return Theme.from_file(THEMES_DIR / f"{theme_id}.json")


_current: Theme | None = None


def current_theme() -> Theme:
    """Return the active theme; consumers should resolve colors through it."""
    global _current
    if _current is None:
        _current = load_builtin_theme()
    return _current
