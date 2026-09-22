"""Offline regression tests for desktop input -> model -> actual tool execution.

Only model responses, speech playback and unrelated Steam discovery are faked.
File operations and the harmless PowerShell check use the real tool bodies.
Windows power commands are always mocked.
"""

import asyncio
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

import httpx2 as httpx
os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
from PySide6.QtCore import Qt
from pydantic_ai import Agent, Tool
from pydantic_ai.messages import (BinaryContent, ModelRequest, ModelResponse,
                                  TextPart, ToolCallPart, ToolReturnPart,
                                  UserPromptPart)
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

# Importing desktop tools should not require the test machine's Steam registry.
_steam_module = sys.modules.get("src.init.steam")
sys.modules["src.init.steam"] = types.SimpleNamespace(steam_manager=None)
from src.init import brain, commands
from src.init.worker import AssistantWorker
if _steam_module is None:
    sys.modules.pop("src.init.steam")
else:
    sys.modules["src.init.steam"] = _steam_module

from src.init.attachments import DesktopMessage, DesktopVoiceMessage
from src.init.core import Assistant
from src.init.identity import register_assistant
from src.init.memory.integration import (MemoryTurn, active_memory,
                                         memory_instructions)
from src.init.session_log import SessionLog


class ActionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.assistant = object.__new__(Assistant)
        self.assistant.username = "Test user"
        self.assistant.MODEL_NAME = "test:executor"
        self.assistant.voice = Mock(is_done=Mock(return_value=True))
        self.assistant.audio_model = None
        self.assistant.audio_model_name = None
        self.assistant.shutdown_requested = threading.Event()
        self.assistant._reload_lock = threading.Lock()
        register_assistant(lambda: self.assistant)
        self.addCleanup(register_assistant, Assistant)
        self.addCleanup(commands.set_confirmation_handler, None)
        self.session = SessionLog(directory=self.folder.name)
        self.addCleanup(self.session.close)
        self.requests = []
        self.phases = []

    def configure(self, actions, tools):
        """Simulate streamed tool calls; the agent dispatches real registered tools."""
        pending = iter(actions)

        async def stream(messages, info):
            self.requests.append((messages[:], info))
            action = next(pending, None)
            if action is None:
                results = [p.content for m in messages for p in m.parts
                           if isinstance(p, ToolReturnPart)]
                yield str(results[-1]) if results else "No action requested."
            else:
                name, args = action
                self.assertIn(name, {t.name for t in info.function_tools})
                payload = json.dumps(args)
                yield {0: DeltaToolCall(name=name, json_args=payload[:2])}
                yield {0: DeltaToolCall(json_args=payload[2:])}

        self.assistant.agent = Agent(
            FunctionModel(stream_function=stream, model_name="test:executor"),
            tools=[Tool(f, sequential=True) for f in tools])

    def audio(self):
        # No non-streaming function is supplied: a transcription pass would fail.
        self.assistant.audio_model = FunctionModel(
            stream_function=self.assistant.agent.model.stream_function,
            model_name="gemma4:e2b")
        self.assistant.audio_model_name = "gemma4:e2b"
        patcher = patch("src.init.config.load_dev_file",
                        return_value={"audio_model": "gemma4:e2b"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def worker(self):
        with patch("src.init.worker.Assistant", return_value=self.assistant), \
                patch("src.init.worker.SessionLog", return_value=self.session):
            worker = AssistantWorker()
        errors = []
        worker.failed.connect(errors.append)
        worker.rejected.connect(lambda _, error: errors.append(error))
        worker.phase.connect(lambda _, phase: self.phases.append(phase))
        return worker, errors

    def test_typed_request_executes_multiple_tools_and_streams_the_result(self):
        path = Path(self.folder.name) / "created.md"
        self.configure([
            ("create_file", {"path": str(path), "content": "ARLO_FILE_OK"}),
            ("read_file", {"path": str(path)}),
        ], [brain.create_file, brain.read_file])
        worker, errors = self.worker()
        worker._ask(1, DesktopMessage("Crea y lee el archivo de prueba."), Mock())
        self.assertEqual(errors, [])
        self.assertEqual(path.read_text(encoding="utf-8"), "ARLO_FILE_OK")
        self.assertEqual(self.phases, ["executing", "processing"] * 2)
        results = [p for m in worker.history for p in m.parts if isinstance(p, ToolReturnPart)]
        self.assertEqual([p.tool_name for p in results], ["create_file", "read_file"])

    def test_native_audio_and_following_text_execute_tools_through_gemma(self):
        path = Path(self.folder.name) / "voice.md"
        self.configure([("create_file", {"path": str(path), "content": "VOICE_OK"})],
                       [brain.create_file])
        self.audio()
        worker, errors = self.worker()
        worker._ask(1, DesktopVoiceMessage(b"test audio"), Mock())
        self.assertEqual(errors, [])
        self.assertTrue(path.is_file())
        self.assertEqual(self.session.last_user_text, "[Voice input]")
        voice_prompt = next(p for m in worker.history for p in m.parts
                            if isinstance(p, UserPromptPart))
        self.assertEqual(voice_prompt.content,
                         [BinaryContent(data=b"test audio", media_type="audio/wav")])
        self.configure([("read_file", {"path": str(path)})], [brain.read_file])
        self.audio()
        worker._ask(2, DesktopMessage("Lee el archivo anterior."), Mock())
        self.assertEqual(errors, [])
        for message in worker.history:
            if isinstance(message, ModelResponse):
                self.assertEqual(message.model_name, "gemma4:e2b")

    def test_general_shell_command_reaches_subprocess_with_confirmation(self):
        self.configure([("execute_command", {
            "command": "Write-Output 'ARLO_COMMAND_OK'",
            "working_directory": self.folder.name,
            "shell": "PowerShell",
        })], [commands.execute_command])
        worker, errors = self.worker()
        confirmations = []

        def accept(turn, message):
            confirmations.append(message)
            worker.resolve_confirmation(True)

        worker.confirmation_requested.connect(accept, Qt.ConnectionType.DirectConnection)
        worker._ask(1, DesktopMessage("Ejecuta el comando de prueba."), Mock())
        self.assertEqual(errors, [])
        self.assertEqual(len(confirmations), 1)
        result = next(p for m in worker.history for p in m.parts
                      if isinstance(p, ToolReturnPart))
        data = json.loads(result.content)
        self.assertEqual(data["exit_code"], 0)
        self.assertIn("ARLO_COMMAND_OK", data["stdout"])

    def test_shell_names_are_case_insensitive_and_accept_exe_suffix(self):
        commands.set_confirmation_handler(lambda _: True)
        for shell in (" PWSH.EXE ", "PowerShell", "CMD.exe", "AUTO"):
            with self.subTest(shell=shell), \
                    patch.object(commands.subprocess, "run", return_value=subprocess.CompletedProcess(
                        [], 0, "ok", "")) as run:
                result = json.loads(commands.execute_command("echo ok", shell=shell))
                self.assertEqual(result["status"], "completed")
                run.assert_called_once()

    def test_shell_denial_is_returned_without_execution(self):
        commands.set_confirmation_handler(lambda _: False)
        with patch.object(commands.subprocess, "run") as run:
            result = json.loads(commands.execute_command("Write-Output 'denied'"))
        run.assert_not_called()
        self.assertEqual(result["status"], "denied")

    def test_power_and_exit_requests_use_normal_tool_dispatch(self):
        self.configure([
            ("shutdown_computer", {"delay_seconds": 300}),
            ("kill_self", {}),
        ], [brain.shutdown_computer, brain.kill_self])
        worker, errors = self.worker()
        exits = []
        worker.exit_requested.connect(lambda: exits.append(True))
        with patch.object(brain.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, "", "")) as run:
            worker._ask(1, DesktopMessage("Apaga el PC en cinco minutos y cierra Arlo."), Mock())
        self.assertEqual(errors, [])
        argv = run.call_args.args[0]
        self.assertEqual(argv[argv.index("/t") + 1], "300")
        self.assertEqual(exits, [True])
        self.assertEqual(len(self.requests), 3)

    def test_immediate_shutdown_does_not_require_a_delay_argument(self):
        with patch.object(brain.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, "", "")) as run:
            brain.shutdown_computer()
        argv = run.call_args.args[0]
        self.assertEqual(argv[argv.index("/t") + 1], "0")

    def test_close_application_can_close_arlo_gracefully(self):
        from src.init.app_close import close_application

        self.configure([("close_application", {"application": "Arlo"})], [close_application])
        worker, errors = self.worker()
        exits = []
        worker.exit_requested.connect(lambda: exits.append(True))
        with patch("src.init.app_close.psutil.process_iter") as processes:
            worker._ask(1, DesktopMessage("Cierra Arlo."), Mock())
        self.assertEqual(errors, [])
        self.assertEqual(exits, [True])
        processes.assert_not_called()

    def test_power_failure_is_reported(self):
        with patch.object(brain.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, "", "shutdown failed test")):
            result = brain.shutdown_computer(30)
        self.assertIn("shutdown failed test", result)

    def test_mentioning_or_negating_power_actions_does_not_bypass_model(self):
        self.configure([], [])
        worker, errors = self.worker()
        with patch.object(brain, "shutdown_computer") as power, \
                patch.object(brain, "kill_self") as close:
            worker._ask(1, DesktopMessage("No apaga el ordenador; explica cómo cerrar Arlo."), Mock())
        self.assertEqual(errors, [])
        self.assertEqual(len(self.requests), 1)
        power.assert_not_called()
        close.assert_not_called()

    def test_cancelling_before_native_audio_does_not_execute(self):
        self.configure([], [])
        self.audio()
        cancel = threading.Event()
        cancel.set()
        reply, history = self.assistant.run_desktop_turn(
            "Voice message", [], audio_input=b"test audio", cancel_event=cancel)
        self.assertEqual((reply, history), ("", []))
        self.assertEqual(self.requests, [])
        self.assistant.voice.stop.assert_called()

    def test_image_history_does_not_select_audio_model(self):
        image = BinaryContent(data=b"image", media_type="image/png")
        history = [
            ModelRequest(parts=[UserPromptPart([image])]),
            ModelResponse(parts=[ToolCallPart("get_working_directory", {}, "old-call")]),
            ModelRequest(parts=[ToolReturnPart("get_working_directory", "D:\\arlo", "old-call")]),
        ]
        self.configure([("get_working_directory", {})], [brain.get_working_directory])
        _, updated = self.assistant.run_desktop_turn("Directorio actual", history)
        self.assertTrue(any(isinstance(p, ToolReturnPart) for m in updated[3:] for p in m.parts))
        self.assertTrue(all(m.model_name == "test:executor" for m in updated[3:]
                            if isinstance(m, ModelResponse)))

    def test_voice_marker_does_not_retrieve_unrelated_historical_commands(self):
        service = Mock(context=Mock(return_value="saved preferences"))
        token = active_memory.set(MemoryTurn(service=service, prompt="[Voice input]"))
        try:
            self.assertIn("saved preferences", memory_instructions())
        finally:
            active_memory.reset(token)
        service.context.assert_called_once_with("")

    def test_real_adapter_sends_native_audio_tools_and_one_system_message(self):
        from pydantic_ai.providers.ollama import OllamaProvider

        requests = []

        def respond(request):
            data = json.loads(request.content)
            requests.append(data)
            if any(message["role"] == "tool" for message in data["messages"]):
                deltas = [{"content": "ARLO_NATIVE_OK"}]
                finish = "stop"
            else:
                deltas = [
                    {"reasoning": "Internal planning must not be spoken."},
                    {"tool_calls": [{"index": 0, "id": "call-directory", "type": "function",
                                     "function": {"name": "get_working_directory", "arguments": "{}"}}]},
                ]
                finish = "tool_calls"
            chunks = [{"id": "test-completion", "created": 1, "model": data["model"],
                       "object": "chat.completion.chunk",
                       "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                      for delta in deltas]
            chunks.append({"id": "test-completion", "created": 1, "model": data["model"],
                           "object": "chat.completion.chunk",
                           "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
            body = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
                                  text=body + "data: [DONE]\n\n")

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        self.addCleanup(lambda: asyncio.run(client.aclose()))
        provider = OllamaProvider(base_url="http://localhost:11434/v1", http_client=client)
        self.assistant.agent = None
        with patch("pydantic_ai.providers.ollama.OllamaProvider", return_value=provider):
            reply, history = self.assistant.run_desktop_turn(
                "Voice message", [], audio_input=b"native wav")
        self.assertEqual(reply, "ARLO_NATIVE_OK")
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertEqual(request["model"], "gemma4:e2b")
            self.assertEqual(request["reasoning_effort"], "low")
            self.assertEqual(sum(m["role"] == "system" for m in request["messages"]), 1)
            self.assertIn("shutdown_computer", {tool["function"]["name"] for tool in request["tools"]})
        user = next(m for m in requests[0]["messages"] if m["role"] == "user")
        self.assertEqual(user["content"], [{"type": "input_audio", "input_audio": {
            "data": base64.b64encode(b"native wav").decode(), "format": "wav"}}])
        self.assertTrue(any(isinstance(p, ToolReturnPart) for m in history for p in m.parts))
        spoken = " ".join(str(call.args[0]) for call in self.assistant.voice.enqueue.call_args_list)
        self.assertNotIn("Internal planning", spoken)

    def test_reload_rebuilds_tools_and_resets_cached_audio_model(self):
        self.assistant.agent = None
        self.assistant._initialize_runtime()
        old_agent = self.assistant.agent
        self.assistant.audio_model = Mock()
        self.assistant.audio_model_name = "stale"
        with patch("src.init.hot_reload.reload_project_modules", return_value=([], [])):
            self.assistant.reload_source()
        self.assertIsNot(self.assistant.agent, old_agent)
        self.assertIsNone(self.assistant.audio_model)
        self.assertFalse(self.assistant.model.profile["openai_chat_supports_multiple_system_messages"])
        self.assertIn("execute_command", self.assistant.agent._function_toolset.tools)


if __name__ == "__main__":
    unittest.main()
