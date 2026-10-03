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
"""The startup disk and the volumes mounted under /Volumes."""

import os
from pathlib import Path


def local_drives(removable=True, volumes=Path("/Volumes")):
    roots = [Path("/")]
    if not removable:
        return roots
    try:
        entries = sorted(volumes.iterdir())
    except OSError:
        return roots
    return roots + [entry for entry in entries
                    if not entry.is_symlink() and os.path.ismount(entry)]
