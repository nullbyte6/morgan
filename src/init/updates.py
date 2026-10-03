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
"""Updates from the repository's GitHub releases: list, download and install the platform installer."""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.platforms import current_platform

REPOSITORY = "xddigs/morgan"
RELEASES_URL = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
CHUNK_SIZE = 256 * 1024


class UpdateCancelled(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    title: str
    url: str
    size: int
    published: str
    prerelease: bool


def version_key(version: str) -> tuple:
    """Order versions by their numbers, a final release after the prereleases of the same numbers."""
    text = version.strip().lstrip("vV")
    numbers, _separator, suffix = text.partition("-")
    return tuple(int(part) for part in re.findall(r"\d+", numbers)), not suffix, suffix


def _request(url: str, accept: str) -> urllib.request.Request:
    from src.init.brain import get_version
    return urllib.request.Request(url, headers={
        "Accept": accept, "User-Agent": f"Arlo/{get_version()}", "X-GitHub-Api-Version": "2022-11-28"})


def available_releases(current: str | None = None) -> list[Release]:
    """The published releases newer than the running version that ship this platform's installer, newest first."""
    from src.init.brain import get_version
    current = current or get_version()
    with urllib.request.urlopen(_request(RELEASES_URL, "application/vnd.github+json"), timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    setup_name = current_platform().installer_name
    releases = []
    for item in payload:
        if item.get("draft"):
            continue
        asset = next((asset for asset in item.get("assets", ())
                      if setup_name and asset.get("name", "").casefold() == setup_name.casefold()), None)
        version = (item.get("tag_name") or "").strip()
        if asset is None or not version or version_key(version) <= version_key(current):
            continue
        releases.append(Release(
            version=version.lstrip("vV"), title=(item.get("name") or "").strip(),
            url=asset["browser_download_url"], size=int(asset.get("size") or 0),
            published=(item.get("published_at") or "")[:10], prerelease=bool(item.get("prerelease"))))
    releases.sort(key=lambda release: version_key(release.version), reverse=True)
    return releases


def setup_path() -> Path:
    platform = current_platform()
    return platform.known_folder("downloads") / platform.installer_name


def download(release: Release, progress: Callable[[int, int], None],
             cancel: threading.Event | None = None) -> Path:
    """Save the release's installer to the Downloads folder, reporting bytes received and the total."""
    target = setup_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(_request(release.url, "application/octet-stream"), timeout=30) as response, \
                partial.open("wb") as output:
            total = int(response.headers.get("Content-Length") or release.size or 0)
            received = 0
            progress(received, total)
            while chunk := response.read(CHUNK_SIZE):
                if cancel is not None and cancel.is_set():
                    raise UpdateCancelled()
                output.write(chunk)
                received += len(chunk)
                progress(received, total)
        if total and received != total:
            raise OSError(f"The download stopped at {received} of {total} bytes.")
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return target


def relaunch_command(terminal: bool = False) -> tuple[list[str], Path]:
    """The command and folder that start Arlo again once the installer has finished."""
    if getattr(sys, "frozen", False):
        return [sys.executable], Path(sys.executable).parent
    installed = current_platform().installed_executable(terminal)
    if installed is not None and installed.is_file():
        return [str(installed)], installed.parent
    return [sys.executable, str(Path(sys.argv[0]).resolve()), *sys.argv[1:]], Path.cwd()


def _environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(("_PYI_", "_MEI"))}
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        root = Path(bundle).resolve()
        environment["PATH"] = os.pathsep.join(
            entry for entry in environment.get("PATH", "").split(os.pathsep)
            if entry and not Path(os.path.expandvars(entry)).resolve().is_relative_to(root))
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    environment.pop("PYTHONHOME", None)
    return environment


def install(setup: Path, command: list[str], directory: Path) -> None:
    """Once this process exits, run the installer, delete it from Downloads and start Arlo again."""
    current_platform().run_installer_after_exit(setup, command, directory, _environment())
