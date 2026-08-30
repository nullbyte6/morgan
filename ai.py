import threading
from ollama import chat
from config import MODEL, SYSTEM_PROMPT


class Assistant:
    def __init__(
        self,
        model: str = MODEL,
        system_prompt: str = SYSTEM_PROMPT
    ):
        self.model = model
        self.system_prompt = system_prompt
        self.messages = []

        self._generation_lock = threading.Lock()

    def stream(self, prompt: str):
        if not self._generation_lock.acquire(blocking=False):
            raise RuntimeError("Assistant is already generating a response.")

        try:
            self.messages.append({
                "role": "user",
                "content": prompt
            })

            response = chat(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self.system_prompt
                    },
                    *self.messages
                ],
                stream=True
            )

            reply = ""

            for chunk in response:
                content = chunk["message"]["content"]
                reply += content

                for character in content:
                    yield character

            self.messages.append({
                "role": "assistant",
                "content": reply
            })

        except Exception:
            if (
                self.messages
                and self.messages[-1]["role"] == "user"
                and self.messages[-1]["content"] == prompt
            ):
                self.messages.pop()

            raise

        finally:
            self._generation_lock.release()

    def ask(self, prompt: str) -> str:
        return "".join(self.stream(prompt))

    def clear(self):
        with self._generation_lock:
            self.messages.clear()