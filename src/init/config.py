"""User configuration and storage, independent of the working directory."""

import json
import os
import tempfile
import warnings
from copy import deepcopy
from pathlib import Path

HOME_PATH = Path.home() / ".nora"
CONFIG_FILE = HOME_PATH / "json" / "config.json"
LEGACY_CONFIG = Path(__file__).resolve().parents[2] / "config.json"
DEFAULTS = {
    "version": "1.0.7-alpha",
    "model_name": "qwen3:14b",
    "keep_alive": "30m",
    "temperature": 0.2,
    "personality": {
        "tone": "friendly",
        "verbosity": "short",
        "humor": "light",
        "formality": "informal",
        "instructions": "",
    },
}
_last_valid = deepcopy(DEFAULTS)
_last_error = None


def ensure_storage():
    """Classify legacy user files, preserving both files on name collisions."""
    folders = {".txt": "note", ".md": ".log", ".json": "json"}
    for folder in folders.values():
        (HOME_PATH / folder).mkdir(parents=True, exist_ok=True)
    for source in HOME_PATH.iterdir():
        folder = folders.get(source.suffix.lower())
        if folder and source.is_file() and not source.is_symlink():
            target = HOME_PATH / folder / source.name
            if not target.exists():
                source.rename(target)


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError("config.json must contain a JSON object")
    result = deepcopy(DEFAULTS)
    result.update(config)
    for key in ("version", "model_name", "keep_alive"):
        if not isinstance(result[key], str) or not result[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    temperature = result["temperature"]
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
        raise ValueError("temperature must be a number between 0 and 2")
    personality = config.get("personality", {})
    if not isinstance(personality, dict):
        raise ValueError("personality must be an object")
    result["personality"] = {**DEFAULTS["personality"], **personality}
    for key, value in result["personality"].items():
        if not isinstance(value, str):
            raise ValueError(f"personality.{key} must be text")
    return result


def save_config(config):
    config = validate_config(config)
    ensure_storage()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CONFIG_FILE.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(config, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary, CONFIG_FILE)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_config():
    """Read fresh settings; retain the last valid settings during invalid edits."""
    global _last_valid, _last_error
    try:
        ensure_storage()
        if not CONFIG_FILE.exists():
            initial = json.loads(LEGACY_CONFIG.read_text(encoding="utf-8-sig")) if LEGACY_CONFIG.exists() else DEFAULTS
            save_config(initial)
        _last_valid = validate_config(json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig")))
        _last_error = None
    except (OSError, ValueError) as error:
        if str(error) != _last_error:
            warnings.warn(f"Nora config: {error}; keeping last valid settings", RuntimeWarning)
            _last_error = str(error)
    return deepcopy(_last_valid)
