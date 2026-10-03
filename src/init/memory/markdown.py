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

import re
from datetime import datetime, timezone
from pathlib import Path

STAMP = re.compile(r"^\[(\d{2}:\d{2}:\d{2} [+-]\d{4})\][ \t]*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def read_log(path, *, role_map, include_tail=False):
    path = Path(path).expanduser()
    result = {"path": str(path.resolve()), "error": None, "warnings": [], "sealed_size": 0}
    if path.is_symlink():
        return {**result, "error": "Symbolic links are not imported"}
    try:
        day = datetime.strptime(path.name, "%Y-%m-%d.md").date()
        if path.stat().st_size > 16 * 1024 * 1024:
            return {**result, "error": "Log exceeds the 16 MiB import limit"}
        data = path.read_bytes()
        text = data.decode("utf-8-sig")
    except (OSError, UnicodeError, ValueError) as error:
        return {**result, "error": str(error)}
    lines = text.splitlines(keepends=True)
    if not lines or not re.fullmatch(r".+ Log — " + re.escape(day.isoformat()), lines[0].strip()):
        return {**result, "error": "Unrecognized daily log header"}
    mapping = {name.casefold(): role for name, role in role_map.items()}
    if any(role not in ("user", "assistant", "system") for role in mapping.values()):
        raise ValueError("Role mapping must use user, assistant or system")
    boundaries = []
    offsets = []
    offset = 3 if data.startswith(b"\xef\xbb\xbf") else 0
    fence = None
    for index, line in enumerate(lines):
        offsets.append(offset)
        offset += len(line.encode("utf-8"))
        stripped = line.rstrip("\r\n")
        body = stripped
        if boundaries and index == boundaries[-1] + 1:
            speaker_line = re.match(r"^[^:\r\n]{1,100}: (.*)", stripped)
            if speaker_line:
                body = speaker_line[1]
        marker = FENCE.match(body)
        if marker:
            token, info = marker.groups()
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not info.strip():
                fence = None
            continue
        if (fence is None and index > 0 and not lines[index - 1].strip()
                and (STAMP.fullmatch(stripped) or re.match(r"^\[\d{2}:\d{2}:", stripped))):
            boundaries.append(index)
    entries = []
    for number, start in enumerate(boundaries):
        tail = number == len(boundaries) - 1
        if tail and (not include_tail or fence is not None):
            result["warnings"].append(f"Unsealed final entry at byte {offsets[start]} was deferred")
            break
        end = len(lines) if tail else boundaries[number + 1]
        stamp = STAMP.fullmatch(lines[start].rstrip("\r\n"))
        speaker = re.match(r"^([^:\r\n]{1,100}): (.*)", lines[start + 1], re.DOTALL) if start + 1 < end else None
        if stamp is None or speaker is None or speaker[1].casefold() not in mapping:
            result["warnings"].append(f"Invalid timestamp or unmapped speaker at byte {offsets[start]}")
            continue
        try:
            created = datetime.strptime(f"{day} {stamp[1]}", "%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            result["warnings"].append(f"Invalid timestamp at byte {offsets[start]}")
            continue
        content = (speaker[2] + "".join(lines[start + 2:end])).rstrip("\r\n")
        if not content.strip():
            result["warnings"].append(f"Empty entry at byte {offsets[start]}")
            continue
        entries.append({"offset": offsets[start], "role": mapping[speaker[1].casefold()],
                        "content": content, "created_at": created.astimezone(timezone.utc).isoformat(timespec="microseconds")})
    if boundaries:
        result["sealed_size"] = len(data) if include_tail and fence is None else offsets[boundaries[-1]]
    result.update(data=data, entries=entries)
    return result
