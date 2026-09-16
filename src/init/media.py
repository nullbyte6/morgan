"""Local Windows playback control and free YouTube search from Python."""

import asyncio
import json
import os
import re
import subprocess
import sys
import webbrowser
from collections import OrderedDict
from typing import Literal

_videos = OrderedDict()
_spotify_tracks = OrderedDict()
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_SPOTIFY_SCOPES = (
    "user-read-playback-state user-read-currently-playing "
    "user-modify-playback-state"
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
        raise ValueError("Spotify is disabled: configure spotify-web-clientid and spotify-web-client_secret in config.json")
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
    except ImportError as error:
        raise ValueError("Spotipy is not installed; install requirements.txt and restart Nora") from error
    client_id, client_secret, _ = settings
    return spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=client_id, client_secret=client_secret,
    ))


def _spotify_player_client():
    """Create an OAuth player client, caching the user token outside config.json."""
    settings = _spotify_settings()
    if settings is None:
        raise ValueError("Spotify is disabled: configure spotify-web-clientid and spotify-web-client_secret in config.json")
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError as error:
        raise ValueError("Spotipy is not installed; install requirements.txt and restart Nora") from error
    from .config import HOME_PATH

    client_id, client_secret, redirect_uri = settings
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=_SPOTIFY_SCOPES,
        cache_path=str(HOME_PATH / "json" / "spotify_token.json"),
        open_browser=True,
    ))


def spotify_is_configured() -> bool:
    """Return whether Spotify credentials are available without exposing them."""
    return _spotify_settings() is not None


def _spotify_error(action: str, error: Exception) -> str:
    return (f"Error {action} in Spotify: {error}. Ensure the redirect URI "
            "in config.json is registered in the Spotify developer dashboard, "
            "authorize the browser prompt, and use an active Spotify Premium device.")


def _spotify_control(action: Literal["play", "pause", "next", "previous"],
                     uri: str | None = None) -> str:
    try:
        client = _spotify_player_client()
        if action == "play":
            client.start_playback(uris=[uri] if uri else None)
        elif action == "pause":
            client.pause_playback()
        elif action == "next":
            client.next_track()
        else:
            client.previous_track()
        return json.dumps({"action": action, "accepted": True,
                           "source": "spotify", "uri": uri}, ensure_ascii=False)
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
                           "instruction": "For ambiguous requests, ask the user to choose; do not play the first result automatically."},
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
            return f"Error searching YouTube: {result.stderr.strip() or 'yt-dlp failed'}. Ensure yt-dlp is installed."
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
                           "instruction": "For ambiguous requests, ask the user to choose; do not play the first result automatically."},
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
                           "note": "Check get_current_media before claiming playback; browser autoplay may require a click."},
                          ensure_ascii=False)
    except OSError as error:
        return f"Error opening YouTube: {error}"
