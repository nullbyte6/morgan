import sys
import threading

from colorama import Fore, Style

USER_COLOR = Fore.LIGHTBLACK_EX
ASSISTANT_COLOR = Fore.GREEN
RESET_COLOR = Style.RESET_ALL


class Spinner:
    """Small terminal spinner shown while the agent is preparing its answer."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        sys.stdout.write("\r/")
        sys.stdout.flush()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def _animate(self) -> None:
        frames = ("/", "-", "\\", "|")
        frame_index = 0
        while not self._stop_event.wait(0.1):
            sys.stdout.write(f"\r{frames[frame_index]}")
            sys.stdout.flush()
            frame_index = (frame_index + 1) % len(frames)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        sys.stdout.write("\r \r")
        sys.stdout.flush()