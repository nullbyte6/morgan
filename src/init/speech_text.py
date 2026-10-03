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
import string
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

    @property
    def code(self):
        return self.language.iso_code_639_1.name.lower() if self.language else None

    def normalize(self, text):
        if self.language is None:
            return text
        code = self.code

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


def _letters(*names, **extra):
    return {**dict(zip(string.ascii_lowercase, names)), **extra}


LETTER_NAMES = {
    "en": _letters("ay", "bee", "see", "dee", "ee", "eff", "gee", "aitch", "eye", "jay", "kay", "el", "em",
                   "en", "oh", "pee", "cue", "ar", "ess", "tee", "you", "vee", "double you", "ex", "why", "zee"),
    "es": _letters("a", "be", "ce", "de", "e", "efe", "ge", "hache", "i", "jota", "ka", "ele", "eme", "ene",
                   "o", "pe", "cu", "erre", "ese", "te", "u", "uve", "doble uve", "equis", "i griega", "zeta",
                   ñ="eñe"),
    "zh": _letters("诶", "比", "西", "迪", "伊", "艾弗", "吉", "艾尺", "艾", "杰", "开", "艾勒", "艾马", "艾娜",
                   "欧", "屁", "吉吾", "艾儿", "艾丝", "提", "优", "维", "达布溜", "艾克斯", "吾艾", "贼德"),
    "fr": _letters("a", "bé", "cé", "dé", "e", "effe", "gé", "ache", "i", "ji", "ka", "elle", "emme", "enne",
                   "o", "pé", "ku", "erre", "esse", "té", "u", "vé", "double vé", "iks", "i grec", "zède"),
    "de": _letters("a", "be", "ze", "de", "e", "ef", "ge", "ha", "i", "jot", "ka", "el", "em", "en", "o", "pe",
                   "ku", "er", "es", "te", "u", "fau", "we", "iks", "ypsilon", "zet"),
    "pt": _letters("a", "bê", "cê", "dê", "e", "éfe", "gê", "agá", "i", "jota", "cá", "éle", "ême", "ene", "o",
                   "pê", "quê", "érre", "ésse", "tê", "u", "vê", "dáblio", "xis", "ípsilon", "zê"),
    "it": _letters("a", "bi", "ci", "di", "e", "effe", "gi", "acca", "i", "i lunga", "cappa", "elle", "emme",
                   "enne", "o", "pi", "cu", "erre", "esse", "ti", "u", "vu", "doppia vu", "ics", "ipsilon",
                   "zeta"),
    "ru": _letters("а", "би", "си", "ди", "и", "эф", "джи", "эйч", "ай", "джей", "кей", "эл", "эм", "эн", "оу",
                   "пи", "кью", "ар", "эс", "ти", "ю", "ви", "дабл-ю", "экс", "уай", "зед"),
    "ja": _letters("エー", "ビー", "シー", "ディー", "イー", "エフ", "ジー", "エイチ", "アイ", "ジェー", "ケー", "エル",
                   "エム", "エヌ", "オー", "ピー", "キュー", "アール", "エス", "ティー", "ユー", "ブイ", "ダブリュー",
                   "エックス", "ワイ", "ゼット"),
    "ko": _letters("에이", "비", "씨", "디", "이", "에프", "지", "에이치", "아이", "제이", "케이", "엘", "엠", "엔",
                   "오", "피", "큐", "알", "에스", "티", "유", "브이", "더블유", "엑스", "와이", "제트"),
}

DOT_WORDS = {"en": "dot", "es": "punto", "zh": "点", "fr": "point", "de": "Punkt", "pt": "ponto", "it": "punto",
             "ru": "точка", "ja": "ドット", "ko": "점"}

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


LATIN_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def spell_letters(value, language=None):
    names = LETTER_NAMES.get(language, LETTER_NAMES["en"])
    return " ".join(names.get(letter.casefold(), letter) for letter in value)


def speak_component(value, language=None):
    value = value.strip("._- ")
    if not value:
        return ""
    pieces = re.findall(r"[^\W\d_]+|\d+", value)
    spoken = []
    for piece in pieces:
        lowered = piece.casefold()
        letters = LATIN_WORD.fullmatch(piece) is not None
        no_vowels = letters and not re.search(r"[aeiouáéíóúüàèìòùâêîôûäöãõ]", lowered)
        uppercase_initialism = letters and piece.isupper() and len(piece) <= 5
        if letters and (len(piece) == 1 or lowered in INITIALISMS
                        or no_vowels or uppercase_initialism):
            spoken.append(spell_letters(piece, language))
        else:
            spoken.append(piece)
    return " ".join(spoken)


def speak_path(path, language=None):
    segments = [segment for segment in re.split(r"[\\/]+", path) if segment]
    spoken = []
    for index, segment in enumerate(segments):
        if segment.endswith(":"):
            segment = segment[:-1]
        if index == len(segments) - 1 and "." in segment.lstrip("."):
            parts = [part for part in segment.split(".") if part]
            values = [speak_component(part, language) for part in parts]
            values = [value for value in values if value]
            if values:
                spoken.append(f" {DOT_WORDS.get(language, DOT_WORDS['en'])} ".join(values))
        else:
            value = speak_component(segment, language)
            if value:
                spoken.append(value)
    return ", ".join(spoken)


def replace_path(match, language=None):
    path = match.group()
    segments = [segment for segment in re.split(r"[\\/]+", path) if segment]
    final = segments[-1] if segments else ""
    path_like = ("\\" in path or path.startswith(("/", "./", "../"))
                 or re.match(r"^[A-Za-z]:[\\/]", path)
                 or path.count("/") >= 2 or "." in final
                 or any(segment.casefold() in INITIALISMS for segment in segments))
    return speak_path(path, language) if path_like else path


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


def prepare_speech(text, pronunciations=None, language=None):
    text = PATH_PATTERN.sub(lambda match: replace_path(match, language), text)
    text = apply_pronunciations(text, pronunciations or {})
    return re.sub(r"\s+", " ", text).strip()
