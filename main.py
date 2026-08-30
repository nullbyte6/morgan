from ai import Assistant

def main():
    assistant = Assistant()
    print("Type 'exit' to quit.")

    while True:
        prompt = input(">> ")

        if prompt.lower() == "exit":
            break

        print("/> ", end="", flush=True)

        for character in assistant.stream(prompt):
            print(character, end="", flush=True)

if __name__ == "__main__":
    main()