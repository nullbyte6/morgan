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
"""Shared interface translations. Conversation language remains independent."""

import json
from functools import lru_cache
from pathlib import Path

LOCALES = Path(__file__).with_name("locales")
LANGUAGES = {"english": "en", "spanish": "es", "chinese": "ch", "french": "fr", "german": "de",
             "portuguese": "pt", "japanese": "ja", "russian": "ru", "korean": "ko", "italian": "it"}
SPEECH_LANGUAGES = {"english": "en", "spanish": "es", "chinese": "zh", "french": "fr", "german": "de",
                    "portuguese": "pt", "japanese": "ja", "russian": "ru", "korean": "ko", "italian": "it"}
LANGUAGE_NAMES = {"english": "English", "spanish": "European Spanish", "chinese": "Simplified Chinese",
                  "french": "French", "german": "German", "portuguese": "Brazilian Portuguese",
                  "japanese": "Japanese", "russian": "Russian", "korean": "Korean", "italian": "Italian"}


@lru_cache(maxsize=1)
def _language_detector():
    from lingua import IsoCode639_1, LanguageDetectorBuilder
    return (LanguageDetectorBuilder.from_iso_codes_639_1(
        *(getattr(IsoCode639_1, code.upper()) for code in SPEECH_LANGUAGES.values()))
        .with_minimum_relative_distance(0.1).build())


def detect_language(text: str) -> str | None:
    """Return the interface language a text is written in, or None when it is unclear."""
    language = _language_detector().detect_language_of(text)
    if language is None:
        return None
    code = language.iso_code_639_1.name.lower()
    return next((key for key, value in SPEECH_LANGUAGES.items() if value == code), None)


def get_language() -> str:
    from . import config
    fallback = config._last_valid.get("lang", "spanish")
    try:
        settings = json.loads(config.CONFIG_FILE.read_text(encoding="utf-8-sig"))
        language = settings.get("lang", fallback)
        return language if language in LANGUAGES else fallback
    except (OSError, ValueError, AttributeError, TypeError):
        return fallback


def set_language(language: str) -> None:
    from .config import load_config, save_config
    if language not in LANGUAGES:
        raise ValueError(tr('lang.unsupported_interface_language', language=language))
    config = load_config()
    config["lang"] = language
    save_config(config)


@lru_cache(maxsize=len(LANGUAGES))
def catalog(language: str) -> dict[str, str]:
    return json.loads((LOCALES / f"lang_{LANGUAGES[language]}.json").read_text(
        encoding="utf-8"))


def tr(key: str, /, **values) -> str:
    """Resolve a stable key against the active global language on every call."""
    language = get_language()
    template = catalog(language).get(key)
    if template is None:
        template = catalog("english")[key]
    if "{assistant_name}" in template and "assistant_name" not in values:
        from .identity import get_assistant_name
        values["assistant_name"] = get_assistant_name()
    return template.format(**values) if values else template
