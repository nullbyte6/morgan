import queue
import threading

from ai import Assistant


def generate_response(assistant: Assistant, prompt: str, output_queue: queue.Queue):
    try:
        for char in assistant.stream(prompt):
            output_queue.put(("char", char))
        output_queue.put(("done", None))
    except Exception as error:
        output_queue.put(("error", error))


def main():
    assistant = Assistant()

    print("Type 'exit' to quit.")
    print()

    while True:
        prompt = input(">> ")

        if prompt.lower() == "exit":
            break

        output_queue = queue.Queue()

        thread = threading.Thread(
            target=generate_response,
            args=(assistant, prompt, output_queue),
            daemon=True
        )

        thread.start()

        print("/> Pensando...", end="", flush=True)

        generating = True
        thinking = True

        while generating:
            try:
                event, value = output_queue.get(timeout=0.05)

                if event == "char":
                    if thinking:
                        print("\r/> ", end="", flush=True)
                        thinking = False

                    print(value, end="", flush=True)

                elif event == "done":
                    generating = False

                elif event == "error":
                    print(f"\nError: {value}")
                    generating = False

            except queue.Empty:
                pass

        thread.join()
        print()


if __name__ == "__main__":
    main()