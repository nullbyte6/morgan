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
"""Minimal bootstrap instructions; configurable behavior belongs in config.json."""

from src.init.lang import tr
from .identity import get_assistant_name


def current_instructions() -> str:
    """Build the live prompt from the latest valid user configuration."""
    from .config import load_config

    config = load_config()
    name = get_assistant_name(config)
    personality = config["personality"]
    instructions = config["instructions"]
    sections = "\n".join(
        f"{key}: {value.replace('{assistant_name}', name) if key == 'identity' else value}"
        for key, value in instructions.items() if value)
    style = "\n".join(
        f"{key}: {value}" for key, value in personality.items() if value)
    return (
            tr('rules.you_are_a_personal_desktop_assistant_follow_the_current_configur',
               assistant_name=name)
            + tr('rules.current_instructions_apply_to_this_response') + sections
            + tr('rules.current_personality_apply_to_this_response') + style)
