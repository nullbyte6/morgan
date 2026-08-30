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

    def stream(self, prompt: str):
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

    def ask(self, prompt: str) -> str:
        return "".join(self.stream(prompt))

    def clear(self):
        self.messages.clear()