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
"""Find the song that is playing: Windows media sessions first, the Spotify Web API when it is authorized."""
import asyncio
import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from src.init import media

log = logging.getLogger("assistant.song")

BROWSERS = ("chrome", "msedge", "edge", "firefox", "brave", "opera", "vivaldi")
ADVERTISEMENT_TITLES = ("advertisement", "publicidad", "anuncio")
REMOTE_INTERVAL = 8.0
DETAIL_INTERVAL = 3.0
BACKOFF = 30.0
THUMBNAIL_ATTEMPTS = 6
MAX_COVER_BYTES = 8_000_000
SPOTIFY = "spotify"


@dataclass(frozen=True)
class Song:
    """A published song and where it is playing, measured at `stamp` on the monotonic clock."""

    source: str
    title: str
    artist: str
    album: str
    duration: float
    position: float
    playing: bool
    seekable: bool
    stamp: float
    cover: bytes = b""

    @property
    def key(self) -> str:
        return f"{self.title}\n{self.artist}".casefold()

    @property
    def remote(self) -> bool:
        return self.source == SPOTIFY

    def position_at(self, now: float) -> float:
        elapsed = now - self.stamp if self.playing else 0.0
        position = self.position + max(0.0, elapsed)
        return min(position, self.duration) if self.duration > 0 else position


def is_song_source(source: str) -> bool:
    source = source.casefold()
    return SPOTIFY in source or any(browser in source for browser in BROWSERS)


def looks_like_song(source: str, title: str, artist: str, album: str) -> bool:
    """Spotify entries with an album and browser entries with an album or a "- Topic" artist are songs.
    Plain videos carry the channel as the artist and no album, so they are left out.
    """
    title, artist, album = title.strip(), artist.strip(), album.strip()
    if not title or not artist:
        return False
    if SPOTIFY in source.casefold():
        return bool(album) and title.casefold() not in ADVERTISEMENT_TITLES and artist.casefold() != SPOTIFY
    return bool(album) or artist.casefold().endswith("- topic")


def _seconds(value) -> float:
    try:
        return max(0.0, value.total_seconds())
    except AttributeError:
        return 0.0


async def _thumbnail(properties) -> bytes:
    from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions

    reference = properties.thumbnail
    if reference is None:
        return b""
    stream = await reference.open_read_async()
    if not stream.size or stream.size > MAX_COVER_BYTES:
        return b""
    buffer = Buffer(int(stream.size))
    await stream.read_async(buffer, buffer.capacity, InputStreamOptions.READ_AHEAD)
    reader = DataReader.from_buffer(buffer)
    data = bytearray(reader.unconsumed_buffer_length)
    reader.read_bytes(data)
    return bytes(data)


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read(MAX_COVER_BYTES)


class SongReader:
    """Reads the current song on every call; keep it on one thread, it owns an event loop."""

    def __init__(self):
        self._loop = None
        self._manager = None
        self._client = None
        self._client_checked = float("-inf")
        self._blocked_until = 0.0
        self._details: dict[str, dict] = {}
        self._details_at = float("-inf")
        self._covers: dict[str, bytes] = {}
        self._attempts: dict[str, int] = {}
        self._remote: Song | None = None
        self._remote_at = float("-inf")

    def close(self) -> None:
        if self._loop is not None:
            self._loop.close()
            self._loop = None

    def read(self) -> Song | None:
        if os.name != "nt":
            return self._read_remote()
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager,
            )
            self._manager = self._loop.run_until_complete(Manager.request_async())
        song = self._loop.run_until_complete(self._read_local())
        if song is not None and SPOTIFY in song.source.casefold():
            song = self._verified(song)
        if song is None:
            return self._read_remote()
        self._remote = None
        return song

    async def _read_local(self) -> Song | None:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
        )

        current = self._manager.get_current_session()
        current_source = current.source_app_user_model_id if current is not None else ""
        best = None
        for session in self._manager.get_sessions():
            source = session.source_app_user_model_id
            if not is_song_source(source):
                continue
            try:
                properties = await session.try_get_media_properties_async()
            except Exception:
                continue
            if not looks_like_song(source, properties.title or "", properties.artist or "",
                                   properties.album_title or ""):
                continue
            playback = session.get_playback_info()
            playing = playback.playback_status == Status.PLAYING
            rank = (not playing, source != current_source)
            if best is None or rank < best[0]:
                best = (rank, session, properties, playback, playing)
        if best is None:
            return None
        _, session, properties, playback, playing = best
        source = session.source_app_user_model_id
        timeline = session.get_timeline_properties()
        duration = max(0.0, _seconds(timeline.end_time) - _seconds(timeline.start_time))
        position = _seconds(timeline.position) - _seconds(timeline.start_time)
        updated = timeline.last_updated_time
        if playing and updated is not None and updated.year > 2000:
            position += max(0.0, (datetime.now(timezone.utc) - updated).total_seconds())
        if duration > 0:
            position = min(position, duration)
        title, artist = properties.title.strip(), properties.artist.strip()
        key = f"{title}\n{artist}".casefold()
        cover = self._covers.get(key, b"")
        if not cover and self._attempts.get(key, 0) < THUMBNAIL_ATTEMPTS:
            self._attempts[key] = self._attempts.get(key, 0) + 1
            try:
                cover = await _thumbnail(properties)
            except Exception:
                cover = b""
            if cover:
                self._covers[key] = cover
        return Song(source=source, title=title, artist=artist, album=(properties.album_title or "").strip(),
                    duration=duration, position=max(0.0, position), playing=playing,
                    seekable=bool(playback.controls.is_playback_position_enabled),
                    stamp=time.monotonic(), cover=cover)

    def _spotify(self):
        """The Spotify client when the user already authorized it; it never opens the browser."""
        now = time.monotonic()
        if now < self._blocked_until:
            return None
        if self._client is None and now - self._client_checked >= REMOTE_INTERVAL:
            self._client_checked = now
            try:
                client = media.spotify_authorized_client()
            except Exception:
                log.exception("The Spotify client could not be created")
                client = None
            self._client = client
        return self._client

    def _playback(self) -> dict | None:
        client = self._spotify()
        if client is None:
            return None
        try:
            return client.current_playback(additional_types="episode") or {}
        except Exception as error:
            log.warning("Spotify playback could not be read: %s", error)
            self._blocked_until = time.monotonic() + BACKOFF
            return None

    def _verified(self, song: Song) -> Song | None:
        """Confirm with Spotify that the local entry is a track, and take its album art and exact length."""
        details = self._details.get(song.key)
        if details is None and time.monotonic() - self._details_at >= DETAIL_INTERVAL:
            self._details_at = time.monotonic()
            state = self._playback()
            if state:
                details = self._details_from(song, state)
                if details is not None:
                    self._details[song.key] = details
        if details is None:
            return song
        if not details["track"]:
            return None
        return replace(song, artist=details["artists"] or song.artist, album=details["album"] or song.album,
                       duration=song.duration or details["duration"],
                       cover=self._covers.get(song.key, song.cover))

    def _details_from(self, song: Song, state: dict) -> dict | None:
        item = state.get("item") or {}
        if item.get("name", "").casefold() != song.title.casefold():
            return None
        if state.get("currently_playing_type") != "track":
            return {"track": False}
        album = item.get("album") or {}
        images = album.get("images") or []
        self._remember_cover(song.key, images[0]["url"] if images else "")
        return {"track": True, "album": album.get("name") or "",
                "artists": ", ".join(artist.get("name", "") for artist in item.get("artists", [])),
                "duration": (item.get("duration_ms") or 0) / 1000}

    def _remember_cover(self, key: str, url: str) -> None:
        if not url:
            return
        try:
            cover = _download(url)
        except Exception as error:
            log.warning("The album cover could not be downloaded: %s", error)
            return
        if cover:
            self._covers[key] = cover

    def _read_remote(self) -> Song | None:
        """A song playing on another Spotify device, such as a phone, read at most every few seconds."""
        now = time.monotonic()
        if now - self._remote_at < REMOTE_INTERVAL:
            return self._remote
        if self._spotify() is None:
            return None
        self._remote_at = now
        state = self._playback()
        item = (state or {}).get("item") or {}
        if not state or state.get("currently_playing_type") != "track" or not item.get("name"):
            self._remote = None
            return None
        album = item.get("album") or {}
        images = album.get("images") or []
        artist = ", ".join(artist.get("name", "") for artist in item.get("artists", []))
        key = f"{item['name']}\n{artist}".casefold()
        if key not in self._covers and images:
            self._remember_cover(key, images[0]["url"])
        self._remote = Song(source=SPOTIFY, title=item["name"], artist=artist, album=album.get("name") or "",
                            duration=(item.get("duration_ms") or 0) / 1000,
                            position=(state.get("progress_ms") or 0) / 1000, playing=bool(state.get("is_playing")),
                            seekable=True, stamp=time.monotonic(), cover=self._covers.get(key, b""))
        return self._remote


def control(song: Song, action: str) -> bool:
    """Play, pause, skip or go back on the player of the song; True when the player accepted it."""
    return _accepted(media.control_media(action, SPOTIFY if song.remote else song.source))


def seek(song: Song, seconds: float) -> bool:
    return _accepted(media.seek_media(seconds, SPOTIFY if song.remote else song.source))


def _accepted(result: str) -> bool:
    try:
        accepted = bool(json.loads(result).get("accepted"))
    except (ValueError, AttributeError):
        accepted = False
    if not accepted:
        log.warning("The player did not accept the command: %s", result)
    return accepted
