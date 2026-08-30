from ai import Assistant

def main():
    assistant = Assistant()

    while True:
        prompt = input(">> ")
        if prompt.lower() == "exit":
            break

        reply = assistant.ask(prompt)
        print(f"ATLAS: {reply}")

if __name__ == "__main__":
    main()