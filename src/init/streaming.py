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

class Phrase(str):
    """A phrase for speech, marked when it is read verbatim rather than spoken."""
    verbatim = False


class VerbatimTracker:
    """Follow quotations, blockquotes and code in streamed text."""

    OPENING = "“«"
    CLOSING = "”»"

    def __init__(self):
        self.fence = False
        self.inline = False
        self.blockquote = False
        self.quote = False
        self.line_start = True
        self.newlines = 0
        self.ticks = 0

    def _finish_ticks(self):
        if self.ticks >= 3 and self.line_start:
            self.fence = not self.fence
        elif self.ticks and not self.fence:
            self.inline = not self.inline
        if self.ticks:
            self.line_start = False
        self.ticks = 0

    @property
    def active(self):
        return self.fence or self.inline or self.blockquote or self.quote

    def split(self, text):
        segments = []
        current = []
        state = self.active
        for character in text:
            if character == "`":
                self.ticks += 1
            else:
                self._finish_ticks()
                if character == "\n":
                    self.newlines += 1
                    if self.newlines >= 2:
                        self.quote = False
                    self.blockquote = False
                    self.inline = False
                    self.line_start = True
                else:
                    self.newlines = 0
                    if character == ">" and self.line_start:
                        self.blockquote = True
                    if character in self.OPENING:
                        self.quote = True
                    elif character in self.CLOSING:
                        self.quote = False
                    elif character == '"':
                        self.quote = not self.quote
                    if not character.isspace():
                        self.line_start = False
            if self.active != state and current:
                segments.append(("".join(current), state))
                current = []
            state = self.active
            current.append(character)
        if current:
            segments.append(("".join(current), state))
        return segments


class SpeechBuffer:
    def __init__(self, *, low_latency=False, fast_first=False):
        self.buffer = ""
        self.first = True
        self.markdown = MarkdownSpeechFilter()
        self.tracker = VerbatimTracker()
        self.verbatim = False
        self.low_latency = low_latency
        self.fast_first = fast_first

    def feed(self, text):
        phrases = []
        for segment, verbatim in self.tracker.split(text):
            spoken = self.markdown.feed(segment)
            if spoken.strip() and verbatim:
                self.verbatim = True
            self.buffer += spoken
            phrases.extend(self.extract(verbatim))
        return phrases

    def extract(self, verbatim):
        phrases = []
        while self.buffer:
            fast = self.low_latency or (self.fast_first and self.first)
            pattern = (r'(?<=[.!?])["»”’]?\s+' if self.first
                       else r'(?<=[.!?;:])["»”’]?\s+')
            minimum = (12 if self.fast_first and not self.low_latency else 8) if fast else 20
            if fast:
                pattern = r'(?<=[.!?;:,])["»”’]?\s+|\n+'
            match = next((m for m in re.finditer(pattern, self.buffer)
                          if m.end() >= minimum), None)
            end = match.end() if match else -1
            if end <= 0 and fast and len(self.buffer) >= 160:
                end = self.buffer.rfind(" ", 80, 160)
            if end <= 0:
                break
            text = self.buffer[:end].strip()
            self.buffer = self.buffer[end:].lstrip()
            if text:
                phrase = Phrase(text)
                phrase.verbatim = self.verbatim
                phrases.append(phrase)
                self.first = False
            self.verbatim = verbatim and bool(self.buffer)
        return phrases

    def finish(self):
        self.buffer += self.markdown.feed("", final=True)
        remaining = self.buffer.strip()
        self.buffer = ""
        if not remaining:
            return []
        phrase = Phrase(remaining)
        phrase.verbatim = self.verbatim
        self.verbatim = False
        return [phrase]


def prefers_response_workspace(text):
    """Return whether a final answer is long enough to read in a response workspace."""
    return (len(text) >= 1200
            or text.count("\n") >= 25
            or len(re.findall(r"^\s*```", text, re.MULTILINE)) >= 4)


class ResponseDelivery:
    """Deliver visible text and speech to the selected response surface."""

    def __init__(self, emit_chunk, enqueue_speech, *, speech_enabled=True, on_surface=None):
        self.emit_chunk = emit_chunk
        self.enqueue_speech = enqueue_speech
        self.speech_enabled = speech_enabled
        self.on_surface = on_surface
        self.buffer = SpeechBuffer(fast_first=True)
        self.delivered_output = None

    def emit(self, chunk):
        if not chunk:
            return
        self.emit_chunk(chunk)
        if self.speech_enabled:
            for phrase in self.buffer.feed(chunk):
                self.enqueue_speech(phrase)

    def flush_speech(self, cancel_event=None):
        if self.speech_enabled:
            for phrase in self.buffer.finish():
                if cancel_event is None or not cancel_event.is_set():
                    self.enqueue_speech(phrase)

    def deliver(self, output, *, streamed="", surface="auto", title="", searched=""):
        if self.delivered_output == output:
            return
        if surface == "auto":
            surface = ("response_view" if searched or prefers_response_workspace(output)
                       else "chat")
        if surface == "response_view":
            title = title or searched
        if self.on_surface is not None:
            allow_speech = self.on_surface(surface, title)
            self.speech_enabled = self.speech_enabled and allow_speech
        self.emit(output[len(streamed):] if output.startswith(streamed) else output)
        self.flush_speech()
        self.delivered_output = output
