#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Cliente de teste: valida o servidor sem precisar do celular.

Uso:
    python test_client.py 127.0.0.1 8765 [quadros] [pin] [opcoes]

Opcoes:
    --no-tls               conecta em TCP puro (servidor rodando com --no-tls)
    --fingerprint BASE64   exige esta impressao digital SPKI (pinning)
    --show-fingerprint     so mostra a impressao digital do servidor e sai
    --pair-token TOKEN     pareia com o token do QR (uso unico) e mostra a
                           credencial do aparelho para as proximas conexoes
    --device-id ID         conecta como um aparelho ja pareado
    --device-key BASE64    chave do aparelho (junto de --device-id)
    --save-device ARQUIVO  salva id+chave recebidos no pareamento (NAO comite)

O PIN nao e enviado: o cliente responde ao desafio do servidor com
HMAC-SHA256(PBKDF2-HMAC-SHA256(pin, salt), nonce), igual ao app Android.
No pareamento, o token tambem nao e enviado: vai apenas HMAC-SHA256(token, nonce).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import socket
import ssl
import struct
import time
from pathlib import Path

import security

MSG_VIDEO = 0x01
MSG_SCREEN = 0x02
MSG_HELLO = 0x10
MSG_INPUT = 0x11
MSG_INFO = 0x12
MSG_PONG = 0x14
MSG_CHALLENGE = 0x15
MSG_PAIR_OK = 0x16

MAX_MESSAGE = 8 * 1024 * 1024


def send(sock, mtype: int, payload: bytes = b"") -> None:
    sock.sendall(struct.pack(">I", len(payload) + 1) + bytes((mtype,)) + payload)


def recv_msg(stream) -> tuple[int, bytes]:
    header = stream.read(4)
    if len(header) < 4:
        raise EOFError("conexao encerrada")
    (size,) = struct.unpack(">I", header)
    if size < 1 or size > MAX_MESSAGE:
        raise ValueError(f"tamanho de mensagem invalido: {size}")
    body = stream.read(size)
    if len(body) < size:
        raise EOFError("conexao encerrada no meio da mensagem")
    return body[0], body[1:]


def format_fp(fingerprint: str) -> str:
    limpo = fingerprint.replace(" ", "")
    return " ".join(limpo[i : i + 4] for i in range(0, len(limpo), 4))


def spki_fingerprint(sock: ssl.SSLSocket) -> str:
    """SHA-256 (base64) da chave publica, igual ao pinning do app."""
    der = sock.getpeercert(binary_form=True)
    if not der:
        raise RuntimeError("o servidor nao apresentou certificado")
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    cert = x509.load_der_x509_certificate(der)
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cliente de teste do Local Control")
    parser.add_argument("host", nargs="?", default="127.0.0.1")
    parser.add_argument("port", nargs="?", type=int, default=8765)
    parser.add_argument("frames", nargs="?", type=int, default=40)
    parser.add_argument("pin", nargs="?", default="")
    parser.add_argument("--no-tls", action="store_true", help="TCP puro")
    parser.add_argument("--fingerprint", default="", help="SPKI esperada (base64)")
    parser.add_argument("--show-fingerprint", action="store_true")
    parser.add_argument("--pair-token", default="", help="token do QR (uso unico)")
    parser.add_argument("--device-id", default="", help="id do aparelho pareado")
    parser.add_argument("--device-key", default="", help="chave do aparelho (base64)")
    parser.add_argument("--save-device", default="", help="salva a credencial do pareamento")
    args = parser.parse_args()

    print(f"conectando em {args.host}:{args.port} ...")
    raw = socket.create_connection((args.host, args.port), 6)
    raw.settimeout(10)

    if args.no_tls:
        sock = raw
    else:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        # A verificacao de cadeia nao serve para certificado autoassinado: o
        # pinning e feito na chave publica (SPKI), como no app.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        sock = ctx.wrap_socket(raw, server_hostname=args.host)
        fingerprint = spki_fingerprint(sock)
        print("TLS:", sock.version(), "| SPKI:", format_fp(fingerprint))
        if args.fingerprint:
            esperado = args.fingerprint.replace(" ", "")
            if fingerprint != esperado:
                print("ERRO: impressao digital diferente (possivel MITM).")
                print("  esperado:", format_fp(esperado))
                sock.close()
                return 2
            print("impressao digital confere.")
        if args.show_fingerprint:
            sock.close()
            return 0

    stream = sock.makefile("rb")
    challenge = None
    while challenge is None:
        try:
            mtype, payload = recv_msg(stream)
        except EOFError:
            print("o servidor encerrou a conexao antes do desafio")
            sock.close()
            return 1
        if mtype == MSG_CHALLENGE:
            challenge = json.loads(payload)
        elif mtype == MSG_INFO:
            # ex.: IP bloqueado por muitas tentativas
            print("servidor:", json.loads(payload))
            sock.close()
            return 1
        else:
            print(f"esperava CHALLENGE (0x15), recebi 0x{mtype:02x}")
            sock.close()
            return 1

    print(
        "desafio: kdf=%s iter=%s auth=%s"
        % (challenge.get("kdf"), challenge.get("iter"), challenge.get("auth"))
    )
    if not challenge.get("auth"):
        print("ERRO: o servidor nao tem PIN configurado")
        sock.close()
        return 1

    nonce = base64.b64decode(challenge["nonce"])
    hello = {
        "v": 3,
        "name": "test-client",
        "width": 1280,
        "quality": 70,
        "fps": 30,
    }

    if args.pair_token:
        token_bytes = args.pair_token.encode("ascii")
        pid = hashlib.sha256(token_bytes).hexdigest()[:32]
        hello["pid"] = pid
        hello["mac"] = base64.b64encode(
            hmac.new(token_bytes, nonce, hashlib.sha256).digest()
        ).decode("ascii")
        print("autenticando com token de pareamento (uso unico)...")
    elif args.device_id and args.device_key:
        key = base64.b64decode(args.device_key)
        hello["device"] = args.device_id
        hello["mac"] = base64.b64encode(
            hmac.new(key, nonce, hashlib.sha256).digest()
        ).decode("ascii")
        print(f"autenticando como aparelho pareado {args.device_id}...")
    else:
        salt = base64.b64decode(challenge["salt"])
        iterations = int(challenge["iter"])
        key = hashlib.pbkdf2_hmac(
            "sha256", args.pin.encode("utf-8"), salt, iterations, 32
        )
        hello["mac"] = base64.b64encode(
            hmac.new(key, nonce, hashlib.sha256).digest()
        ).decode("ascii")

    send(sock, MSG_HELLO, json.dumps(hello).encode())

    total = 0
    last = b""
    started = time.perf_counter()
    recusado = False

    while total < args.frames:
        try:
            mtype, payload = recv_msg(stream)
        except EOFError:
            print("conexao encerrada pelo servidor")
            break

        if mtype == MSG_PAIR_OK:
            info = json.loads(payload)
            print("pareamento concluido!")
            print("  id :", info.get("id"))
            print("  key:", info.get("key"))
            if args.save_device:
                destino = Path(args.save_device)
                with open(destino, "w", encoding="utf-8") as fh:
                    json.dump(
                        {
                            "id": info.get("id"),
                            "key": info.get("key"),
                            "name": info.get("name"),
                        },
                        fh,
                        indent=2,
                    )
                security.restrict_permissions(destino)
                print("  credencial salva em", destino, "(nao comite)")
        elif mtype == MSG_SCREEN:
            print("tela:", json.loads(payload))
        elif mtype == MSG_INFO:
            info = json.loads(payload)
            if info.get("error"):
                print("servidor:", info)
                recusado = True
                break
            if "warn" in info:
                print("aviso:", info)
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

    if recusado:
        sock.close()
        return 1

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
