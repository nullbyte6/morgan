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

import argparse
import json
import sys
from pathlib import Path

from .service import MemoryService


def main(argv=None):
    parser = argparse.ArgumentParser(description="Arlo local memory maintenance")
    parser.add_argument("--database", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    backup = commands.add_parser("backup")
    backup.add_argument("destination", type=Path)
    importer = commands.add_parser("import")
    importer.add_argument("paths", nargs="+", type=Path)
    importer.add_argument("--speaker", action="append", required=True, metavar="NAME=ROLE")
    importer.add_argument("--include-tail", action="store_true",
                          help="Only for closed logs: also accept the final unsealed entry")
    for command in ("delete-message", "delete-memory"):
        deletion = commands.add_parser(command)
        deletion.add_argument("id")
    args = parser.parse_args(argv)
    try:
        if args.database:
            service = MemoryService(args.database)
        else:
            from .integration import configured_service
            service = configured_service()
            if service is None:
                raise ValueError("Memory is disabled; specify --database for explicit maintenance")
        if args.command == "check":
            result = service.health()
            success = result["integrity"] == ["ok"] and not result["foreign_key_errors"]
        elif args.command == "backup":
            service.backup(args.destination)
            result, success = {"backup": str(args.destination)}, True
        elif args.command == "import":
            roles = {}
            for speaker in args.speaker:
                name, separator, role = speaker.rpartition("=")
                if not separator or not name or role not in ("user", "assistant", "system"):
                    raise ValueError("Use --speaker NAME=user, NAME=assistant or NAME=system")
                roles[name] = role
            paths = [file for path in args.paths for file in
                     (sorted(path.glob("*.md")) if path.is_dir() else [path])]
            result = [service.import_markdown(path, role_map=roles, include_tail=args.include_tail) for path in paths]
            success = all(not item["error"] for item in result)
        else:
            deleted = service.delete_message(args.id) if args.command == "delete-message" else service.delete_memory(args.id)
            result, success = {"deleted": deleted, "original_markdown_retained": True}, deleted
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if success else 1
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
