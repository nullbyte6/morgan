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
    """Remove Markdown syntax while retaining streaming-safe prose."""

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
                    if final:
                        index = len(self.pending)
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
                if newline < 0 and not final:
                    prefix = self.pending[index:]
                    if (not prefix.strip() or prefix.lstrip().startswith("|")
                            or re.match(r"^ {0,3}[`~]", prefix)
                            or prefix.startswith("    ") or prefix.startswith("\t")):
                        break

                available = (
                    self.pending[index:]
                    if newline < 0
                    else self.pending[index:newline])

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

                if (available.startswith("    ")
                    or available.startswith("\t")):
                    if newline < 0:
                        if final:
                            index = len(self.pending)
                        break

                    index = newline + 1
                    self.line_start = True
                    continue

                if self._is_table_separator(available):
                    index = (len(self.pending)
                        if newline < 0
                        else newline + 1)

                    self.line_start = True
                    continue

                if self._is_table_row(available):
                    row = self._speak_table_row(available)

                    if row:
                        spoken.append(row)

                    index = (len(self.pending)
                        if newline < 0
                        else newline + 1)

                    self.line_start = True
                    continue

                self.line_start = False

            char = self.pending[index]

            if char == "`":
                end = index

                while (end < len(self.pending)
                    and self.pending[end] == "`"):
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
                spoken.append(char)
                self.line_start = True
            else:
                spoken.append(char)

            index += 1

        self.pending = self.pending[index:]

        if final:
            self.pending = ""

        return "".join(spoken)

    @staticmethod
    def _is_table_separator(line: str) -> bool:
        stripped = line.strip()

        if not stripped.startswith("|") or not stripped.endswith("|"):
            return False

        cells = [
            cell.strip()
            for cell in stripped.strip("|").split("|")
        ]

        return bool(cells) and all(
            re.fullmatch(r":?-{3,}:?", cell)
            for cell in cells
        )

    @staticmethod
    def _is_table_row(line: str) -> bool:
        stripped = line.strip()

        return (
            stripped.startswith("|")
            and stripped.endswith("|")
            and stripped.count("|") >= 3
        )

    @staticmethod
    def _speak_table_row(line: str) -> str:
        cells = [
            cell.strip()
            for cell in line.strip().strip("|").split("|")
            if cell.strip()
        ]

        return ". ".join(cells) + ".\n" if cells else ""

class SpeechBuffer:
    def __init__(self, *, low_latency=False):
        self.buffer = ""
        self.first = True
        self.markdown = MarkdownSpeechFilter()
        self.low_latency = low_latency

    def feed(self, text):
        self.buffer += self.markdown.feed(text)
        phrases = []
        while self.buffer:
            pattern = (r'(?<=[.!?])["»”’]?\s+' if self.first
                       else r'(?<=[.!?;:])["»”’]?\s+')
            minimum = 8 if self.low_latency else 20
            if self.low_latency:
                pattern = r'(?<=[.!?;:,])["»”’]?\s+|\n+'
            match = next((m for m in re.finditer(pattern, self.buffer)
                          if m.end() >= minimum), None)
            end = match.end() if match else -1
            if end <= 0 and self.low_latency and len(self.buffer) >= 160:
                end = self.buffer.rfind(" ", 80, 160)
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
