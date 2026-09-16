from __future__ import annotations

from typing import TYPE_CHECKING

from prompt_toolkit.key_binding import KeyBindings

if TYPE_CHECKING:
    from .editor import NoraEditor

def create_keybindings(editor: "NoraEditor") -> KeyBindings:
    kb = KeyBindings()

    @kb.add("c-s")
    def save(event) -> None:
        editor.save()

    @kb.add("c-q")
    def quit_editor(event) -> None:
        if editor.modified:
            editor.set_message("Unsaved changes — Ctrl+S to save, Ctrl+Q again to discard.")
            if editor.quit_pending:
                event.app.exit()

            editor.quit_pending = True
            return

        event.app.exit()

    @kb.add("escape")
    def cancel(event) -> None:
        editor.quit_pending = False
        editor.set_message("")

    return kb