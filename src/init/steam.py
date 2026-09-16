"""Browses the local Steam library and checks whether the installed games
match the game requested by the user, managed by a Steam account"""

from steam_client.utils import steam_from_registry


class SteamManager:
    """Represents a steam game manager. Holds the entire registry of
    local games."""
    def __init__(self):
        self.steam = steam_from_registry()

    def games(self):
        """Returns a list of all games available in the steam library"""
        return list(self.steam.library.games())

    def find_game(self, name: str):
        """Returns a game matching the given name"""
        return self.steam.library.game_by_name(name)

    def launch(self, name: str) -> bool:
        """Returns a boolean indicating if the game was launched"""
        game = self.find_game(name)
        if game is None:
            return False
        game.run()
        return True


steam_manager = SteamManager()