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
"""Phrase buffering shared by terminal and cancellable desktop streaming."""

import re


class SpeechBuffer:
    def __init__(self):
        self.buffer = ""
        self.first = True

    def feed(self, text):
        self.buffer += text
        phrases = []
        while self.buffer:
            pattern = (r'(?<=[,.!?;:])["»”’]?\s+' if self.first
                       else r'(?<=[.!?;:])["»”’]?\s+')
            match = next((m for m in re.finditer(pattern, self.buffer)
                          if m.end() >= 20), None)
            end = match.end() if match else -1
            if end == -1 and self.first and len(self.buffer) >= 60:
                end = self.buffer.rfind(" ", 30, 60)
            if end <= 0:
                break
            phrase = self.buffer[:end].strip()
            self.buffer = self.buffer[end:].lstrip()
            if phrase:
                phrases.append(phrase)
                self.first = False
        return phrases

    def finish(self):
        remaining = self.buffer.strip()
        self.buffer = ""
        return [remaining] if remaining else []
