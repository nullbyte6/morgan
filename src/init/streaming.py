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


class MarkdownSpeechFilter:
    """Remove Markdown code while retaining streaming-safe prose."""

    def __init__(self):
        self.pending = ""
        self.fence = None
        self.inline_ticks = 0
        self.line_start = True

    def feed(self, text, *, final=False):
        self.pending += text
        spoken = []
        index = 0
        while index < len(self.pending):
            if self.fence is not None:
                newline = self.pending.find("\n", index)
                if newline < 0:
                    break
                line = self.pending[index:newline]
                marker = re.match(r"^ {0,3}([`~]+)\s*$", line)
                if (marker and marker.group(1)[0] == self.fence[0]
                        and len(marker.group(1)) >= len(self.fence)):
                    self.fence = None
                index = newline + 1
                self.line_start = True
                continue

            if self.line_start and self.inline_ticks == 0:
                newline = self.pending.find("\n", index)
                available = self.pending[index:] if newline < 0 else self.pending[index:newline]
                marker = re.match(r"^ {0,3}([`~]+)", available)
                if marker:
                    token = marker.group(1)
                    if len(token) >= 3:
                        self.fence = token
                        if newline < 0:
                            index = len(self.pending)
                            break
                        index = newline + 1
                        self.line_start = True
                        continue
                    if newline < 0 and not final and marker.end() == len(available):
                        break
                if (available.startswith("    ") or available.startswith("\t")):
                    if newline < 0:
                        if final:
                            index = len(self.pending)
                        break
                    index = newline + 1
                    self.line_start = True
                    continue
                self.line_start = False

            char = self.pending[index]
            if char == "`":
                end = index
                while end < len(self.pending) and self.pending[end] == "`":
                    end += 1
                count = end - index
                if end == len(self.pending) and not final:
                    break
                if self.inline_ticks == 0:
                    self.inline_ticks = count
                elif count == self.inline_ticks:
                    self.inline_ticks = 0
                index = end
                continue
            if char == "\n":
                if self.inline_ticks == 0:
                    spoken.append(char)
                self.line_start = True
            elif self.inline_ticks == 0:
                spoken.append(char)
            index += 1

        self.pending = self.pending[index:]
        if final:
            self.pending = ""
        return "".join(spoken)


class SpeechBuffer:
    FIRST_PHRASE_MIN = 24
    FIRST_PHRASE_LIMIT = 40

    def __init__(self):
        self.buffer = ""
        self.first = True
        self.markdown = MarkdownSpeechFilter()

    def feed(self, text):
        self.buffer += self.markdown.feed(text)
        phrases = []
        while self.buffer:
            pattern = (r'(?<=[,.!?;:])["»”’]?\s+' if self.first
                       else r'(?<=[.!?;:])["»”’]?\s+')
            match = next((m for m in re.finditer(pattern, self.buffer)
                          if m.end() >= 20), None)
            end = match.end() if match else -1
            if (end == -1 and self.first
                    and len(self.buffer) >= self.FIRST_PHRASE_LIMIT):
                end = self.buffer.rfind(
                    " ", self.FIRST_PHRASE_MIN, self.FIRST_PHRASE_LIMIT)
            if end <= 0:
                break
            phrase = self.buffer[:end].strip()
            self.buffer = self.buffer[end:].lstrip()
            if phrase:
                phrases.append(phrase)
                self.first = False
        return phrases

    def finish(self):
        self.buffer += self.markdown.feed("", final=True)
        remaining = self.buffer.strip()
        self.buffer = ""
        return [remaining] if remaining else []
