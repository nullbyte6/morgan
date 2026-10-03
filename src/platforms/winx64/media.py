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
"""Windows media sessions through GSMTC and output audio capture through WASAPI loopback."""

from src.init.lang import tr
import asyncio
from datetime import datetime, timezone
import json

from ..base import MediaReader, MediaSession

MAX_COVER_BYTES = 8_000_000


def _seconds(value):
    try:
        return max(0.0, value.total_seconds())
    except AttributeError:
        return 0.0


async def _thumbnail(properties):
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


class WinMediaReader(MediaReader):
    def __init__(self):
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )
        self._loop = asyncio.new_event_loop()
        self._manager = self._loop.run_until_complete(Manager.request_async())

    def sessions(self, accept=None):
        return self._loop.run_until_complete(self._sessions(accept))

    async def _sessions(self, accept):
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
        )

        current = self._manager.get_current_session()
        current_source = current.source_app_user_model_id if current is not None else ""
        result = []
        for session in self._manager.get_sessions():
            source = session.source_app_user_model_id
            if accept is not None and not accept(source):
                continue
            try:
                properties = await session.try_get_media_properties_async()
            except Exception:
                continue
            playback = session.get_playback_info()
            playing = playback.playback_status == Status.PLAYING
            timeline = session.get_timeline_properties()
            duration = max(0.0, _seconds(timeline.end_time) - _seconds(timeline.start_time))
            position = _seconds(timeline.position) - _seconds(timeline.start_time)
            updated = timeline.last_updated_time
            if playing and updated is not None and updated.year > 2000:
                position += max(0.0, (datetime.now(timezone.utc) - updated).total_seconds())
            if duration > 0:
                position = min(position, duration)
            result.append(MediaSession(
                source=source, title=properties.title or "", artist=properties.artist or "",
                album=properties.album_title or "", playing=playing,
                current=source == current_source, duration=duration,
                position=max(0.0, position),
                seekable=bool(playback.controls.is_playback_position_enabled),
                handle=properties))
        return result

    def cover(self, session):
        return self._loop.run_until_complete(_thumbnail(session.handle))

    def close(self):
        self._loop.close()


def current_media():
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as MediaManager,
    )

    async def read_media():
        manager = await MediaManager.request_async()

        session = manager.get_current_session()

        if session is None:
            return None

        properties = await session.try_get_media_properties_async()
        playback = session.get_playback_info()
        timeline = session.get_timeline_properties()

        return {
            "source": session.source_app_user_model_id,
            "title": properties.title or None,
            "artist": properties.artist or None,
            "album_title": properties.album_title or None,
            "album_artist": properties.album_artist or None,
            "track_number": properties.track_number or None,
            "playback_status": str(playback.playback_status),
            "position_seconds": (
                timeline.position.total_seconds()
                if timeline is not None
                else None
            ),
            "duration_seconds": (
                timeline.end_time.total_seconds()
                if timeline is not None
                else None
            ),
        }

    return asyncio.run(read_media())


def media_sessions():
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as MediaManager,
    )

    async def read_sessions():
        manager = await MediaManager.request_async()

        result = []

        for session in manager.get_sessions():
            try:
                properties = await session.try_get_media_properties_async()
                playback = session.get_playback_info()

                result.append({
                    "source": session.source_app_user_model_id,
                    "title": properties.title or None,
                    "artist": properties.artist or None,
                    "album": properties.album_title or None,
                    "playback_status": str(playback.playback_status),
                })

            except Exception as error:
                result.append({
                    "source": session.source_app_user_model_id,
                    "error": str(error),
                })

        return result

    return asyncio.run(read_sessions())


async def _session(manager, source):
    if source:
        matches = [session for session in manager.get_sessions()
                   if session.source_app_user_model_id == source]
        if len(matches) != 1:
            raise LookupError
        return matches[0]
    return manager.get_current_session()


def control_media(action, source=""):
    operations = {
        "play": ("is_play_enabled", "try_play_async"),
        "pause": ("is_pause_enabled", "try_pause_async"),
        "next": ("is_next_enabled", "try_skip_next_async"),
        "previous": ("is_previous_enabled", "try_skip_previous_async"),
    }

    async def apply():
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )
        manager = await Manager.request_async()
        try:
            session = await _session(manager, source)
        except LookupError:
            return tr('media.error_source_is_absent_or_matches_multiple_sessions_list_media_s')
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

    return asyncio.run(bounded())


def seek_media(seconds, source=""):
    async def apply():
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )
        manager = await Manager.request_async()
        try:
            session = await _session(manager, source)
        except LookupError:
            return tr('media.error_source_is_absent_or_matches_multiple_sessions_list_media_s')
        if session is None:
            return tr('media.error_no_active_media_session')
        if not session.get_playback_info().controls.is_playback_position_enabled:
            return tr('media.error_this_media_session_does_not_support', action="seek")
        accepted = await session.try_change_playback_position_async(round(seconds * 10_000_000))
        return json.dumps({"action": "seek", "accepted": bool(accepted),
                           "source": session.source_app_user_model_id})

    async def bounded():
        return await asyncio.wait_for(apply(), timeout=10)

    return asyncio.run(bounded())


def record_output_audio(seconds, sample_rate):
    import soundcard as sc

    speaker = sc.default_speaker()
    if speaker is None:
        raise OSError(tr('brain.error_no_default_audio_output_device_was_found'))
    loopbacks = sc.all_microphones(include_loopback=True)

    loopback = next(
        (microphone
            for microphone in loopbacks
            if speaker.name.casefold() in microphone.name.casefold()
               or microphone.name.casefold() in speaker.name.casefold()),
        None,
    )

    if loopback is None:
        raise OSError(tr('brain.error_no_loopback_device_found_for', value0=speaker.name))

    try:
        with loopback.recorder(samplerate=sample_rate) as recorder:
            return recorder.record(numframes=sample_rate * seconds)
    except Exception as error:
        raise OSError(tr('brain.error_capturing_system_audio', error=error)) from error
