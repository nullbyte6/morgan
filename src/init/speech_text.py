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
import re
from functools import lru_cache

from babel import UnknownLocaleError
from babel.numbers import NumberFormatError, parse_decimal
from lingua import LanguageDetectorBuilder
from num2words import num2words


@lru_cache(maxsize=1)
def speech_language_detector():
    return (LanguageDetectorBuilder.from_all_languages()
            .with_minimum_relative_distance(0.1).build())


class SpeechNumbers:
    """Keep the response language stable for synthesis and numeric spans."""

    def __init__(self, context=""):
        self.context = context
        self.response = ""
        self.language = None

    def observe(self, text):
        self.response += " " + text
        if self.language is None:
            detector = speech_language_detector()
            self.language = (detector.detect_language_of(self.response)
                             or detector.detect_language_of(self.context))

    def normalize(self, text):
        if self.language is None:
            return text
        code = self.language.iso_code_639_1.name.lower()

        def cardinal(value):
            try:
                return num2words(value, lang=code)
            except (NotImplementedError, OverflowError, ValueError):
                return str(value)

        def replace(match):
            original = match.group()
            try:
                number = parse_decimal(original, locale=code, strict=True)
            except (NumberFormatError, UnknownLocaleError):
                spoken = re.sub(r"\d+", lambda part: cardinal(int(part.group())), original)
            else:
                spoken = cardinal(number)
                if spoken == str(number):
                    return original
            if match.start() and text[match.start() - 1].isalnum():
                spoken = " " + spoken
            if match.end() < len(text) and text[match.end()].isalpha():
                spoken += " "
            return spoken

        return re.sub(r"(?<!\w)-\d+(?:[.,]\d+)*|\d+(?:[.,]\d+)*", replace, text)


LETTER_NAMES = {
    "a": "a", "b": "be", "c": "ce", "d": "de", "e": "e",
    "f": "efe", "g": "ge", "h": "hache", "i": "i", "j": "jota",
    "k": "ka", "l": "ele", "m": "eme", "n": "ene", "ñ": "eñe",
    "o": "o", "p": "pe", "q": "cu", "r": "erre", "s": "ese",
    "t": "te", "u": "u", "v": "uve", "w": "doble uve", "x": "equis",
    "y": "i griega", "z": "zeta",
}

INITIALISMS = {
    "ai", "api", "cli", "cpu", "css", "csv", "dll", "dns", "exe",
    "gpu", "gui", "html", "http", "https", "id", "ip", "js", "jsx",
    "pdf", "py", "ram", "sdk", "sql", "src", "ssh", "ssl", "svg",
    "ts", "tsx", "tsv", "txt", "ui", "uri", "url", "usr", "ux", "xml",
}

PATH_PATTERN = re.compile(
    r"(?<![\w:/])(?:[A-Za-z]:[\\/]|[.~]?[\\/])?"
    r"(?:[\w.@+-]+[\\/])+[\w@+.-]*[\w@+]",
    re.UNICODE,
)


def spell_letters(value):
    return " ".join(LETTER_NAMES.get(letter.casefold(), letter) for letter in value)


def speak_component(value):
    value = value.strip("._- ")
    if not value:
        return ""
    pieces = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+|\d+", value)
    spoken = []
    for piece in pieces:
        lowered = piece.casefold()
        letters = piece.isalpha()
        no_vowels = letters and not re.search(r"[aeiouáéíóúü]", lowered)
        uppercase_initialism = letters and piece.isupper() and len(piece) <= 5
        if letters and (len(piece) == 1 or lowered in INITIALISMS
                        or no_vowels or uppercase_initialism):
            spoken.append(spell_letters(piece))
        else:
            spoken.append(piece)
    return " ".join(spoken)


def speak_path(path):
    segments = [segment for segment in re.split(r"[\\/]+", path) if segment]
    spoken = []
    for index, segment in enumerate(segments):
        if segment.endswith(":"):
            segment = segment[:-1]
        if index == len(segments) - 1 and "." in segment.lstrip("."):
            parts = [part for part in segment.split(".") if part]
            values = [speak_component(part) for part in parts]
            values = [value for value in values if value]
            if values:
                spoken.append(" punto ".join(values))
        else:
            value = speak_component(segment)
            if value:
                spoken.append(value)
    return ", ".join(spoken)


def replace_path(match):
    path = match.group()
    segments = [segment for segment in re.split(r"[\\/]+", path) if segment]
    final = segments[-1] if segments else ""
    path_like = ("\\" in path or path.startswith(("/", "./", "../"))
                 or re.match(r"^[A-Za-z]:[\\/]", path)
                 or path.count("/") >= 2 or "." in final
                 or any(segment.casefold() in INITIALISMS for segment in segments))
    return speak_path(path) if path_like else path


def apply_pronunciations(text, pronunciations):
    for word, pronunciation in sorted(
            pronunciations.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.escape(word)
        if word[0].isalnum():
            pattern = r"(?<!\w)" + pattern
        if word[-1].isalnum():
            pattern += r"(?!\w)"
        text = re.sub(pattern, lambda _: pronunciation, text, flags=re.IGNORECASE)
    return text


def prepare_speech(text, pronunciations=None):
    text = PATH_PATTERN.sub(replace_path, text)
    text = apply_pronunciations(text, pronunciations or {})
    return re.sub(r"\s+", " ", text).strip()
