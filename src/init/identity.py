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
