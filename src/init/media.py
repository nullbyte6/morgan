"""Local Windows playback control and free YouTube search from Python."""

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
        raise ValueError("Spotify is disabled: configure spotify-web-clientid and "
                         "spotify-web-client_secret in config.json")
    try:
        import spotipy
        from spotipy.cache_handler import CacheFileHandler
        from spotipy.oauth2 import SpotifyClientCredentials
    except ImportError as error:
        raise ValueError("Spotipy is not installed; install requirements.txt and restart Nora") from error
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
        raise ValueError("Spotify is disabled: configure spotify-web-clientid "
                         "and spotify-web-client_secret in config.json")
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError as error:
        raise ValueError("Spotipy is not installed; install requirements.txt and restart Nora") from error
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
    return (f"Error {action} in Spotify: {error}. Ensure the redirect URI "
            "in config.json is registered in the Spotify developer dashboard, "
            "authorize the browser prompt, and use an active Spotify Premium device.")


def _spotify_target_device(client) -> str:
    """Choose a safe playback target when Spotify has no active device.
    An explicitly configured device wins. Otherwise Nora uses the device whose
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
        raise ValueError("the configured spotify_device_id is not currently available")
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
        raise ValueError("no Spotify Connect devices are available; open Spotify and start a track once")
    raise ValueError("no active or local Spotify device was found; choose one with "
                     f"spotify_device_id in config.json: {json.dumps(candidates, ensure_ascii=False)}")


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
        "note": "Spotify accepted the command but did not report the requested track as playing.",
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
        return _spotify_error(f"controlling {action}", error)


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
        return "Error: media control requires Windows"
    operations = {
        "play": ("is_play_enabled", "try_play_async"),
        "pause": ("is_pause_enabled", "try_pause_async"),
        "next": ("is_next_enabled", "try_skip_next_async"),
        "previous": ("is_previous_enabled", "try_skip_previous_async"),
    }
    if action not in operations:
        return "Error: choose play, pause, next or previous"

    async def apply():
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )
        manager = await Manager.request_async()
        if source:
            matches = [session for session in manager.get_sessions()
                       if session.source_app_user_model_id == source]
            if len(matches) != 1:
                return "Error: source is absent or matches multiple sessions; list media sessions again"
            session = matches[0]
        else:
            session = manager.get_current_session()
        if session is None:
            return None
        flag, method = operations[action]
        if not getattr(session.get_playback_info().controls, flag):
            return f"Error: this media session does not support {action}"
        accepted = await getattr(session, method)()
        return json.dumps({"action": action, "accepted": bool(accepted),
                           "source": session.source_app_user_model_id,
                           "error": None if accepted else "Application rejected the command"})

    async def bounded():
        return await asyncio.wait_for(apply(), timeout=10)

    try:
        result = asyncio.run(bounded())
        if result is None and not source and spotify_is_configured():
            return _spotify_control(action)
        return result or "Error: no active media session"
    except Exception as error:
        return f"Error controlling media: {error or type(error).__name__}"


def search_spotify_songs(query: str, max_results: int = 5) -> str:
    """Search Spotify tracks when Spotify is configured; does not start playback.
    Results contain Spotify track URIs. Use play_spotify_song with one URI from
    this recent search. Client credentials are enough to search; playback later
    opens the user OAuth flow only when it is needed.
    """
    if not query.strip():
        return "Error: specify a song, artist or search phrase"
    if type(max_results) is not int or not 1 <= max_results <= 10:
        return "Error: max_results must be between 1 and 10"
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
                           "instruction": "For ambiguous requests, ask the user to choose; "
                                          "do not play the first result automatically."},
                          ensure_ascii=False)
    except Exception as error:
        return _spotify_error("searching", error)


def play_spotify_song(uri: str) -> str:
    """Play a recent Spotify search result on the active Spotify device.
    The first playback request opens Spotify OAuth if needed. Spotify Premium
    and an active Spotify Connect device are required by Spotify's Player API.
    """
    if uri not in _spotify_tracks:
        return "Error: uri must come from a recent search_spotify_songs result; search again"
    return _spotify_control("play", uri)


def search_spotify_playlists(query: str, max_results: int = 10) -> str:
    """Search public Spotify playlists by name without reading their tracks."""
    if not query.strip():
        return "Error: specify a playlist name or search phrase"
    if type(max_results) is not int or not 1 <= max_results <= 10:
        return "Error: max_results must be between 1 and 10"
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
                           "instruction": "Choose a numbered result when ambiguous, then use its exact uri with play_spotify_playlist. Do not read tracks merely to play a public playlist."},
                          ensure_ascii=False)
    except Exception as error:
        return _spotify_error("searching playlists", error)


def search_spotify_albums(query: str, max_results: int = 10) -> str:
    """Search Spotify albums and cache their context URIs for playback."""
    if not query.strip():
        return "Error: specify an album, artist or search phrase"
    if type(max_results) is not int or not 1 <= max_results <= 10:
        return "Error: max_results must be between 1 and 10"
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
                           "instruction": "Choose a numbered result when ambiguous, then use its exact uri with play_spotify_album."},
                          ensure_ascii=False)
    except Exception as error:
        return _spotify_error("searching albums", error)


def play_spotify_album(uri: str) -> str:
    """Start an album returned by search_spotify_albums."""
    if uri not in _spotify_albums:
        return "Error: uri must come from a recent search_spotify_albums result; search again"
    return _spotify_control("play", uri, context=True)


def list_spotify_playlists(max_results: int = 50) -> str:
    """List playlists owned or followed by the authorized Spotify user.
    This uses the current-user endpoint and OAuth playlist scopes. Results are
    cached by URI so a later play_spotify_playlist call cannot guess an ID.
    """
    if type(max_results) is not int or not 1 <= max_results <= 500:
        return "Error: max_results must be between 1 and 500"
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
            "instruction": "For ambiguous playlist requests, ask the user to choose a "
                           "numbered playlist; then use its exact uri.",
        }, ensure_ascii=False)
    except Exception as error:
        return _spotify_error("listing playlists", error)


def get_spotify_playlist_tracks(uri: str, max_results: int = 100) -> str:
    """Read tracks from a playlist returned by list_spotify_playlists."""
    if uri not in _spotify_playlists:
        return "Error: uri must come from a recent list_spotify_playlists result; list playlists again"
    if type(max_results) is not int or not 1 <= max_results <= 500:
        return "Error: max_results must be between 1 and 500"
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
        return _spotify_error("reading playlist tracks", error)


def play_spotify_playlist(uri: str) -> str:
    """Start a playlist returned by list_spotify_playlists on Spotify."""
    if uri not in _spotify_playlists:
        return "Error: uri must come from a recent list_spotify_playlists result; list playlists again"
    return _spotify_control("play", uri, context=True)


def search_youtube_songs(query: str, max_results: int = 5) -> str:
    """Search YouTube without playing or downloading anything.
    Returns numbered candidates with video_id, title, channel and duration.
    If the request is ambiguous, present candidates and wait for the user's
    choice before calling play_youtube_song with the corresponding video_id.
    Uses local yt-dlp; requires Internet but no API key or paid service.
    """
    if not query.strip():
        return "Error: specify a song, artist or search phrase"
    if type(max_results) is not int or not 1 <= max_results <= 10:
        return "Error: max_results must be between 1 and 10"
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
            return (f"Error searching YouTube: {result.stderr.strip() or 'yt-dlp failed'}. "
                    f"Ensure yt-dlp is installed.")
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
                           "instruction": "For ambiguous requests, ask the user to choose; "
                                          "do not play the first result automatically."},
                          ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return "Error: YouTube search timed out; try again"
    except (OSError, ValueError) as error:
        return f"Error searching YouTube: {error}"


def play_youtube_song(video_id: str) -> str:
    """Open a candidate from search_youtube_songs in YouTube with autoplay requested.
    Use the user's selection when the original request was ambiguous. Browser
    autoplay may be blocked; opening a video does not confirm playback.
    """
    candidate = _videos.get(video_id)
    if candidate is None:
        return "Error: video_id must come from a recent search_youtube_songs result; search again"
    url = candidate["url"] + "&autoplay=1"
    try:
        if not webbrowser.open(url, new=2):
            return "Error: the browser did not accept the YouTube URL"
        return json.dumps({"opened": True, "title": candidate["title"], "url": url,
                           "playback_confirmed": False,
                           "note": "Check get_current_media before claiming playback;"
                                   " browser autoplay may require a click."},
                          ensure_ascii=False)
    except OSError as error:
        return f"Error opening YouTube: {error}"
