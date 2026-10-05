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
"""MPRIS media players through playerctl, and system audio capture through PulseAudio."""

from src.init.lang import tr
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..base import MediaReader, MediaSession
from . import services

MAX_COVER_BYTES = 8_000_000
SEPARATOR = "\x1f"
FORMAT = SEPARATOR.join("{{%s}}" % field for field in (
    "playerName", "status", "title", "artist", "album", "mpris:length", "position", "mpris:artUrl"))
COMMANDS = {"play": "play", "pause": "pause", "next": "next", "previous": "previous"}


def _playerctl(*arguments):
    executable = shutil.which("playerctl")
    if not executable:
        raise OSError("playerctl is not installed")
    result = subprocess.run([executable, *arguments], capture_output=True, text=True,
                            errors="replace", timeout=10, env=services.system_environment())
    if result.returncode:
        raise OSError((result.stderr or result.stdout).strip() or f"playerctl exited with {result.returncode}")
    return result.stdout


def _seconds(value):
    try:
        return max(0.0, int(value.strip()) / 1_000_000)
    except ValueError:
        return 0.0


def parse_players(output):
    players = []
    for line in output.splitlines():
        fields = line.split(SEPARATOR)
        if len(fields) < 8:
            continue
        name, state, title, artist, album, length, position, artwork = fields[:8]
        state = state.strip().casefold()
        if state not in {"playing", "paused"}:
            continue
        duration, position = _seconds(length), _seconds(position)
        players.append({"source": name.strip(), "state": state, "title": title, "artist": artist,
                        "album": album, "duration": duration,
                        "position": min(position, duration) if duration > 0 else position,
                        "artwork": artwork.strip()})
    return players


def read_players(accept=None):
    try:
        output = _playerctl("--all-players", "metadata", "--format", FORMAT)
    except OSError:
        return []
    return [player for player in parse_players(output) if accept is None or accept(player["source"])]


def current_player(players):
    return next((player for player in players if player["state"] == "playing"),
                players[0] if players else None)


class LinuxMediaReader(MediaReader):
    def sessions(self, accept=None):
        players = read_players(accept)
        current = current_player(players)
        return [MediaSession(source=player["source"], title=player["title"], artist=player["artist"],
                             album=player["album"], playing=player["state"] == "playing",
                             current=player is current, duration=player["duration"],
                             position=player["position"], seekable=True, handle=player["artwork"])
                for player in players]

    def cover(self, session):
        url = urlparse(session.handle or "")
        if url.scheme == "file":
            return Path(unquote(url.path)).read_bytes()[:MAX_COVER_BYTES]
        if url.scheme not in {"http", "https"}:
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
    _playerctl("--player", player["source"], COMMANDS[action])
    return json.dumps({"action": action, "accepted": True, "source": player["source"], "error": None})


def seek_media(seconds, source=""):
    try:
        player = _target(source)
    except LookupError:
        return tr('media.error_source_is_absent_or_matches_multiple_sessions_list_media_s')
    if player is None:
        return tr('media.error_no_active_media_session')
    _playerctl("--player", player["source"], "position", str(max(0, round(seconds))))
    return json.dumps({"action": "seek", "accepted": True, "source": player["source"]})


def record_output_audio(seconds, sample_rate):
    import soundcard as sc

    speaker = sc.default_speaker()
    if speaker is None:
        raise OSError(tr('brain.error_no_default_audio_output_device_was_found'))
    loopback = next((microphone for microphone in sc.all_microphones(include_loopback=True)
                     if getattr(microphone, "isloopback", False)
                     and (speaker.name.casefold() in microphone.name.casefold()
                          or microphone.name.casefold() in speaker.name.casefold())), None)
    if loopback is None:
        raise OSError(tr('brain.error_no_loopback_device_found_for', value0=speaker.name))
    try:
        with loopback.recorder(samplerate=sample_rate) as recorder:
            return recorder.record(numframes=sample_rate * seconds)
    except Exception as error:
        raise OSError(tr('brain.error_capturing_system_audio', error=error)) from error
