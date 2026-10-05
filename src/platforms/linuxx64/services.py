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
"""Service startup on Linux through the bash services script, and child processes outside a frozen bundle."""

from contextlib import contextmanager
import os
from pathlib import Path
import sys

LIBRARY_VARIABLES = ("LD_LIBRARY_PATH", "LD_PRELOAD")


def service_launchers(name):
    return list(dict.fromkeys((f"{name}-services.sh", "morgan-services.sh")))


def service_command(script, voice):
    return ["/bin/bash", str(script), "--no-console", *(() if voice else ("--no-voice",))]


def system_environment():
    """The environment for system tools: a frozen bundle must not leak its own libraries into them."""
    environment = dict(os.environ)
    if getattr(sys, "frozen", False):
        for name in LIBRARY_VARIABLES:
            original = environment.pop(f"{name}_ORIG", None)
            if original is None:
                environment.pop(name, None)
            else:
                environment[name] = original
    return environment


@contextmanager
def unbundled_libraries(bundle):
    saved = {name: os.environ.get(name) for name in LIBRARY_VARIABLES}
    restored = system_environment()
    for name in LIBRARY_VARIABLES:
        if name in restored:
            os.environ[name] = restored[name]
        else:
            os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def installed_executable():
    for candidate in (Path.home() / ".local" / "opt" / "Morgan" / "Morgan", Path("/opt/Morgan/Morgan")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None
