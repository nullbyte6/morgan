import threading
from ollama import chat
from config import MODEL, SYSTEM_PROMPT
from chat import Conversation

class Assistant:
    def __init__(
        self,
        model: str = MODEL,
        system_prompt: str = SYSTEM_PROMPT
    ):
        self.model = model
        self.conversation = Conversation(system_prompt)

        self._generation_lock = threading.Lock()

    def stream(self, prompt: str):

        if not self._generation_lock.acquire(blocking=False):
            raise RuntimeError(
                "Assistant is already generating a response."
            )

        try:
            self.conversation.add_user_message(prompt)

            response = chat(
                model=self.model,
                messages=self.conversation.get_messages(),
                stream=True
            )

            reply = ""

            for chunk in response:
                content = chunk["message"]["content"]
                reply += content

                for character in content:
                    yield character

            self.conversation.add_assistant_message(reply)

        except Exception:
            if (
                self.conversation.messages
                and self.conversation.messages[-1]["role"] == "user"
                and self.conversation.messages[-1]["content"] == prompt
            ):
                self.conversation.messages.pop()

            raise

        finally:
            self._generation_lock.release()

    def ask(self, prompt: str) -> str:
        return "".join(self.stream(prompt))

    def clear(self):
        with self._generation_lock:
            self.conversation.clear()