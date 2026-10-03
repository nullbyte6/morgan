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
"""Dark colors for the terminal, taken from the desktop's theme files without Qt."""
import json
import logging
import re
from pathlib import Path

THEMES_DIR = Path(__file__).resolve().parents[3] / "assets" / "themes"
DEFAULT_THEME_ID = "catppuccin-macchiato"
_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_log = logging.getLogger("assistant.tui")

ORB_ROLES = {
    "idle": "orb_idle",
    "processing": "orb_processing",
    "reading": "orb_reading",
    "writing": "orb_writing",
    "executing": "orb_executing",
    "awaiting_permission": "orb_awaiting_permission",
    "denied_error": "orb_error",
    "success": "orb_success",
}


def channels(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def luminance(color: str) -> float:
    red, green, blue = channels(color)
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255


def mix(front: str, back: str, ratio: float) -> str:
    """Blend front over back; ratio 1 is entirely front."""
    ratio = min(1.0, max(0.0, ratio))
    return "#{:02x}{:02x}{:02x}".format(*(
        round(b + (f - b) * ratio) for f, b in zip(channels(front), channels(back))))


def _read(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    colors = data.get("colors")
    if not isinstance(data.get("id"), str) or not isinstance(colors, dict):
        return None
    return data["id"], {role: value.lower() for role, value in colors.items()
                        if isinstance(value, str) and _HEX.fullmatch(value)}


def _themes():
    from src.init.config import HOME_PATH

    found = {}
    for directory in (THEMES_DIR, HOME_PATH / "themes"):
        try:
            paths = sorted(directory.glob("*.json"))
        except OSError:
            continue
        for path in paths:
            theme = _read(path)
            if theme is not None:
                found[theme[0]] = theme[1]
    return found


class Palette:
    """Semantic color roles; light themes are replaced by the default dark theme."""

    def __init__(self, colors: dict[str, str]):
        self.colors = colors

    def __getitem__(self, role: str) -> str:
        return self.colors[role]

    def state(self, orb_state: str) -> str:
        return self.colors[ORB_ROLES.get(orb_state, "orb_idle")]


def load_palette() -> Palette:
    themes = _themes()
    base = themes.get(DEFAULT_THEME_ID)
    if base is None:
        raise FileNotFoundError(f"Default theme not found in {THEMES_DIR}")
    try:
        from src.init.config import load_config
        selected = themes.get(load_config().get("theme"), base)
    except Exception:
        _log.exception("Unable to read the configured theme")
        selected = base
    colors = {**base, **selected}
    if luminance(colors["surface"]) > 0.5:
        colors = base
    return Palette(colors)
