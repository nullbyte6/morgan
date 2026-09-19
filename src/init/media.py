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
"""Local Windows playback control and free YouTube search from Python."""

from src.init.lang import tr
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import webbrowser
from collections import OrderedDict
from typing import Literal

_videos = OrderedDict()
_spotify_tracks = OrderedDict()
_spotify_playlists = OrderedDict()
_spotify_albums = OrderedDict()
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_SPOTIFY_SCOPES = (
    "user-read-playback-state user-read-currently-playing "
    "user-modify-playback-state user-read-private "
    "playlist-read-private playlist-read-collaborative"
)


def _spotify_settings() -> tuple[str, str, str] | None:
    """Return Spotify credentials only when the user configured both values."""
    from .config import load_config

    config = load_config()
    client_id = config["spotify-web-clientid"].strip()
    client_secret = config["spotify-web-client_secret"].strip()
    redirect_uri = config["spotify_redirect_uri"].strip()
    if not client_id or not client_secret:
        return None
    return client_id, client_secret, redirect_uri


def _spotify_metadata_client():
    settings = _spotify_settings()
    if settings is None:
        raise ValueError(tr('media.spotify_is_disabled_configure_spotify_web_clientid_and_spotify_w'))
    try:
        import spotipy
        from spotipy.cache_handler import CacheFileHandler
        from spotipy.oauth2 import SpotifyClientCredentials
    except ImportError as error:
        raise ValueError(tr('media.spotipy_is_not_installed_install_requirements_txt_and_restart_ar')) from error
    from .config import HOME_PATH

    client_id, client_secret, _ = settings
    return spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=client_id,
        client_secret=client_secret,
        cache_handler=CacheFileHandler(
            cache_path=str(HOME_PATH / "json" / "spotify_client_token.json"),
        ),
    ))


def _spotify_player_client():
    """Create an OAuth player client with a cache isolated per Spotify app."""
    settings = _spotify_settings()
    if settings is None:
        raise ValueError(tr('media.spotify_is_disabled_configure_spotify_web_clientid_and_spotify_w'))
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError as error:
        raise ValueError(tr('media.spotipy_is_not_installed_install_requirements_txt_and_restart_ar')) from error
    from .config import HOME_PATH

    client_id, client_secret, redirect_uri = settings
    app_key = hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:16]
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=_SPOTIFY_SCOPES,
        cache_path=str(HOME_PATH / "json" / f"spotify_token_{app_key}.json"),
        show_dialog=True,
        open_browser=True,
    ))


def spotify_is_configured() -> bool:
    """Return whether Spotify credentials are available without exposing them."""
    return _spotify_settings() is not None


def _spotify_error(action: str, error: Exception) -> str:
    return (tr('media.error_in_spotify_ensure_the_redirect_uri_in_config_json_is_regis', action=action, error=error))


def _spotify_target_device(client) -> str:
    """Choose a safe playback target when Spotify has no active device.
    An explicitly configured device wins. Otherwise, Arlo uses the device whose
    name equals this Windows computer name. It never guesses among unrelated
    Spotify Connect devices such as speakers in another room.
    """
    from .config import load_config

    devices = [device for device in client.devices().get("devices", [])
               if not device.get("is_restricted") and device.get("id")]
    configured = load_config()["spotify_device_id"].strip()
    if configured:
        if any(device["id"] == configured for device in devices):
            return configured
        raise ValueError(tr('media.the_configured_spotify_device_id_is_not_currently_available'))
    active = [device for device in devices if device.get("is_active")]
    if active:
        return active[0]["id"]

    computer_name = os.environ.get("COMPUTERNAME", "").casefold()
    local = [device for device in devices
             if device.get("name", "").casefold() == computer_name]

    if len(local) == 1:
        return local[0]["id"]
    candidates = [{"id": device["id"], "name": device.get("name"),
                   "type": device.get("type")}
                  for device in devices]
    if not candidates:
        raise ValueError(tr('media.no_spotify_connect_devices_are_available_open_spotify_and_start'))
    raise ValueError(tr('media.no_active_or_local_spotify_device_was_found_choose_one_with_spot', value0=json.dumps(candidates, ensure_ascii=False)))


def _spotify_playback_confirmation(client, expected_uri: str | None,
                                   expected_context_uri: str | None = None) -> dict:
    """Read Spotify after a player command; HTTP 204 alone is not playback."""
    for _ in range(3):
        state = client.current_playback() or {}
        item = state.get("item") or {}
        uri = item.get("uri")
        context_uri = (state.get("context") or {}).get("uri")
        playing = bool(state.get("is_playing"))
        track_matches = expected_uri is None or uri == expected_uri
        context_matches = (expected_context_uri is None
                           or context_uri == expected_context_uri)
        if playing and track_matches and context_matches:
            return {
                "playback_confirmed": True,
                "confirmed_uri": uri,
                "confirmed_context_uri": context_uri,
                "title": item.get("name"),
                "artists": [artist.get("name") for artist in item.get("artists", [])],
                "device": (state.get("device") or {}).get("name"),
            }
        time.sleep(0.4)
    return {
        "playback_confirmed": False,
        "confirmed_uri": uri,
        "confirmed_context_uri": context_uri,
        "is_playing": playing,
        "device": (state.get("device") or {}).get("name"),
        "note": tr('media.spotify_accepted_the_command_but_did_not_report_the_requested_tr'),
    }


def _spotify_control(action: Literal["play", "pause", "next", "previous"],
        uri: str | None = None, context: bool = False) -> str:
    try:
        client = _spotify_player_client()
        device_id = _spotify_target_device(client)

        if action == "play":
            devices = client.devices().get("devices", [])
            target = next((d for d in devices if d.get("id") == device_id), None)
            if target is not None and not target.get("is_active"):
                client.transfer_playback(
                    device_id=device_id,
                    force_play=False,
                )
                time.sleep(0.5)

            playback = {"device_id": device_id}
            if context:
                playback["context_uri"] = uri
            else:
                playback["uris"] = [uri] if uri else None
            client.start_playback(**playback)

        elif action == "pause":
            client.pause_playback(device_id=device_id)

        elif action == "next":
            client.next_track(device_id=device_id)

        else:
            client.previous_track(device_id=device_id)

        response = {
            "action": action,
            "accepted": True,
            "source": "spotify",
            "uri": uri,
            "device_id": device_id,
        }

        if action == "play":
            response.update(_spotify_playback_confirmation(
                client, None if context else uri,
                uri if context else None,
            ))
        return json.dumps(response, ensure_ascii=False)

    except Exception as error:
        return _spotify_error(tr('media.controlling', action=action), error)


def control_media(action: Literal["play", "pause", "next", "previous"],
                  source: str = "") -> str:
    """Control the active Windows media session, or an exact source ID.
    Obtain source IDs with list_media_sessions if targeting a particular app.
    Returns whether the application accepted the command; unsupported controls
    and absent sessions are errors, not successes. Does not simulate keystrokes.
    """
    if source.strip().casefold() == "spotify":
        return _spotify_control(action)
    if os.name != "nt":
        return tr('media.error_media_control_requires_windows')
    operations = {
        "play": ("is_play_enabled", "try_play_async"),
        "pause": ("is_pause_enabled", "try_pause_async"),
        "next": ("is_next_enabled", "try_skip_next_async"),
        "previous": ("is_previous_enabled", "try_skip_previous_async"),
    }
    if action not in operations:
        return tr('media.error_choose_play_pause_next_or_previous')

    async def apply():
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )
        manager = await Manager.request_async()
        if source:
            matches = [session for session in manager.get_sessions()
                       if session.source_app_user_model_id == source]
            if len(matches) != 1:
                return tr('media.error_source_is_absent_or_matches_multiple_sessions_list_media_s')
            session = matches[0]
        else:
            session = manager.get_current_session()
        if session is None:
            return None
        flag, method = operations[action]
        if not getattr(session.get_playback_info().controls, flag):
            return tr('media.error_this_media_session_does_not_support', action=action)
        accepted = await getattr(session, method)()
        return json.dumps({"action": action, "accepted": bool(accepted),
                           "source": session.source_app_user_model_id,
                           "error": None if accepted else tr('media.application_rejected_the_command')})

    async def bounded():
        return await asyncio.wait_for(apply(), timeout=10)

    try:
        result = asyncio.run(bounded())
        if result is None and not source and spotify_is_configured():
            return _spotify_control(action)
        return result or tr('media.error_no_active_media_session')
    except Exception as error:
        return tr('media.error_controlling_media', value0=error or type(error).__name__)


def search_spotify_songs(query: str, max_results: int = 5) -> str:
    """Search Spotify tracks when Spotify is configured; does not start playback.
    Results contain Spotify track URIs. Use play_spotify_song with one URI from
    this recent search. Client credentials are enough to search; playback later
    opens the user OAuth flow only when it is needed.
    """
    if not query.strip():
        return tr('media.error_specify_a_song_artist_or_search_phrase')
    if type(max_results) is not int or not 1 <= max_results <= 10:
        return tr('media.error_max_results_must_be_between_1_and_10')
    try:
        items = _spotify_metadata_client().search(
            q=query.strip(), type="track", limit=max_results,
        ).get("tracks", {}).get("items", [])
        candidates = []
        for item in items:
            uri = item.get("uri", "")
            if not uri.startswith("spotify:track:"):
                continue
            candidate = {
                "number": len(candidates) + 1,
                "uri": uri,
                "title": item.get("name"),
                "artists": [artist.get("name") for artist in item.get("artists", [])],
                "album": (item.get("album") or {}).get("name"),
                "duration_seconds": round((item.get("duration_ms") or 0) / 1000),
            }
            candidates.append(candidate)
            _spotify_tracks[uri] = candidate
            _spotify_tracks.move_to_end(uri)
        while len(_spotify_tracks) > 100:
            _spotify_tracks.popitem(last=False)
        return json.dumps({"query": query, "service": "spotify",
                           "candidates": candidates,
                           "instruction": tr('media.for_ambiguous_requests_ask_the_user_to_choose_do_not_play_the_fi')},
                          ensure_ascii=False)
    except Exception as error:
        return _spotify_error("searching", error)


def play_spotify_song(uri: str) -> str:
    """Play a recent Spotify search result on the active Spotify device.
    The first playback request opens Spotify OAuth if needed. Spotify Premium
    and an active Spotify Connect device are required by Spotify's Player API.
    """
    if uri not in _spotify_tracks:
        return tr('media.error_uri_must_come_from_a_recent_search_spotify_songs_result_se')
    return _spotify_control("play", uri)


def search_spotify_playlists(query: str, max_results: int = 10) -> str:
    """Search public Spotify playlists by name without reading their tracks."""
    if not query.strip():
        return tr('media.error_specify_a_playlist_name_or_search_phrase')
    if type(max_results) is not int or not 1 <= max_results <= 10:
        return tr('media.error_max_results_must_be_between_1_and_10')
    try:
        items = _spotify_player_client().search(
            q=query.strip(), type="playlist", limit=max_results,
        ).get("playlists", {}).get("items", [])
        candidates = []
        for playlist in items:
            if not playlist or playlist.get("type") != "playlist":
                continue
            uri = playlist.get("uri", "")
            if not uri.startswith("spotify:playlist:"):
                continue
            candidate = {
                "number": len(candidates) + 1,
                "uri": uri,
                "name": playlist.get("name"),
                "owner": (playlist.get("owner") or {}).get("display_name")
                         or (playlist.get("owner") or {}).get("id"),
                "public": playlist.get("public"),
                "collaborative": playlist.get("collaborative"),
                "tracks_total": (playlist.get("tracks") or {}).get("total"),
            }
            candidates.append(candidate)
            _spotify_playlists[uri] = candidate
            _spotify_playlists.move_to_end(uri)
        return json.dumps({"service": "spotify", "query": query,
                           "playlists": candidates,
                           "instruction": tr('media.choose_a_numbered_result_when_ambiguous_then_use_its_exact_uri_w')},
                          ensure_ascii=False)
    except Exception as error:
        return _spotify_error(tr('media.searching_playlists'), error)


def search_spotify_albums(query: str, max_results: int = 10) -> str:
    """Search Spotify albums and cache their context URIs for playback."""
    if not query.strip():
        return tr('media.error_specify_an_album_artist_or_search_phrase')
    if type(max_results) is not int or not 1 <= max_results <= 10:
        return tr('media.error_max_results_must_be_between_1_and_10')
    try:
        items = _spotify_metadata_client().search(
            q=query.strip(), type="album", limit=max_results,
        ).get("albums", {}).get("items", [])
        candidates = []
        for album in items:
            uri = album.get("uri", "")
            if not uri.startswith("spotify:album:"):
                continue
            candidate = {
                "number": len(candidates) + 1,
                "uri": uri,
                "name": album.get("name"),
                "artists": [artist.get("name") for artist in album.get("artists", [])],
                "release_date": album.get("release_date"),
                "total_tracks": album.get("total_tracks"),
            }
            candidates.append(candidate)
            _spotify_albums[uri] = candidate
            _spotify_albums.move_to_end(uri)
        return json.dumps({"service": "spotify", "query": query,
                           "albums": candidates,
                           "instruction": tr('media.choose_a_numbered_result_when_ambiguous_then_use_its_exact_uri_w_88125e')},
                          ensure_ascii=False)
    except Exception as error:
        return _spotify_error(tr('media.searching_albums'), error)


def play_spotify_album(uri: str) -> str:
    """Start an album returned by search_spotify_albums."""
    if uri not in _spotify_albums:
        return tr('media.error_uri_must_come_from_a_recent_search_spotify_albums_result_s')
    return _spotify_control("play", uri, context=True)


def list_spotify_playlists(max_results: int = 50) -> str:
    """List playlists owned or followed by the authorized Spotify user.
    This uses the current-user endpoint and OAuth playlist scopes. Results are
    cached by URI so a later play_spotify_playlist call cannot guess an ID.
    """
    if type(max_results) is not int or not 1 <= max_results <= 500:
        return tr('media.error_max_results_must_be_between_1_and_500')
    try:
        client = _spotify_player_client()
        page = client.current_user_playlists(limit=min(max_results, 50))
        candidates = []
        while page and len(candidates) < max_results:
            for playlist in page.get("items", []):
                uri = playlist.get("uri", "")
                if not uri.startswith("spotify:playlist:"):
                    continue
                candidate = {
                    "number": len(candidates) + 1,
                    "uri": uri,
                    "name": playlist.get("name"),
                    "owner": (playlist.get("owner") or {}).get("display_name")
                             or (playlist.get("owner") or {}).get("id"),
                    "public": playlist.get("public"),
                    "collaborative": playlist.get("collaborative"),
                    "tracks_total": (playlist.get("tracks") or {}).get("total"),
                }
                candidates.append(candidate)
                _spotify_playlists[uri] = candidate
                _spotify_playlists.move_to_end(uri)
                if len(candidates) >= max_results:
                    break
            if len(candidates) >= max_results or not page.get("next"):
                break
            page = client.next(page)
        while len(_spotify_playlists) > 500:
            _spotify_playlists.popitem(last=False)
        return json.dumps({
            "service": "spotify",
            "playlists": candidates,
            "instruction": tr('media.for_ambiguous_playlist_requests_ask_the_user_to_choose_a_numbere'),
        }, ensure_ascii=False)
    except Exception as error:
        return _spotify_error(tr('media.listing_playlists'), error)


def get_spotify_playlist_tracks(uri: str, max_results: int = 100) -> str:
    """Read tracks from a playlist returned by list_spotify_playlists."""
    if uri not in _spotify_playlists:
        return tr('media.error_uri_must_come_from_a_recent_list_spotify_playlists_result')
    if type(max_results) is not int or not 1 <= max_results <= 500:
        return tr('media.error_max_results_must_be_between_1_and_500')
    playlist_id = uri.rsplit(":", 1)[-1]
    try:
        client = _spotify_player_client()
        page = client.playlist_items(playlist_id, limit=min(max_results, 50))
        tracks = []
        while page and len(tracks) < max_results:
            for entry in page.get("items", []):
                track = entry.get("track") or {}
                track_uri = track.get("uri")
                if not track_uri:
                    continue
                tracks.append({
                    "number": len(tracks) + 1,
                    "uri": track_uri,
                    "title": track.get("name"),
                    "artists": [artist.get("name") for artist in track.get("artists", [])],
                })
                if len(tracks) >= max_results:
                    break
            if len(tracks) >= max_results or not page.get("next"):
                break
            page = client.next(page)
        return json.dumps({"playlist_uri": uri, "playlist": _spotify_playlists[uri].get("name"),
                           "tracks": tracks}, ensure_ascii=False)
    except Exception as error:
        return _spotify_error(tr('media.reading_playlist_tracks'), error)


def play_spotify_playlist(uri: str) -> str:
    """Start a playlist returned by list_spotify_playlists on Spotify."""
    if uri not in _spotify_playlists:
        return tr('media.error_uri_must_come_from_a_recent_list_spotify_playlists_result')
    return _spotify_control("play", uri, context=True)


def search_youtube_songs(query: str, max_results: int = 5) -> str:
    """Search YouTube without playing or downloading anything.
    Returns numbered candidates with video_id, title, channel and duration.
    If the request is ambiguous, present candidates and wait for the user's
    choice before calling play_youtube_song with the corresponding video_id.
    Uses local yt-dlp; requires Internet but no API key or paid service.
    """
    if not query.strip():
        return tr('media.error_specify_a_song_artist_or_search_phrase')
    if type(max_results) is not int or not 1 <= max_results <= 10:
        return tr('media.error_max_results_must_be_between_1_and_10')
    try:
        command = [sys.executable, "-m", "yt_dlp", "--ignore-config",
                   "--flat-playlist", "--dump-single-json", "--skip-download",
                   "--no-warnings", "--no-progress", "--socket-timeout", "10",
                   "--retries", "1", "--extractor-retries", "1", "--",
                   f"ytsearch{max_results}:{query.strip()}"]
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=45, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode:
            return (tr('media.error_searching_youtube_ensure_yt_dlp_is_installed', value0=result.stderr.strip() or tr('media.yt_dlp_failed')))
        entries = json.loads(result.stdout).get("entries") or []
        candidates = []
        for entry in entries:
            if not entry or not _VIDEO_ID.fullmatch(entry.get("id", "")):
                continue
            candidate = {"number": len(candidates) + 1, "video_id": entry["id"],
                         "title": entry.get("title"), "channel": entry.get("channel") or entry.get("uploader"),
                         "duration_seconds": entry.get("duration"),
                         "url": f"https://www.youtube.com/watch?v={entry['id']}"}
            candidates.append(candidate)
            _videos[entry["id"]] = candidate
            _videos.move_to_end(entry["id"])
        while len(_videos) > 100:
            _videos.popitem(last=False)
        return json.dumps({"query": query, "candidates": candidates,
                           "instruction": tr('media.for_ambiguous_requests_ask_the_user_to_choose_do_not_play_the_fi')},
                          ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return tr('media.error_youtube_search_timed_out_try_again')
    except (OSError, ValueError) as error:
        return tr('media.error_searching_youtube', error=error)


def play_youtube_song(video_id: str) -> str:
    """Open a candidate from search_youtube_songs in YouTube with autoplay requested.
    Use the user's selection when the original request was ambiguous. Browser
    autoplay may be blocked; opening a video does not confirm playback.
    """
    candidate = _videos.get(video_id)
    if candidate is None:
        return tr('media.error_video_id_must_come_from_a_recent_search_youtube_songs_resu')
    url = candidate["url"] + "&autoplay=1"
    try:
        if not webbrowser.open(url, new=2):
            return tr('media.error_the_browser_did_not_accept_the_youtube_url')
        return json.dumps({"opened": True, "title": candidate["title"], "url": url,
                           "playback_confirmed": False,
                           "note": tr('media.check_get_current_media_before_claiming_playback_browser_autopla')},
                          ensure_ascii=False)
    except OSError as error:
        return tr('media.error_opening_youtube', error=error)
