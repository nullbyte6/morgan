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
"""Browses the local Steam library and checks whether the installed games
match the game requested by the user, managed by a Steam account"""

import re
from difflib import get_close_matches
from pathlib import Path

from src.platforms import current_platform

class SteamManager:
    """Represents a steam game manager. Holds the entire registry of
    local games."""

    def __init__(self):
        self.steam_path = current_platform().steam_path()

    def _library_paths(self) -> list[Path]:
        """Returns a list of paths to local Steam libraries"""
        if self.steam_path is None:
            return []
        paths = [self.steam_path]
        vdf = self.steam_path / "steamapps" / "libraryfolders.vdf"

        if vdf.exists():
            content = vdf.read_text(encoding="utf-8", errors="ignore")

            for path in re.findall(r'"path"\s+"([^"]+)"', content):
                library = Path(path.replace("\\\\", "\\"))
                if library not in paths:
                    paths.append(library)

        return paths

    def games(self) -> list[dict]:
        """Returns a list of all games available in the steam library"""
        games = []

        for library in self._library_paths():
            steamapps = library / "steamapps"

            if not steamapps.exists():
                continue

            for manifest in steamapps.glob("appmanifest_*.acf"):
                content = manifest.read_text(
                    encoding="utf-8",
                    errors="ignore")

                appid = re.search(r'"appid"\s+"([^"]+)"', content)
                name = re.search(r'"name"\s+"([^"]+)"', content)
                installdir = re.search(
                    r'"installdir"\s+"([^"]+)"',
                    content)

                if not appid or not name:
                    continue

                games.append({
                    "appid": appid.group(1),
                    "name": name.group(1),
                    "install_dir": (
                        installdir.group(1)
                        if installdir else ""),
                    "library": str(library),
                })

        return games

    def find_game(self, name: str):
        """Finds the game with the given name"""
        games = self.games()
        query = name.strip().casefold()

        for game in games:
            if game["name"].casefold() == query:
                return game

        for game in games:
            if query in game["name"].casefold():
                return game

        names = {game["name"]: game for game in games}
        matches = get_close_matches(
            name,
            names,
            n=1,
            cutoff=0.7)

        return names[matches[0]] if matches else None

    def launch(self, name: str) -> bool:
        """Launches the game with the given name"""
        game = self.find_game(name)
        if game is None:
            return False

        current_platform().open_path(f"steam://rungameid/{game['appid']}")
        return True


steam_manager = SteamManager()
