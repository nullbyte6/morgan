"""Minimal bootstrap instructions; configurable behavior belongs in config.json."""

from .identity import get_assistant


INSTRUCTIONS = (
    "You are {assistant_name}, a personal desktop assistant. "
    "Follow the current configuration, use tools carefully, and only report "
    "results supported by the available evidence. "
)


def current_instructions() -> str:
    """Build the live prompt from the latest valid user configuration."""
    from .config import load_config

    config = load_config()
    personality = config["personality"]
    instructions = config["instructions"]
    sections = "\n".join(
        f"{key}: {value}" for key, value in instructions.items() if value
    )
    style = "\n".join(
        f"{key}: {value}" for key, value in personality.items() if value
    )
    return (
        INSTRUCTIONS.replace("{assistant_name}", get_assistant().name)
        + "\nCurrent instructions (apply to this response):\n" + sections
        + "\nCurrent personality (apply to this response):\n" + style
    )
