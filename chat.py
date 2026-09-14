
class Conversation:
    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        self.messages = []

    def add_user_message(self, content: str):
        self.messages.append({
            "role": "user",
            "content": content})

    def add_assistant_message(self, content: str):
        self.messages.append({
            "role": "assistant",
            "content": content})

    def get_messages(self):
        return [
            {
                "role": "system",
                "content": self.system_prompt
            },
            *self.messages
        ]

    def clear(self):
        self.messages.clear()