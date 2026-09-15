"""Regression checks without Ollama, notifications, or real user storage."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, Mock, patch

from agent import Assistant, main
from src.init import config, notifications, rules, session_log


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.assistant = Assistant()
        self.name_patch = patch.object(self.assistant, "name", "Test Assistant")
        self.name_patch.start()
        self.addCleanup(self.name_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name)
        for target, value in (
            ("HOME_PATH", home),
            ("CONFIG_FILE", home / "json" / "config.json"),
            ("LEGACY_CONFIG", home / "missing.json"),
        ):
            patcher = patch.object(config, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_shared_instance_preserves_state_across_threads(self):
        with patch.object(self.assistant, "terminal_ui", object()):
            ui = self.assistant.terminal_ui
            with ThreadPoolExecutor(max_workers=8) as pool:
                instances = list(pool.map(lambda _: Assistant(), range(32)))
            self.assertTrue(all(item is self.assistant for item in instances))
            self.assertIs(Assistant().terminal_ui, ui)

    def test_identity_import_does_not_load_runtime(self):
        result = subprocess.run(
            [sys.executable, "-c", "from agent import Assistant; import sys; "
             "assert Assistant() is Assistant(); "
             "assert Assistant().agent is None; "
             "assert 'pydantic_ai' not in sys.modules; "
             "assert 'src.init.brain' not in sys.modules"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_script_and_module_share_identity(self):
        # Execute the script definitions, excluding only its final main() call.
        code = """
import ast, sys, types
from pathlib import Path
tree = ast.parse(Path('agent.py').read_text(encoding='utf-8'))
tree.body.pop()
script = types.ModuleType('__main__')
sys.modules['__main__'] = script
exec(compile(tree, 'agent.py', 'exec'), script.__dict__)
from agent import Assistant
assert Assistant is script.Assistant
assert Assistant() is script.Assistant()
"""
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_main_runs_shared_assistant(self):
        with patch.object(self.assistant, "run") as run:
            main()
        run.assert_called_once_with()

    def test_name_reaches_greetings_instructions_and_banner(self):
        from pyfiglet import figlet_format

        self.assertIn(self.assistant.name, self.assistant.startup_greetings[0])
        self.assertIn(self.assistant.name, rules.current_instructions())
        self.assertEqual(self.assistant.banner,
                         figlet_format(self.assistant.name, font="big", width=120))
        with patch.object(self.assistant, "name", "Changed"):
            self.assertIn("Changed", rules.current_instructions())
            self.assertEqual(self.assistant.banner,
                             figlet_format("Changed", font="big", width=120))

    def test_stream_and_log_use_current_identity(self):
        log = session_log.SessionLog(directory=self.temp.name)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assistant.stream(["hello", " world"], session=log)
        contents = log.path.read_text(encoding="utf-8")
        self.assertIn(f"{self.assistant.name} Log", contents)
        self.assertIn(f"{self.assistant.name}:", contents)
        self.assertIn("hello world", contents)

    def test_notifications_and_timer_titles_use_identity(self):
        with patch.object(notifications, "_deliver") as deliver:
            notifications.send_notification("hello")
            deliver.assert_called_once_with(self.assistant.name, "hello")
            notifications.send_notification("hello", "Custom")
            deliver.assert_called_with("Custom", "hello")
        with patch.object(notifications, "schedule_notification") as schedule:
            notifications.start_timer(10)
            schedule.assert_called_once_with(
                10, "Timer", f"{self.assistant.name} — Timer finished")

    def test_scheduled_notification_resolves_default_name(self):
        with patch.object(notifications.os, "name", "nt"), \
                patch.object(notifications.threading, "Timer") as timer, \
                patch.object(notifications, "_timers", {}):
            result = json.loads(notifications.schedule_notification(10, "hello"))
            entry = notifications._timers[result["id"]]
            self.assertEqual(entry["title"], self.assistant.name)
            timer.return_value.start.assert_called_once()

    def test_notification_payload_carries_name_safely(self):
        with patch.object(notifications.os, "name", "nt"), \
                patch.object(notifications.subprocess, "run") as run:
            run.return_value.returncode = 0
            notifications._deliver("Title", "Message")
            payload = json.loads(run.call_args.kwargs["input"])
            self.assertEqual(payload["assistant_name"], self.assistant.name)

    def test_runtime_initializes_once_and_registers_instructions(self):
        with patch.object(self.assistant, "agent", None):
            self.assistant._initialize_runtime()
            model_agent = self.assistant.agent
            self.assistant._initialize_runtime()
            self.assertIs(self.assistant.agent, model_agent)
            self.assertIn(self.assistant.name, self.assistant.current_instructions())

    def test_session_commands_and_streaming(self):
        from pydantic_ai.messages import ModelResponse, TextPart
        from src.init import brain

        log = Mock(private=False)
        log.handle_command.return_value = None
        model_agent = MagicMock()
        response = ModelResponse(parts=[TextPart("Reply")])
        result = model_agent.run_stream_sync.return_value.__enter__.return_value
        result.stream_text.return_value = iter(["Reply"])
        result.all_messages.return_value = [response]
        inputs = iter(["reload", "cd .", "git status", "hello", "exit"])
        with patch.object(self.assistant, "agent", model_agent), \
                patch.object(self.assistant, "read_user_input", side_effect=inputs), \
                patch.object(self.assistant, "directory_cmd", side_effect=["Moved", None, None]), \
                patch.object(self.assistant, "git_cmd", side_effect=["Clean", None]), \
                patch.object(session_log, "SessionLog", return_value=log), \
                patch.object(brain, "refresh_model_keep_alive"), \
                patch.object(brain, "refresh", return_value="Reloaded"), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assistant.run_session()
        log.write.assert_any_call(self.assistant.name, "Moved")
        log.write.assert_any_call(self.assistant.name, "Clean")
        log.write.assert_any_call(self.assistant.name, "Reply")
        model_agent.run_stream_sync.assert_called_once()


if __name__ == "__main__":
    unittest.main()
