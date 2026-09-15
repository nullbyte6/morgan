"""Read-only local PC diagnostics, independent of the agent and user storage."""

from .scanner import SystemHealthScanner

__all__ = ["SystemHealthScanner"]
