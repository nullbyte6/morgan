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
import logging
import re
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

THEMES_DIR = Path(__file__).resolve().parents[2] / "assets" / "themes"
DEFAULT_THEME_ID = "catppuccin-macchiato"
THEME_FORMAT_VERSION = 1
SEED_MANIFEST = ".builtin-themes"

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
_THEME_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_log = logging.getLogger("assistant.theme")
_TOKEN = re.compile(r"@([a-z][a-z0-9_]*)(?:/(\d{1,3})(?:~([a-z][a-z0-9_]*))?)?")


class Theme:
    """An immutable set of semantic color roles."""

    def __init__(self, theme_id: str, name: str, version: int, colors: dict[str, str],
                 path: Path | None = None):
        if isinstance(version, bool) or version != THEME_FORMAT_VERSION:
            raise ValueError(f"Unsupported theme format version: {version!r}")
        if not isinstance(theme_id, str) or not _THEME_ID.fullmatch(theme_id):
            raise ValueError(f"Invalid theme id: {theme_id!r}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Theme {theme_id!r} requires a display name")
        if not isinstance(colors, dict):
            raise ValueError(f"Theme {theme_id!r} colors must be an object")
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
        self.name = name.strip()
        self.version = version
        self.path = path
        self._colors = {role: value.lower() for role, value in colors.items()}
        self._qcolors = {role: QColor(value) for role, value in self._colors.items()}

    @classmethod
    def from_file(cls, path: Path) -> Theme:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: theme file must contain a JSON object")
        return cls(data.get("id"), data.get("name"), data.get("version"), data.get("colors"), Path(path))

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

    def blend(self, role: str, alpha: int, base: str) -> str:
        """Return role at alpha pre-composited over base as an opaque color."""
        color, under = self._qcolors[role], self._qcolors[base]
        ratio = min(255, int(alpha)) / 255
        return "#{:02x}{:02x}{:02x}".format(*(
            round(back + (front - back) * ratio) for front, back in (
                (color.red(), under.red()), (color.green(), under.green()), (color.blue(), under.blue()))))

    def render(self, template: str) -> str:
        """Replace @role, @role/alpha and @role/alpha~base tokens (alpha 0-255) with CSS colors."""
        return _TOKEN.sub(
            lambda match: self.blend(match.group(1), int(match.group(2)), match.group(3))
            if match.group(3) else self.css(
                match.group(1),
                None if match.group(2) is None else min(255, int(match.group(2)))),
            template)


class ThemeNotifier(QObject):
    """Broadcast the new theme after the current theme is replaced."""
    theme_changed = Signal(object)


def load_builtin_theme(theme_id: str = DEFAULT_THEME_ID) -> Theme:
    return Theme.from_file(THEMES_DIR / f"{theme_id}.json")


def user_themes_dir() -> Path:
    from .config import HOME_PATH
    return HOME_PATH / "themes"


def seed_user_themes() -> Path:
    """Copy built-in themes the user folder has not received yet, never overwriting or restoring deleted ones."""
    directory = user_themes_dir()
    manifest = directory / SEED_MANIFEST
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if manifest.is_file():
            seeded = set(manifest.read_text(encoding="utf-8").split())
        else:
            seeded = {path.name for path in directory.glob("*.json")}
        pending = [source for source in sorted(THEMES_DIR.glob("*.json")) if source.name not in seeded]
        for source in pending:
            target = directory / source.name
            if not target.exists():
                shutil.copyfile(source, target)
            seeded.add(source.name)
        if pending or not manifest.is_file():
            manifest.write_text("\n".join(sorted(seeded)) + "\n", encoding="utf-8")
    except OSError as error:
        _log.warning("Unable to seed themes in %s: %s", directory, error)
    return directory


def discover_themes() -> list[Theme]:
    """Return valid themes by display name; invalid or duplicate files are skipped."""
    themes: dict[str, Theme] = {}
    directory = seed_user_themes()
    try:
        paths = sorted((path for path in directory.glob("*.json") if path.is_file()),
                       key=lambda path: path.name.casefold())
    except OSError as error:
        _log.warning("Unable to list themes in %s: %s", directory, error)
        paths = []
    for path in paths:
        try:
            theme = Theme.from_file(path)
        except (OSError, UnicodeError, ValueError) as error:
            _log.warning("Ignoring theme %s: %s", path, error)
            continue
        if theme.id in themes:
            _log.warning("Ignoring theme %s: duplicate id %r already defined by %s",
                         path, theme.id, themes[theme.id].path)
            continue
        themes[theme.id] = theme
    if DEFAULT_THEME_ID not in themes:
        themes[DEFAULT_THEME_ID] = load_builtin_theme()
    return sorted(themes.values(), key=lambda theme: (theme.name.casefold(), theme.id))


def resolve_theme(theme_id: str | None) -> Theme:
    """Find an installed theme, falling back to the default when unavailable."""
    try:
        for theme in discover_themes():
            if theme.id == theme_id:
                return theme
    except Exception:
        _log.exception("Theme discovery failed")
    if theme_id != DEFAULT_THEME_ID:
        _log.warning("Theme %r is unavailable; using %r", theme_id, DEFAULT_THEME_ID)
    return load_builtin_theme()


def configured_theme_id() -> str:
    try:
        from .config import load_config
        theme_id = load_config().get("theme")
    except Exception:
        _log.exception("Unable to read the configured theme")
        return DEFAULT_THEME_ID
    return theme_id if isinstance(theme_id, str) else DEFAULT_THEME_ID


_current: Theme | None = None
_notifier: ThemeNotifier | None = None


def theme_notifier() -> ThemeNotifier:
    global _notifier
    if _notifier is None:
        _notifier = ThemeNotifier()
    return _notifier


def on_theme_changed(slot) -> None:
    """Call slot(theme) whenever the current theme is replaced."""
    theme_notifier().theme_changed.connect(slot)


def current_theme() -> Theme:
    """Return the active theme; consumers should resolve colors through it."""
    global _current
    if _current is None:
        _current = resolve_theme(configured_theme_id())
    return _current


def set_current_theme(theme: Theme) -> None:
    """Replace the active theme and notify every subscribed consumer."""
    global _current
    _current = theme
    theme_notifier().theme_changed.emit(theme)


def select_theme(theme_id: str) -> Theme:
    """Persist a user theme choice by id and apply it immediately."""
    theme = resolve_theme(theme_id)
    try:
        from .config import load_config, save_config
        config = load_config()
        if config.get("theme") != theme.id:
            config["theme"] = theme.id
            save_config(config)
    except (OSError, ValueError):
        _log.exception("Unable to persist the selected theme")
    set_current_theme(theme)
    return theme
