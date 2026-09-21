import tempfile
import unittest
from pathlib import Path

from src.init.memory.integration import MemoryTurn, active_memory, memory_instructions
from src.init.memory.service import MemoryService


class MemoryContextTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.service = MemoryService(Path(self.tempdir.name) / "memory.sqlite3")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_relevant_fact_is_injected(self):
        memory = self.service.remember(
            "El color favorito de mi familiar es ultravioleta",
            category="fact",
            key="test_family_color",
        )

        context = self.service.context("cual es el color favorito de mi familiar")

        self.assertIn(memory["id"], context)
        self.assertIn("ultravioleta", context)
        self.assertNotIn("ultravioleta", self.service.context("temperatura exterior"))

    def test_history_is_used_when_no_confirmed_memory_matches(self):
        session_id = self.service.start_session()
        self.service.record_message(
            session_id, "user", "Mi familiar se llama NombreDePrueba"
        )
        self.service.record_message(session_id, "assistant", "Lo tendré presente.")

        context = self.service.context("como se llama mi familiar")

        self.assertIn("NombreDePrueba", context)

    def test_instructions_include_prompt_relevant_context(self):
        memory = self.service.remember(
            "El instrumento favorito de mi familiar es el piano",
            category="fact",
            key="test_family_instrument",
        )
        token = active_memory.set(
            MemoryTurn(
                self.service,
                "session",
                "message",
                "cual es el instrumento favorito de mi familiar",
                False,
                None,
            )
        )
        try:
            instructions = memory_instructions()
        finally:
            active_memory.reset(token)

        self.assertIn(memory["id"], instructions)
        self.assertIn("use recall to verify it", instructions)


if __name__ == "__main__":
    unittest.main()
