import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic_ai.messages import (ModelRequest, ModelResponse, PartDeltaEvent,
                                  PartStartEvent, TextPart, TextPartDelta,
                                  ToolCallPart, ToolReturnPart, UserPromptPart)

from src.init.core import Assistant, AssistantTextStream


class FakeVoice:
    def __init__(self):
        self.audio_callback = None
        self.speaking_callback = None
        self.subtitle_callback = None

    def begin_turn(self):
        pass

    def enqueue(self, text):
        pass

    def request_done(self):
        pass

    def is_done(self):
        return True

    def stop(self):
        pass


class FakeResult:
    def __init__(self, output, messages):
        self.output = output
        self._messages = messages

    def new_messages(self):
        return self._messages


class TextToolAgent:
    def __init__(self):
        self.calls = []

    async def run(self, prompt, *, message_history, event_stream_handler,
                  **kwargs):
        self.calls.append((prompt, list(message_history)))
        if len(self.calls) == 1:
            output = ('Inspecting.\n```json\n'
                      '{"name":"list_files","arguments":{"path":"."}}\n```')
            messages = [
                ModelRequest(parts=[UserPromptPart(prompt)]),
                ModelResponse(parts=[TextPart(output)]),
            ]
            events = [PartStartEvent(index=0, part=TextPart(output))]
        else:
            assert any(isinstance(part, ToolReturnPart)
                       for message in message_history
                       for part in message.parts)
            output = "Final answer"
            messages = [ModelResponse(parts=[TextPart(output)])]
            events = [
                PartStartEvent(index=0, part=TextPart("Final ")),
                PartDeltaEvent(index=0, delta=TextPartDelta("answer")),
            ]

        async def event_source():
            for event in events:
                yield event

        await event_stream_handler(
            SimpleNamespace(messages=[*message_history, *messages]),
            event_source())
        return FakeResult(output, messages)


class ConversationFlowTests(unittest.TestCase):
    def test_tool_payload_is_hidden_from_stream(self):
        chunks = []
        stream = AssistantTextStream({"list_files"}, chunks.append)
        text = ('Visible text.\n```json\n'
                '{"name":"list_files","arguments":{"path":"."}}\n```')
        for offset in range(0, len(text), 4):
            stream.feed(text[offset:offset + 4])
        visible, call = stream.finish()
        self.assertEqual(call, ("list_files", {"path": "."}))
        self.assertEqual("".join(chunks), visible)
        self.assertNotIn("list_files", visible)
        self.assertIn("Visible text.", visible)

    def test_text_tool_call_continues_with_result_and_streams_final_text(self):
        assistant = object.__new__(Assistant)
        assistant.agent = TextToolAgent()
        assistant.voice = FakeVoice()
        assistant.audio_model = None
        assistant.audio_model_name = None
        assistant.provider = None
        assistant._active_cancellation_token = None
        chunks = []

        async def tool_result(name, arguments):
            self.assertEqual((name, arguments),
                             ("list_files", {"path": "."}))
            return "file-a.py\nfile-b.py"

        with patch("src.init.core.invoke_text_tool", tool_result):
            reply, history = assistant.run_desktop_turn(
                "Inspect the project", [], on_chunk=chunks.append,
                cancel_event=threading.Event())

        self.assertEqual(reply, "Inspecting.\nFinal answer")
        self.assertEqual(chunks[-2:], ["Final ", "answer"])
        self.assertFalse(any("list_files" in chunk for chunk in chunks))
        self.assertTrue(any(isinstance(part, ToolCallPart)
                            for message in history for part in message.parts))
        self.assertTrue(any(isinstance(part, ToolReturnPart)
                            for message in history for part in message.parts))
        self.assertIsNone(assistant.agent.calls[1][0])


if __name__ == "__main__":
    unittest.main()
