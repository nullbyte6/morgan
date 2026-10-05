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
"""Phone API: lets paired devices chat with this assistant and read Nova over the network.

It is off by default; turn it on with the "api" section of config.json:

    "api": {"enabled": true, "host": "127.0.0.1", "port": 8765,
            "allow_remote_confirmation": false, "tls_certificate": "", "tls_key": ""}

Only connections from loopback, private LAN or Tailscale addresses are served. Set host to the
Tailscale or LAN address (or 0.0.0.0) to reach it from a phone. Pair a device with
"python -m src.init.api pair", which prints a code valid for five minutes.

Every route except /v1/health and /v1/pair needs "Authorization: Bearer <token>".

    GET    /v1/health                                  liveness
    POST   /v1/pair                {code, device_name} -> {device_id, token}
    GET    /v1/me                                      assistant name, version, language
    DELETE /v1/me                                      unpair this device
    GET    /v1/sessions                                open sessions (at most 4)
    POST   /v1/sessions                                open a session
    GET    /v1/sessions/{id}                           session with its transcript
    DELETE /v1/sessions/{id}                           close a session
    POST   /v1/sessions/{id}/messages   {text}         -> {turn}; 409 while still answering
    POST   /v1/sessions/{id}/interrupt                 stop the current answer
    POST   /v1/sessions/{id}/confirmations/{n} {accepted}
    WS     /v1/sessions/{id}/stream                    server events as JSON text frames
    GET    /v1/nova/agenda?first_day&last_day          reminders and events
    POST   /v1/nova/reminders      {title, remind_at, notes, repeat}
    POST   /v1/nova/reminders/{id}/completion {completed}
    GET    /v1/nova/journal?first_day&last_day&query&limit
    GET    /v1/nova/search?query&limit                 agenda entries and journal entries

Stream events carry a "type": snapshot (first frame, with the transcript, the partial reply and
any pending confirmation), ready, accepted, chunk (text delta), step, phase, activity,
task_title, finished (full reply), failed, rejected, permission_denied, confirmation,
confirmation_blocked, confirmation_closed, resync (reconnect to get a fresh snapshot), closed
and ping. Commands that need the user's consent are refused unless allow_remote_confirmation
is on, in which case they are sent to the phone as confirmation events.
"""
import logging

from src.init.config import load_config

log = logging.getLogger("assistant.api")
_server = None


def start_api_server():
    """Start the API when config.json enables it; return the server or None."""
    global _server
    settings = load_config()["api"]
    if _server is not None or not settings["enabled"]:
        return _server
    from .server import ApiServer
    server = ApiServer(settings)
    server.start()
    _server = server
    log.info("API listening on %s:%s", settings["host"], settings["port"])
    return server


def stop_api_server():
    global _server
    server, _server = _server, None
    if server is not None:
        server.stop()
