"""Shared interface translations. Conversation language remains independent."""

import json
from functools import lru_cache
from pathlib import Path

from .config import load_config, save_config

LOCALES = Path(__file__).with_name("locales")
LANGUAGES = {"english": "en", "spanish": "es"}


def get_language() -> str:
    return load_config()["lang"]


def set_language(language: str) -> None:
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported interface language: {language}")
    config = load_config()
    config["lang"] = language
    save_config(config)


@lru_cache(maxsize=2)
def catalog(language: str) -> dict[str, str]:
    return json.loads((LOCALES / f"lang_{LANGUAGES[language]}.json").read_text(
        encoding="utf-8"))


def tr(key: str, **values) -> str:
    """Resolve a stable key against the active global language on every call."""
    language = get_language()
    template = catalog(language).get(key)
    if template is None:
        template = catalog("english")[key]
    return template.format(**values) if values else template
