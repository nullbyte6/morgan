"""Immutable observable task activity, without model text or reasoning."""

from dataclasses import dataclass
from pathlib import PureWindowsPath


@dataclass(frozen=True)
class TaskActivity:
    task_id: str
    lifecycle: str
    role: str
    event: str = "state"
    call_id: str = ""
    category: str = ""
    subject: str = ""


def tool_activity(name, arguments, role, spec):
    if role == "verify" and (not spec.effectful or spec.verification_capable):
        return "verify", ""
    if name in {"read_code", "read_file", "read_binary_file"}:
        path = arguments.get("path", "")
        subject = PureWindowsPath(path).name if isinstance(path, str) else ""
        return "read", " ".join(subject.split())[:80]
    if name in {"search_code", "list_code", "find_directories", "list_files"}:
        return "search", ""
    if spec.domain == "git":
        return "git", ""
    if name in {"verify_code", "check_system_health", "check_disk_health", "check_security_health"}:
        return "verify", ""
    if name in {"search_web", "read_web_page"}:
        return "web", ""
    return ("execute" if spec.effectful and not spec.ancillary else "inspect"), ""
