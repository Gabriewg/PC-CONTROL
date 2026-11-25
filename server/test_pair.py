#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Teste de integracao do pareamento por QR (token de uso unico + aparelho).

Roda um servidor de verdade (TLS 1.3) em uma porta local e um cliente que faz o
mesmo handshake do app Android:

1. QR -> token de uso unico (HMAC do token);
2. servidor devolve id + chave exclusiva do aparelho;
3. proxima conexao usa a chave do aparelho, sem PIN;
4. token reaproveitado/expirado e MAC errado sao recusados.

Uso (Windows):
    server\\.venv\\Scripts\\python.exe server\\test_pair.py
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import socket
import ssl
import struct
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import security
import server as lc_server

MSG_SCREEN = 0x02
MSG_HELLO = 0x10
MSG_INFO = 0x12
MSG_CHALLENGE = 0x15
MSG_PAIR_OK = 0x16

ok_count = 0
fail_count = 0


def check(cond: bool, label: str) -> None:
    global ok_count, fail_count
    if cond:
        ok_count += 1
        print(f"  ok    {label}")
    else:
        fail_count += 1
        print(f"  FALHA {label}")


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def mac_b64(key: bytes, nonce: bytes) -> str:
    return b64(hmac.new(key, nonce, hashlib.sha256).digest())


async def recv_msg(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    header = await asyncio.wait_for(reader.readexactly(4), timeout=10)
    (size,) = struct.unpack(">I", header)
    if size < 1 or size > 8 * 1024 * 1024:
        raise ValueError(f"tamanho invalido: {size}")
    body = await asyncio.wait_for(reader.readexactly(size), timeout=10)
    return body[0], body[1:]


async def send_msg(writer: asyncio.StreamWriter, mtype: int, obj: dict) -> None:
    payload = json.dumps(obj).encode()
    writer.write(struct.pack(">I", len(payload) + 1) + bytes((mtype,)) + payload)
    await writer.drain()


async def open_session(port: int, client_ctx: ssl.SSLContext):
    reader, writer = await asyncio.open_connection(
        "127.0.0.1", port, ssl=client_ctx, server_hostname="localcontrol"
    )
    mtype, payload = await recv_msg(reader)
    if mtype != MSG_CHALLENGE:
        raise RuntimeError(f"esperava CHALLENGE, veio 0x{mtype:02x}")
    challenge = json.loads(payload)
    return reader, writer, challenge


async def pair(port, client_ctx, token: str) -> tuple[int, dict]:
    reader, writer, challenge = await open_session(port, client_ctx)
    nonce = base64.b64decode(challenge["nonce"])
    hello = {
        "v": 3,
        "name": "test-pair",
        "width": 1280,
        "quality": 70,
        "fps": 30,
        "pid": security.token_id(token),
        "mac": mac_b64(token.encode("ascii"), nonce),
    }
    await send_msg(writer, MSG_HELLO, hello)
    mtype, payload = await recv_msg(reader)
    data = json.loads(payload) if payload else {}
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return mtype, data


async def connect_device(port, client_ctx, device_id: str, device_key: bytes) -> tuple[int, dict]:
    reader, writer, challenge = await open_session(port, client_ctx)
    nonce = base64.b64decode(challenge["nonce"])
    hello = {
        "v": 3,
        "name": "test-device",
        "width": 1280,
        "quality": 70,
        "fps": 30,
        "device": device_id,
        "mac": mac_b64(device_key, nonce),
    }
    await send_msg(writer, MSG_HELLO, hello)
    mtype, payload = await recv_msg(reader)
    data = json.loads(payload) if payload else {}
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return mtype, data


async def main() -> int:
    print("== QR: formato do link ==")
    fp = b64(hashlib.sha256(b"chave-publica-de-teste").digest())
    uri = security.pairing_uri("192.168.0.10", 8765, fp, "token-de-teste", "PC do Gabriel")
    parsed = urlparse(uri)
    query = parse_qs(parsed.query)
    check(parsed.scheme == "localcontrol", "esquema localcontrol")
    check(parsed.hostname == "192.168.0.10" and parsed.port == 8765, "host e porta no link")
    check(security.fingerprint_from_url(query["fp"][0]) == fp, "fingerprint SPKI volta igual")
    check(query["t"][0] == "token-de-teste", "token no link")
    check(query["n"][0] == "PC do Gabriel", "nome do PC no link")

    print("== servidor de teste ==")
    tmp = Path(tempfile.mkdtemp(prefix="lc-pair-"))
    pin_path = tmp / "pin.txt"
    record = security.save_pin(pin_path, "1234", tls_enabled=True)
    cert = tmp / "cert.pem"
    key = tmp / "key.pem"
    security.ensure_certificate(cert, key)
    fingerprint = security.spki_fingerprint(cert)
    ssl_ctx = security.build_ssl_context(cert, key)

    class Clock:
        def __init__(self) -> None:
            self.now = time.time()

        def __call__(self) -> float:
            return self.now

    clock = Clock()
    tokens = security.PairingTokens(ttl=30, clock=clock)
    devices = security.DeviceStore(tmp / "devices.json")
    limiter = security.RateLimiter(tmp / "auth_state.json")

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    args = argparse.Namespace(
        port=port,
        bind="127.0.0.1",
        discovery_port=0,
        monitor=1,
        width=1600,
        quality=70,
        fps=30,
        no_gpu=True,
        no_qr=True,
        no_tray=True,
        pair_ttl=30,
    )
    srv = lc_server.Server(
        args,
        record,
        limiter,
        True,
        tokens=tokens,
        devices=devices,
        fingerprint=fingerprint,
        activity_cb=lambda count, names: None,
    )
    srv.grabber.monitor_index = 1
    listener = await asyncio.start_server(
        srv.handle_client, "127.0.0.1", port, ssl=ssl_ctx, ssl_handshake_timeout=5
    )
    print(f"  servidor em 127.0.0.1:{port}")

    client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    client_ctx.check_hostname = False
    client_ctx.verify_mode = ssl.CERT_NONE

    try:
        print("== token de uso unico ==")
        token = tokens.create()
        mtype, data = await pair(port, client_ctx, token.token)
        check(mtype == MSG_PAIR_OK, "pareamento aceito (PAIR_OK)")
        device_id = data.get("id", "")
        device_key = base64.b64decode(data.get("key", ""))
        check(len(device_id) == 16, "id do aparelho com 16 hex")
        check(len(device_key) == 32, "chave do aparelho com 32 bytes")
        check(devices.get(device_id) is not None, "aparelho salvo em devices.json")
        check((tmp / "devices.json").exists(), "devices.json gravado")

        mtype, data = await pair(port, client_ctx, token.token)
        check(mtype == MSG_INFO, "token reaproveitado recusado")
        check("pareamento" in data.get("error", ""), "mensagem de pareamento invalido")

        print("== conexao com a chave do aparelho ==")
        mtype, data = await connect_device(port, client_ctx, device_id, device_key)
        check(mtype == MSG_SCREEN, "aparelho pareado conectou sem PIN")
        check(data.get("tls") is True, "sessao com TLS")

        print("== MAC errado nao consome o token ==")
        token2 = tokens.create()
        reader, writer, challenge = await open_session(port, client_ctx)
        nonce = base64.b64decode(challenge["nonce"])
        await send_msg(
            writer,
            MSG_HELLO,
            {
                "v": 3,
                "name": "test-pair",
                "pid": token2.pid,
                "mac": mac_b64(b"chave-errada", nonce),
            },
        )
        mtype, data = await recv_msg(reader)
        check(mtype == MSG_INFO, "MAC errado recusado")
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

        mtype, data = await pair(port, client_ctx, token2.token)
        check(mtype == MSG_PAIR_OK, "token continua valido depois de MAC errado")

        print("== expiracao ==")
        token3 = tokens.create()
        clock.now += 31
        mtype, data = await pair(port, client_ctx, token3.token)
        check(mtype == MSG_INFO, "token expirado recusado")

        print("== revogacao ==")
        devices.clear()
        mtype, data = await connect_device(port, client_ctx, device_id, device_key)
        check(mtype == MSG_INFO, "aparelho esquecido recusado")
    finally:
        listener.close()
        await listener.wait_closed()
        srv.grabber.close()

    print()
    if fail_count:
        print(f"FALHARAM {fail_count} teste(s); {ok_count} passaram.")
        return 1
    print(f"TODOS OS {ok_count} TESTES DE PAREAMENTO PASSARAM")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
