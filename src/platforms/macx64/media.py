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
"""Spotify and Music playback through their AppleScript dictionaries."""

from src.init.lang import tr
import json
import subprocess
import urllib.request

import psutil

from ..base import MediaReader, MediaSession

MAX_COVER_BYTES = 8_000_000
SEPARATOR = "\x1f"

READ = """tell application "{application}"
    try
        if player state is stopped then return ""
        set t to current track
        set separator to character id 31
        return (player state as text) & separator & (name of t) & separator & (artist of t) & separator ¬
            & (album of t) & separator & ({duration} as text) & separator & (player position as text) ¬
            & separator & {artwork}
    on error
        return ""
    end try
end tell"""

PLAYERS = (
    ("com.spotify.client", "Spotify", READ.format(
        application="Spotify", duration="(duration of t) / 1000", artwork="(artwork url of t)")),
    ("com.apple.Music", "Music", READ.format(
        application="Music", duration="(duration of t)", artwork='""')),
)
APPLICATIONS = {source: application for source, application, _script in PLAYERS}
COMMANDS = {"play": "play", "pause": "pause", "next": "next track", "previous": "previous track"}

SEEK = """on run argv
    tell application "{application}" to set player position to ((item 1 of argv) as integer)
end run"""


def _number(value):
    try:
        return max(0.0, float(value.strip().replace(",", ".")))
    except ValueError:
        return 0.0


def parse_player(source, output):
    fields = output.rstrip("\r\n").split(SEPARATOR)
    if len(fields) < 7:
        return None
    state, title, artist, album, duration, position, artwork = fields[:7]
    duration, position = _number(duration), _number(position)
    return {"source": source, "state": state.strip().casefold(), "title": title, "artist": artist,
            "album": album, "duration": duration,
            "position": min(position, duration) if duration > 0 else position,
            "artwork": artwork.strip()}


def _running(application):
    return any(process.info["name"] == application for process in psutil.process_iter(["name"]))


def _osascript(script, *arguments):
    result = subprocess.run(["osascript", "-e", script, *arguments], capture_output=True,
                            text=True, errors="replace", timeout=10)
    if result.returncode:
        raise OSError((result.stderr or result.stdout).strip() or f"osascript exited with {result.returncode}")
    return result.stdout


def read_players(accept=None):
    players = []
    for source, application, script in PLAYERS:
        if (accept is not None and not accept(source)) or not _running(application):
            continue
        player = parse_player(source, _osascript(script))
        if player is not None:
            players.append(player)
    return players


def current_player(players):
    return next((player for player in players if player["state"] == "playing"),
                players[0] if players else None)


class MacMediaReader(MediaReader):
    def sessions(self, accept=None):
        players = read_players(accept)
        current = current_player(players)
        return [MediaSession(source=player["source"], title=player["title"], artist=player["artist"],
                             album=player["album"], playing=player["state"] == "playing",
                             current=player is current, duration=player["duration"],
                             position=player["position"], seekable=True, handle=player["artwork"])
                for player in players]

    def cover(self, session):
        if not session.handle.startswith("https://"):
            return b""
        request = urllib.request.Request(session.handle, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.read(MAX_COVER_BYTES)


def current_media():
    player = current_player(read_players())
    if player is None:
        return None
    return {"source": player["source"], "title": player["title"] or None,
            "artist": player["artist"] or None, "album_title": player["album"] or None,
            "album_artist": None, "track_number": None, "playback_status": player["state"],
            "position_seconds": player["position"], "duration_seconds": player["duration"]}


def media_sessions():
    return [{"source": player["source"], "title": player["title"] or None,
             "artist": player["artist"] or None, "album": player["album"] or None,
             "playback_status": player["state"]} for player in read_players()]


def _target(source):
    players = read_players()
    if source:
        matches = [player for player in players if player["source"] == source]
        if len(matches) != 1:
            raise LookupError
        return matches[0]
    return current_player(players)


def control_media(action, source=""):
    try:
        player = _target(source)
    except LookupError:
        return tr('media.error_source_is_absent_or_matches_multiple_sessions_list_media_s')
    if player is None:
        return None
    _osascript(f'tell application "{APPLICATIONS[player["source"]]}" to {COMMANDS[action]}')
    return json.dumps({"action": action, "accepted": True, "source": player["source"], "error": None})


def seek_media(seconds, source=""):
    try:
        player = _target(source)
    except LookupError:
        return tr('media.error_source_is_absent_or_matches_multiple_sessions_list_media_s')
    if player is None:
        return tr('media.error_no_active_media_session')
    _osascript(SEEK.format(application=APPLICATIONS[player["source"]]), str(round(seconds)))
    return json.dumps({"action": "seek", "accepted": True, "source": player["source"]})
