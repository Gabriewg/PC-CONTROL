#!/usr/bin/env python3
"""
Cliente de teste: valida o servidor sem precisar do celular.

Uso:
    python test_client.py 127.0.0.1 8765

Ele conecta, recebe quadros, salva o ultimo em frame.jpg e move o cursor
do PC para o centro da tela (para confirmar que a injecao funciona).
"""

from __future__ import annotations

import json
import struct
import sys
import time

MSG_VIDEO = 0x01
MSG_SCREEN = 0x02
MSG_HELLO = 0x10
MSG_INPUT = 0x11
MSG_INFO = 0x12
MSG_PONG = 0x14


def send(sock, mtype: int, payload: bytes = b"") -> None:
    sock.sendall(struct.pack(">I", len(payload) + 1) + bytes((mtype,)) + payload)


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
    frames = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    pin = sys.argv[4] if len(sys.argv) > 4 else ""

    print(f"conectando em {host}:{port} ...")
    sock = __import__("socket").create_connection((host, port), 6)
    sock.settimeout(10)
    stream = sock.makefile("rb")

    hello = {"v": 1, "name": "test-client", "width": 1280, "quality": 70, "fps": 30, "pin": pin}
    send(sock, MSG_HELLO, json.dumps(hello).encode())

    total = 0
    last = b""
    info = None
    started = time.perf_counter()

    while total < frames:
        header = stream.read(4)
        if len(header) < 4:
            print("conexao encerrada pelo servidor")
            break
        (size,) = struct.unpack(">I", header)
        body = stream.read(size)
        mtype, payload = body[0], body[1:]

        if mtype == MSG_SCREEN:
            info = json.loads(payload)
            print("tela:", info)
        elif mtype == MSG_INFO:
            print("servidor:", json.loads(payload))
        elif mtype == MSG_VIDEO:
            total += 1
            last = payload[4:]

    elapsed = time.perf_counter() - started
    if total:
        with open("frame.jpg", "wb") as fh:
            fh.write(last)
        print(
            f"{total} quadros em {elapsed:.2f}s "
            f"({total / elapsed:.1f} fps, ultimo com {len(last) / 1024:.0f} KB) -> frame.jpg"
        )

    print("movendo o cursor para o centro da tela...")
    try:
        send(sock, MSG_INPUT, json.dumps({"t": "m", "x": 0.5, "y": 0.5}).encode())
        time.sleep(0.4)
        send(sock, MSG_INPUT, json.dumps({"t": "ping", "ts": int(time.time() * 1000)}).encode())
        time.sleep(0.2)
    except OSError as exc:
        print("nao foi possivel enviar entrada:", exc)
    sock.close()
    print("ok")


if __name__ == "__main__":
    main()
