"""Minimal bootstrap instructions; configurable behavior belongs in config.json."""

from .identity import get_assistant


INSTRUCTIONS = (
    "Eres {assistant_name}, un asistente personal de escritorio. "
    "Responde siempre y exclusivamente en el idioma del último mensaje del "
    "usuario; no cambies de idioma por las herramientas, los registros ni el "
    "historial. Sigue la configuración actual, usa las herramientas con "
    "cuidado y comunica sólo resultados respaldados por la evidencia disponible. "
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
