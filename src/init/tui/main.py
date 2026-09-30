#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
#
#  This program is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty
#  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Terminal entry point: one lightweight Arlo session without Qt."""
import argparse
import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path


def parse_arguments(argv):
    parser = argparse.ArgumentParser(
        prog="arlo-tui", description="Arlo in the terminal: the lightweight version of the desktop.")
    parser.add_argument(
        "--no-voice", action="store_true",
        help="do not start or use the text-to-speech service; show subtitles and text only")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    return parser.parse_args(argv)


def configure_logging():
    from src.init.console import LogStream
    from src.init.identity import get_assistant_identifier

    log_path = Path(tempfile.gettempdir()) / get_assistant_identifier() / "agent.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.captureWarnings(True)
    sys.stderr = LogStream("assistant.stderr", logging.INFO)
    logging.getLogger("assistant.tui").info("Terminal backend logging initialized")


def splash():
    """Show the name at once while the heavy runtime modules import."""
    from src.init.config import load_dev_file
    from src.init.tui import i18n
    from src.init.tui.palette import channels, load_palette
    from src.init.tui.text import banner, pad

    try:
        import colorama
        colorama.just_fix_windows_console()
    except ImportError:
        pass
    size = os.get_terminal_size()
    i18n.refresh()
    art = banner(i18n.assistant_name(), size.columns, size.lines)
    width = max(len(line) for line in art)
    red, green, blue = channels(load_palette().state("idle"))
    color = f"\x1b[1;38;2;{red};{green};{blue}m"
    lines = ["\n" * max(0, (size.lines - len(art) - 2) // 3)]
    for line in art:
        lines.append(" " * ((size.columns - width) // 2) + color + pad(line, width) + "\x1b[0m\n")
    version = load_dev_file()["version"]
    lines.append(" " * ((size.columns - len(version)) // 2) + version + "\n")
    sys.stdout.write("".join(lines))
    sys.stdout.flush()


async def run(voice_enabled):
    from src.init.tui.app import TuiApp
    from src.init.tui.palette import load_palette
    from src.init.tui.prefs import Preferences
    from src.init.tui.widgets import Scheduler

    scheduler = Scheduler(asyncio.get_running_loop())
    application = TuiApp(scheduler, Preferences(), load_palette(), voice_enabled=voice_enabled)
    await application.run()


def main(argv=None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    if arguments.version:
        from src.init.config import load_dev_file
        print(load_dev_file()["version"])
        return 0
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("The terminal version needs an interactive terminal.", file=sys.stderr)
        return 2

    os.chdir(Path.home())
    from src.init.tui.i18n import t
    from src.init.voice_ipc import ProcessLock

    running = ProcessLock("desktop-running")
    if not running.acquire():
        print(t("tui.already_running"), file=sys.stderr)
        return 1
    try:
        splash()
        configure_logging()
        asyncio.run(run(not arguments.no_voice))
    finally:
        running.release()
    return 0
