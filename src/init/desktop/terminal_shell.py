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
"""Start CMD with normal Ctrl+C handling, even from a detached GUI parent."""
import ctypes
import subprocess
import sys


def main():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handler_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
    kernel.SetConsoleCtrlHandler.argtypes = [handler_type, ctypes.c_int]
    kernel.SetConsoleCtrlHandler.restype = ctypes.c_int

    # The inherited ignore-Ctrl+C flag also affects the shell's children.
    # Clear it here, without changing Arlo's own console handlers.
    if not kernel.SetConsoleCtrlHandler(handler_type(), False):
        raise ctypes.WinError(ctypes.get_last_error())

    @handler_type
    def handle_control(event):
        # The shell handles these events; keep its supervising process alive.
        return event in (0, 1)

    if not kernel.SetConsoleCtrlHandler(handle_control, True):
        raise ctypes.WinError(ctypes.get_last_error())
    return subprocess.call([sys.argv[1], "/D"])


if __name__ == "__main__":
    sys.exit(main())
