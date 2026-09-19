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
