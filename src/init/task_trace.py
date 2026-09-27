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
"""Incremental task journals with content-addressed payloads and deterministic replay."""

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _changes(previous, current, path=()):
    if isinstance(previous, dict) and isinstance(current, dict):
        for key in previous.keys() - current.keys():
            yield {"op": "remove", "path": [*path, key]}
        for key, value in current.items():
            if key not in previous:
                yield {"op": "set", "path": [*path, key], "value": value}
            else:
                yield from _changes(previous[key], value, (*path, key))
    elif previous != current:
        if isinstance(previous, list) and isinstance(current, list) and current[:len(previous)] == previous:
            yield {"op": "append", "path": list(path), "value": current[len(previous):]}
        else:
            yield {"op": "set", "path": list(path), "value": current}


class TaskJournal:
    def __init__(self, path, state):
        self.path = Path(path)
        self.state = state
        self.previous = {}
        self.event_sequence = 0

    def _payload(self, value):
        def default(item):
            return item.model_dump(mode="json") if hasattr(item, "model_dump") else str(item)
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=default).encode("utf-8")
        if len(raw) <= 8192:
            return json.loads(raw)
        value = json.loads(raw)
        if isinstance(value, dict):
            value = {key: self._payload(child) for key, child in value.items()}
        elif isinstance(value, list):
            value = [self._payload(child) for child in value]
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(raw) <= 8192:
            return value
        digest = hashlib.sha256(raw).hexdigest()
        target = self.path.parent / ("payload-" + digest + ".json")
        if not target.exists():
            target.write_bytes(raw)
        return {"journal_blob_sha256": digest, "bytes": len(raw)}

    def record(self, event, **details):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = self.state.snapshot(include_evidence=False)
        delta = list(_changes(self.previous, snapshot))
        entry = {"version": 2, "task_id": self.state.id, "event_sequence": self.event_sequence + 1,
                 "time": datetime.now(timezone.utc).isoformat(), "event": event,
                 "state_delta": [self._payload(operation) for operation in delta],
                 **{key: self._payload(value) for key, value in details.items()}}
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        self.previous = copy.deepcopy(snapshot)
        self.event_sequence += 1


def replay_trace(path):
    path = Path(path)
    state = {}
    evidence = {}

    def payload(value):
        if isinstance(value, dict) and set(value) == {"journal_blob_sha256", "bytes"}:
            digest = value["journal_blob_sha256"]
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Invalid journal payload hash")
            raw = (path.parent / ("payload-" + digest + ".json")).read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("Journal payload hash mismatch")
            return payload(json.loads(raw))
        if isinstance(value, dict):
            return {key: payload(child) for key, child in value.items()}
        if isinstance(value, list):
            return [payload(child) for child in value]
        return value

    with path.open(encoding="utf-8") as stream:
        for sequence, line in enumerate(stream, 1):
            event = json.loads(line)
            if event.get("version") != 2 or event["event_sequence"] != sequence:
                raise ValueError("Unsupported or discontinuous task journal")
            for encoded in event["state_delta"]:
                operation = payload(encoded)
                target = state
                for key in operation["path"][:-1]:
                    target = target[key]
                key = operation["path"][-1]
                if operation["op"] == "remove":
                    del target[key]
                elif operation["op"] == "append":
                    target[key].extend(operation["value"])
                else:
                    target[key] = operation["value"]
            if event["event"] == "observation":
                item = payload(event["evidence"])
                evidence[item["id"]] = item
    return {"state": state, "evidence": evidence}
