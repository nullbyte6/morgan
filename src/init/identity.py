"""Access the application's identity without importing its entry point."""

from collections.abc import Callable
from typing import Protocol

class AssistantIdentity(Protocol):
    name: str


_assistant_factory: Callable[[], AssistantIdentity] | None = None

def register_assistant(factory: Callable[[], AssistantIdentity]) -> None:
    """Register the singleton factory without initializing its runtime."""
    global _assistant_factory
    _assistant_factory = factory


def get_assistant() -> AssistantIdentity:
    """Return the registered singleton; the application owns its name and state."""
    if _assistant_factory is None:
        raise RuntimeError("The application has not registered its assistant")
    return _assistant_factory
