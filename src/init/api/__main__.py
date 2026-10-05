#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of morgan.
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
"""Command line for pairing phones: pair, devices and revoke <id>."""
import socket
import sys
import time

from src.init.api.auth import CODE_LIFETIME, DeviceStore, PairingCodes
from src.init.api.server import is_private_address
from src.init.config import load_config


def local_addresses() -> list[str]:
    try:
        found = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return sorted({item[4][0] for item in found if is_private_address(item[4][0])
                   and not item[4][0].startswith("127.")})


def pair():
    settings = load_config()["api"]
    code, _ = PairingCodes().create()
    scheme = "https" if settings["tls_certificate"] else "http"
    host = settings["host"]
    hosts = local_addresses() if host in ("0.0.0.0", "::") else [host]
    print(f"Pairing code: {code}  (valid for {CODE_LIFETIME // 60} minutes, single use)")
    for address in hosts:
        print(f"Server: {scheme}://{address}:{settings['port']}")
    if not settings["enabled"]:
        print('The API is off. Set "enabled": true in the "api" section of config.json '
              "and restart.")


def devices():
    paired = DeviceStore().list()
    if not paired:
        print("No paired devices.")
    for device in paired:
        seen = (time.strftime("%Y-%m-%d %H:%M", time.localtime(device["last_seen"]))
                if device["last_seen"] else "never")
        print(f"{device['id']}  {device['name']}  last seen {seen}")


def revoke(device_id):
    print("Revoked." if DeviceStore().revoke(device_id) else "No such device.")
    return 0


def main(arguments) -> int:
    command = arguments[0] if arguments else ""
    if command == "pair":
        pair()
    elif command == "devices":
        devices()
    elif command == "revoke" and len(arguments) == 2:
        return revoke(arguments[1])
    else:
        print("Usage: python -m src.init.api pair | devices | revoke <id>")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
