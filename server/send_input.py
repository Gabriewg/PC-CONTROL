# SPDX-License-Identifier: AGPL-3.0-or-later
"""Envia um evento de teclado/mouse para o servidor (diagnostico)."""

from __future__ import annotations

import json
import socket
import struct
import sys
import time

MSG_SCREEN = 0x02
MSG_HELLO = 0x10
MSG_INPUT = 0x11


def send(sock, mtype: int, payload: bytes = b"") -> None:
    sock.sendall(struct.pack(">I", len(payload) + 1) + bytes((mtype,)) + payload)


def abrir(host: str, port: int) -> socket.socket:
    sock = socket.create_connection((host, port), 6)
    sock.settimeout(10)
    send(sock, MSG_HELLO, json.dumps({"v": 1, "name": "diag", "width": 960, "quality": 60}).encode())
    stream = sock.makefile("rb")
    header = stream.read(4)
    size = struct.unpack(">I", header)[0]
    body = stream.read(size)
    if body[0] != MSG_SCREEN:
        raise SystemExit(f"resposta inesperada: {body[0]}")
    print("conectado:", json.loads(body[1:]))
    return sock


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
    sock = abrir(host, port)

    for arg in sys.argv[3:]:
        if "=" in arg:
            cmd = dict(part.split("=", 1) for part in arg.split(","))
            event = {"t": "k", "key": cmd.get("key", ""), "mods": cmd.get("mods", "").split("|") if cmd.get("mods") else []}
        else:
            event = {"t": "k", "key": arg, "mods": []}
        print("enviando", event)
        send(sock, MSG_INPUT, json.dumps(event).encode())
        time.sleep(0.25)

    time.sleep(0.5)
    sock.close()


if __name__ == "__main__":
    main()
