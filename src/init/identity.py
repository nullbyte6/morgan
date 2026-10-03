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
"""Access the application's identity without importing its entry point."""

from src.init.lang import tr
from collections.abc import Callable
from typing import Protocol

class AssistantIdentity(Protocol):
    name: str


_assistant_factory: Callable[[], AssistantIdentity] | None = None

def register_assistant(factory: Callable[[], AssistantIdentity]) -> None:
    """Register the singleton factory without initializing its runtime."""
    global _assistant_factory
    _assistant_factory = factory


def get_assistant() -> AssistantIdentity:
    """Return the registered singleton; the application owns its name and state."""
    if _assistant_factory is None:
        raise RuntimeError(tr('identity.the_application_has_not_registered_its_assistant'))
    return _assistant_factory()


def get_assistant_name(config: dict | None = None) -> str:
    """Resolve the assistant display name from the existing configuration."""
    if config is None:
        from .config import load_config
        config = load_config()
    return config["assistant"]["name"]


GENDER_INSTRUCTIONS = {
    "auto": "Infer your gender from your name: if your name is a male name you are male and must use masculine forms about yourself (he/him, and masculine adjectives, participles and articles in gendered languages, such as \"listo\" in Spanish); if it is a female name you are female and must use feminine forms (she/her, \"lista\"). Never default to feminine forms. If the name is neutral or ambiguous, avoid gendered self-reference.",
    "male": "You are male: always use masculine forms about yourself (he/him, and masculine adjectives, participles and articles in gendered languages, such as \"listo\" in Spanish), whatever your name suggests.",
    "female": "You are female: always use feminine forms about yourself (she/her, and feminine adjectives, participles and articles in gendered languages, such as \"lista\" in Spanish), whatever your name suggests.",
    "neutral": "You have no gender: avoid gendered self-reference, using neutral wording and, in gendered languages, phrasing that needs no masculine or feminine form about yourself.",
}


def get_assistant_gender_instruction(config: dict | None = None) -> str:
    """Return the first-person gender guidance for the configured gender."""
    if config is None:
        from .config import load_config
        config = load_config()
    return GENDER_INSTRUCTIONS[config["assistant"].get("gender", "auto")]


def get_assistant_identifier() -> str:
    """Return the name namespace shared by the running storage and services."""
    from .config import HOME_PATH
    return HOME_PATH.name.removeprefix(".")


def get_assistant_installation(config: dict | None = None):
    """Return the installed application directory named by the <NAME> variable."""
    import os
    from pathlib import Path
    value = os.environ.get(get_assistant_name(config).upper(), "").strip()
    return Path(value) if value else None


def get_assistant_environment(key: str, default=None):
    """Read generic environment options while accepting legacy launcher options."""
    import os
    from .config import DEFAULTS
    legacy_prefix = DEFAULTS["assistant"]["name"].upper()
    return os.environ.get("ASSISTANT_" + key, os.environ.get(legacy_prefix + "_" + key, default))
