import os
from datetime import datetime

from pydantic_ai import Agent
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

model = OllamaModel("qwen3:14b", provider=OllamaProvider(
    base_url="http://localhost:11434/v1"))

NOTES_FILE="notes.txt"

def get_current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def calculate(expression: str) -> str:
    if not set(expression) <= set("0123456789+-*/(). "):
        return "Error: only numbers are allowed"
    try:
        return str(eval(expression))
    except Exception as error:
        return f"Error: {error}"

def save_note(note: str) -> str:
    with open(NOTES_FILE, encoding="utf-8") as file:
        file.write(f"-{note}\n")
    return "Note saved"

def read_note(note: str) -> str:
    if not os.path.exists(NOTES_FILE):
        return "No notes saved yet"
    with open(NOTES_FILE, encoding="utf-8") as file:
        return file.read()

agent = Agent(
    model=model,
    tools=[get_current_time, calculate, save_note, read_note],
    instructions=("You are a helpful personal assistant developed by me, "
                  "running 100% locally. Use your tools whenever they can "
                  "help answer the question. Keep your answers short and "
                  "friendly. Adapt your language to the spoken language of "
                  "the question"
    ),
)