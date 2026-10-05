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
"""HTTP and WebSocket server that lets paired phones talk to this assistant."""
import asyncio
import ipaddress
import logging
import threading
import time

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from .auth import DeviceStore, PairingCodes
from .sessions import (InvalidMessage, SUBSCRIBER_BACKLOG, SessionBusy, SessionLimitReached,
                       SessionManager)

API_VERSION = 1
PING_INTERVAL = 25
PAIR_FAILURE_LIMIT = 10
PAIR_FAILURE_WINDOW = 300
CARRIER_GRADE_NAT = ipaddress.ip_network("100.64.0.0/10")

log = logging.getLogger("assistant.api")


def is_private_address(host) -> bool:
    try:
        address = ipaddress.ip_address(str(host).split("%")[0])
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return (address.is_loopback or address.is_private or address.is_link_local
            or address in CARRIER_GRADE_NAT)


class PrivateNetworkOnly:
    """Refuse every connection that does not come from a local or Tailscale address."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            if client is None or not is_private_address(client[0]):
                if scope["type"] == "http":
                    await JSONResponse({"detail": "Forbidden"}, status_code=403)(scope, receive, send)
                else:
                    await send({"type": "websocket.close", "code": 1008})
                return
        await self.app(scope, receive, send)


class PairBody(BaseModel):
    code: str = Field(max_length=32)
    device_name: str = Field(default="Phone", max_length=60)


class MessageBody(BaseModel):
    text: str


class ConfirmationBody(BaseModel):
    accepted: bool


class ReminderBody(BaseModel):
    title: str = Field(max_length=300)
    remind_at: str = Field(max_length=40)
    notes: str = Field(default="", max_length=2000)
    repeat: str = Field(default="none", max_length=20)


class CompletionBody(BaseModel):
    completed: bool = True


def _bearer(headers) -> str:
    scheme, _, token = headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def _checked(result: dict) -> dict:
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "The request failed"))
    return result


def create_app(manager: SessionManager, devices: DeviceStore, pairing: PairingCodes,
               settings: dict) -> FastAPI:
    app = FastAPI(title="Morgan API", version=str(API_VERSION), docs_url=None,
                  redoc_url=None, openapi_url=None)
    failures = {}
    failures_lock = threading.Lock()

    def authenticate(request: Request) -> dict:
        device = devices.verify(_bearer(request.headers))
        if device is None:
            raise HTTPException(401, "Invalid or missing token",
                                headers={"WWW-Authenticate": "Bearer"})
        return device

    def session_or_404(session_id: str):
        session = manager.get(session_id)
        if session is None:
            raise HTTPException(404, "Unknown session")
        return session

    @app.get("/v1/health")
    def health():
        return {"status": "ok", "api": API_VERSION}

    @app.post("/v1/pair")
    def pair(body: PairBody, request: Request):
        client = request.client.host if request.client else ""
        now = time.monotonic()
        with failures_lock:
            recent = [stamp for stamp in failures.get(client, [])
                      if now - stamp < PAIR_FAILURE_WINDOW]
            failures[client] = recent
            if len(recent) >= PAIR_FAILURE_LIMIT:
                raise HTTPException(429, "Too many attempts; try again later")
        if not pairing.redeem(body.code):
            with failures_lock:
                failures[client].append(now)
            raise HTTPException(403, "Invalid or expired pairing code")
        device_id, token = devices.add(body.device_name)
        log.info("Paired device %s (%s)", device_id, body.device_name)
        return {"device_id": device_id, "token": token}

    @app.get("/v1/me")
    def me(device: dict = Depends(authenticate)):
        from src.init.brain import get_version
        from src.init.config import load_config
        from src.init.identity import get_assistant_name
        return {"assistant": get_assistant_name(), "version": get_version(),
                "language": load_config()["lang"], "api": API_VERSION, "device": device,
                "remote_confirmation": settings["allow_remote_confirmation"]}

    @app.delete("/v1/me")
    def unpair(device: dict = Depends(authenticate)):
        devices.revoke(device["id"])
        return {"ok": True}

    @app.get("/v1/sessions")
    def list_sessions(device: dict = Depends(authenticate)):
        return {"sessions": manager.list()}

    @app.post("/v1/sessions", status_code=201)
    def create_session(device: dict = Depends(authenticate)):
        try:
            return manager.create().summary()
        except SessionLimitReached as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/v1/sessions/{session_id}")
    def get_session(session_id: str, device: dict = Depends(authenticate)):
        session = session_or_404(session_id)
        return {**session.summary(), "transcript": list(session.transcript)}

    @app.delete("/v1/sessions/{session_id}")
    def close_session(session_id: str, device: dict = Depends(authenticate)):
        if not manager.close(session_id):
            raise HTTPException(404, "Unknown session")
        return {"ok": True}

    @app.post("/v1/sessions/{session_id}/messages", status_code=202)
    def send_message(session_id: str, body: MessageBody, device: dict = Depends(authenticate)):
        session = session_or_404(session_id)
        if session.error:
            raise HTTPException(503, session.error)
        try:
            return {"turn": session.send(body.text)}
        except InvalidMessage as error:
            raise HTTPException(400, str(error)) from error
        except SessionBusy as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/v1/sessions/{session_id}/interrupt")
    def interrupt(session_id: str, device: dict = Depends(authenticate)):
        session_or_404(session_id).interrupt()
        return {"ok": True}

    @app.post("/v1/sessions/{session_id}/confirmations/{request_id}")
    def confirm(session_id: str, request_id: int, body: ConfirmationBody,
                device: dict = Depends(authenticate)):
        session = session_or_404(session_id)
        if not settings["allow_remote_confirmation"]:
            raise HTTPException(403, "Confirmations must be answered on the PC")
        if not session.confirm(request_id, body.accepted):
            raise HTTPException(404, "No such pending confirmation")
        return {"ok": True}

    @app.websocket("/v1/sessions/{session_id}/stream")
    async def stream(websocket: WebSocket, session_id: str):
        session = manager.get(session_id)
        device = devices.verify(_bearer(websocket.headers))
        if device is None or session is None:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        queue = asyncio.Queue(maxsize=SUBSCRIBER_BACKLOG)
        snapshot = session.subscribe(queue, asyncio.get_running_loop())

        async def sender():
            await websocket.send_json(snapshot)
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), PING_INTERVAL)
                except asyncio.TimeoutError:
                    event = {"type": "ping"}
                await websocket.send_json(event)
                if event["type"] == "closed":
                    return

        async def receiver():
            while True:
                await websocket.receive_text()

        tasks = [asyncio.ensure_future(sender()), asyncio.ensure_future(receiver())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            session.unsubscribe(queue)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await websocket.close()
            except (RuntimeError, WebSocketDisconnect):
                pass

    @app.get("/v1/nova/agenda")
    def agenda(first_day: str | None = None, last_day: str | None = None,
               device: dict = Depends(authenticate)):
        from src.init.nova.tools import list_agenda
        return _checked(list_agenda(first_day, last_day))

    @app.post("/v1/nova/reminders", status_code=201)
    def add_reminder(body: ReminderBody, device: dict = Depends(authenticate)):
        from src.init.nova.tools import add_reminder as add
        return _checked(add(body.title, body.remind_at, body.notes, body.repeat))

    @app.post("/v1/nova/reminders/{reminder_id}/completion")
    def complete_reminder(reminder_id: str, body: CompletionBody,
                          device: dict = Depends(authenticate)):
        from src.init.nova.tools import complete_reminder as complete
        return _checked(complete(reminder_id, body.completed))

    @app.get("/v1/nova/journal")
    def journal(first_day: str | None = None, last_day: str | None = None,
                query: str | None = None, limit: int = 20,
                device: dict = Depends(authenticate)):
        from src.init.nova.tools import read_journal
        return _checked(read_journal(first_day, last_day, query, limit))

    @app.get("/v1/nova/search")
    def search(query: str = Query(min_length=1, max_length=200), limit: int = 20,
               device: dict = Depends(authenticate)):
        from src.init.nova.tools import read_journal, search_agenda
        agenda = _checked(search_agenda(query, limit))
        journal = _checked(read_journal(query=query, limit=limit))
        return {"query": query, "agenda": agenda["entries"], "journal": journal["entries"]}

    return PrivateNetworkOnly(app)


class ApiServer:
    """Runs the API on its own thread inside the assistant's process."""

    def __init__(self, settings: dict):
        self.settings = settings
        self.manager = SessionManager(settings["allow_remote_confirmation"])
        self.devices = DeviceStore()
        self.pairing = PairingCodes()
        self.server = None
        self.thread = None

    def start(self):
        app = create_app(self.manager, self.devices, self.pairing, self.settings)
        settings = self.settings
        config = uvicorn.Config(
            app, host=settings["host"], port=settings["port"], log_config=None,
            log_level="warning", lifespan="off",
            ssl_certfile=settings["tls_certificate"] or None,
            ssl_keyfile=settings["tls_key"] or None)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self._run, name="api-server", daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self.server.run()
        except (Exception, SystemExit):
            log.exception("The API server stopped")
        if not self.server.started:
            log.error("The API server could not listen on %s:%s",
                      self.settings["host"], self.settings["port"])

    def stop(self):
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(5)
        self.manager.close_all()
