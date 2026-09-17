"""Browses the local Steam library and checks whether the installed games
match the game requested by the user, managed by a Steam account"""

import winreg


class SteamManager:
    """Represents a steam game manager. Holds the entire registry of
    local games."""

    def __init__(self):
        self.steam_path = self._find_steam_path()

    @staticmethod
    def _find_steam_path() -> Path:
        """Finds the local Steam installation path"""
        keys = (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")
        )

        for root, key_path in keys:
            try:
                with winreg.OpenKey(root, key_path) as key:
                    value, _ = winreg.QueryValueEx(key, "SteamPath")
                    return Path(value)
            except OSError:
                continue

        raise FileNotFoundError("Steam installation not found")

    def _library_paths(self) -> list[Path]:
        """Returns a list of paths to local Steam libraries"""
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

        os.startfile(f"steam://rungameid/{game['appid']}")
        return True


steam_manager = SteamManager()
