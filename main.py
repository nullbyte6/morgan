from ollama import chat

MODEL = "qwen3-coder"
def ask(prompt: str) -> str:
    response = chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return response["message"]["content"]


while True:
    prompt = input(">> ")
    if prompt.lower() in ("salir", "quit"):
        break

    print(f"ATLAS > {ask(prompt)}")