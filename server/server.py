#!/usr/bin/env python3
"""
Servidor de controle remoto local (estilo AnyDesk) para Windows.

- Captura a tela e envia JPEG via TCP (funciona em Wi-Fi ou por USB com adb reverse)
- Recebe toques/teclas do celular e injeta no Windows com SendInput
- Responde a descoberta por UDP para o app achar o PC sozinho na rede

Dois motores de captura:
  * DXGI Desktop Duplication (dxcam) - rapido, usa a GPU; so envia quando a tela muda
  * GDI/BitBlt (mss)                 - fallback universal

Protocolo (os dois sentidos): [4 bytes tamanho][1 byte tipo][payload]
  0x01 VIDEO    : 2 bytes cursorX + 2 bytes cursorY (0..65535) + JPEG
  0x02 SCREEN   : JSON com resolucao/tela/monitores
  0x03 CURSOR   : 2 bytes X + 2 bytes Y (atualizacao barata do cursor)
  0x10 HELLO    : JSON do app: nome/tela + "mac" (HMAC-SHA256 do nonce)
  0x11 INPUT    : JSON com evento de mouse/teclado
  0x13 PING     : JSON {"ts": ...}   (cliente -> servidor)
  0x14 PONG     : JSON {"ts": ...}   (servidor -> cliente)
  0x15 CHALLENGE: JSON {"nonce","salt","iter","kdf"} enviado antes do HELLO

O PIN nunca trafega: o servidor manda um nonce novo a cada conexao e o app
responde com HMAC-SHA256(chave_derivada_do_PIN, nonce). O pin.txt guarda apenas
o resultado da KDF (PBKDF2-HMAC-SHA256 com salt).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import io
import json
import logging
import os
import socket
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

import mss
import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover - fallback
    cv2 = None

try:
    import dxcam
except Exception:  # pragma: no cover - opcional
    dxcam = None

from PIL import Image

import security
import wininput

# ------------------------------------------------------------------ constantes

MSG_VIDEO = 0x01
MSG_SCREEN = 0x02
MSG_CURSOR = 0x03
MSG_HELLO = 0x10
MSG_INPUT = 0x11
MSG_INFO = 0x12
MSG_PING = 0x13
MSG_PONG = 0x14
MSG_CHALLENGE = 0x15

DISCOVERY_PORT = 8766
DISCOVERY_MAGIC = b"LOCALCONTROL_DISCOVER"
# Teto das mensagens que o app manda. O servidor e quem envia os JPEGs; aceitar
# qualquer tamanho do cliente permitiria derrubar o PC com um cabecalho falso.
MAX_APP_MESSAGE = 64 * 1024
# Tempo para o app responder ao desafio e mandar o HELLO.
HELLO_TIMEOUT = 5.0
KEEPALIVE = 1.0  # reenvia o ultimo quadro parado a cada 1s (seguranca)

# Controle de fluxo. Se o cliente nao acompanha (4G, Wi-Fi ruim), o buffer de
# escrita do socket cresce e cada frame novo entra atras de varios antigos: a
# imagem chega cada vez mais atrasada. Acima de FLOW_HIGH_BYTES pulamos frames
# (o proximo ja tera o estado atual da tela); abaixo de FLOW_LOW_BYTES vale a
# pena esperar o drain de verdade.
FLOW_HIGH_BYTES = 96 * 1024
FLOW_LOW_BYTES = 32 * 1024

# Buffer de envio do kernel por conexao. Sem esse teto o Windows enfileira
# centenas de KB antes de o nosso backlog comecar a crescer e o controle de
# fluxo so reagiria tarde demais (latencia alta mesmo "pulando frames").
SEND_BUFFER_BYTES = 128 * 1024

VERSION = "1.3"

# Arquivos locais ficam ao lado do server.py (nao dependem do diretorio atual).
# Nenhum deles vai para o Git: veja .gitignore.
BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = str(BASE_DIR / "server.log")
PIN_PATH = BASE_DIR / "pin.txt"
CERT_PATH = BASE_DIR / "cert.pem"
KEY_PATH = BASE_DIR / "key.pem"
STATE_PATH = BASE_DIR / "auth_state.json"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3

logger = logging.getLogger("localcontrol")


def setup_logging() -> None:
    """Log com data/hora no console e em server.log (rotativo)."""
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    try:
        file_handler = RotatingFileHandler(
            LOG_PATH, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
        )
    except OSError as exc:
        print(f"aviso: nao foi possivel abrir {LOG_PATH}: {exc}")
    else:
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout) if sys.stdout is not None else None
    if stream_handler is not None:
        stream_handler.setFormatter(fmt)
        root.addHandler(stream_handler)


def _silence_comtypes_shutdown() -> None:
    """Esconde o ruido do comtypes/dxcam no encerramento.

    O dxcam guarda ponteiros COM em estruturas globais; no fim do processo o
    __del__ deles roda depois do CoUninitialize e o comtypes registra um
    "access violation" como excecao ignorada. Nao afeta nada (o processo ja esta
    saindo), mas poluia o server.err.log.
    """
    previous = sys.unraisablehook

    def hook(unraisable: "sys.UnraisableHookArgs") -> None:
        obj = unraisable.object
        module = getattr(type(obj), "__module__", "") if obj is not None else ""
        if not module.startswith("comtypes") and obj is not None:
            module = getattr(obj, "__module__", "")
        if module.startswith("comtypes"):
            return
        previous(unraisable)

    sys.unraisablehook = hook


def log(*args: object) -> None:
    logger.info(" ".join(str(a) for a in args))


def pack_msg(mtype: int, payload: bytes = b"") -> bytes:
    return struct.pack(">I", len(payload) + 1) + bytes((mtype,)) + payload


async def read_msg(
    reader: asyncio.StreamReader, max_size: int = MAX_APP_MESSAGE
) -> tuple[int, bytes]:
    header = await reader.readexactly(4)
    (size,) = struct.unpack(">I", header)
    # O tamanho e conferido ANTES de alocar/ler o corpo.
    if size < 1 or size > max_size:
        raise ValueError(f"tamanho de mensagem invalido: {size}")
    body = await reader.readexactly(size)
    return body[0], body[1:]


# ------------------------------------------------------------------ captura

def _new_mss() -> "mss.mss":
    factory = getattr(mss, "MSS", None) or mss.mss
    return factory()


class Grabber:
    """Captura + codifica a tela. Tudo roda em uma unica thread (mss/dxcam
    nao sao thread-safe) para nao misturar contextos de GPU."""

    def __init__(self, use_gpu: bool = True) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="captura")
        self._mss: "mss.mss | None" = None
        self._cam = None
        self._cam_output: int | None = None
        self._gpu_disabled = (not use_gpu) or (dxcam is None)
        self.monitor_index = 1
        self.bbox = (0, 0, 1920, 1080)
        self.last_grab_ms = 0.0
        self.backend = "gdi" if self._gpu_disabled else "dxgi"
        self._cache: bytes | None = None
        self._cache_kw: tuple[int, int] = (0, 0)
        # monitor mss (1..N) -> output DXGI (0..N-1). O dxcam numera os outputs
        # pela ordem do DXGI, que NAO bate com a do mss (que segue
        # EnumDisplayMonitors). Sem esse mapa o video vinha de um monitor e os
        # cliques iam para outro.
        self._dxgi_outputs: dict[int, int] = {}

    # -- gerenciamento de backend (sempre na thread do pool)

    def _open_mss(self) -> "mss.mss":
        if self._mss is None:
            self._mss = _new_mss()
        return self._mss

    def _drop_camera(self) -> None:
        if self._cam is not None:
            try:
                self._cam.release()
            except Exception:
                pass
        self._cam = None
        self._cam_output = None

    def close(self) -> None:
        """Solta camera e mss antes do processo sair.

        Fazer isso com o COM ainda inicializado evita que os destrutores do
        comtypes/dxcam rodem no shutdown e cuspam "access violation".
        """
        try:
            self._pool.submit(self._release).result(5)
        except Exception:  # noqa: BLE001
            pass
        self._pool.shutdown(wait=False)

    def _release(self) -> None:
        self._drop_camera()
        if self._mss is not None:
            try:
                self._mss.close()
            except Exception:
                pass
            self._mss = None

    def _output_rect(self, cam) -> tuple[int, int, int, int] | None:
        """Retangulo (left, top, w, h) do output DXGI da camera, se exposto."""
        output = getattr(cam, "_output", None) or getattr(cam, "output", None)
        desc = getattr(output, "desc", None)
        rect = getattr(desc, "DesktopCoordinates", None)
        if rect is None:
            return None
        return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)

    def _camera(self, index: int):
        if self._gpu_disabled:
            return None
        if self._cam is not None and self._cam_output == index:
            return self._cam
        self._drop_camera()

        monitors = self._ordered_monitors()
        mon = monitors[index]
        target = (mon["left"], mon["top"], mon["width"], mon["height"])
        total = max(1, len(monitors) - 1)  # mss[0] = tela virtual inteira

        # Tenta primeiro o output que ja funcionou para este monitor; depois os
        # demais, conferindo o retangulo de cada um ate achar o mesmo do mss.
        first = self._dxgi_outputs.get(index, max(0, index - 1))
        candidates = [first] + [i for i in range(total) if i != first]

        for out_idx in candidates:
            try:
                cam = dxcam.create(output_idx=out_idx, output_color="BGR")
            except Exception as exc:  # noqa: BLE001
                log(f"output DXGI {out_idx} indisponivel ({exc!r})")
                continue
            rect = self._output_rect(cam)
            if rect is not None and rect != target:
                try:
                    cam.release()
                except Exception:
                    pass
                continue
            self._cam = cam
            self._cam_output = index
            self._dxgi_outputs[index] = out_idx
            self.backend = "dxgi"
            extra = "" if rect is None else f" {rect[0]},{rect[1]} {rect[2]}x{rect[3]}"
            log(f"captura via GPU (Desktop Duplication, monitor {index} -> DXGI {out_idx}{extra})")
            return cam

        log("nenhum output DXGI corresponde ao monitor pedido; usando GDI")
        self._gpu_disabled = True
        self._cam = None
        self._cam_output = None
        self.backend = "gdi"
        return None

    # -- api publica

    def _ordered_monitors(self) -> list[dict]:
        """Monitores do mss com o principal primeiro (mss[0] = tela virtual).

        O mss segue a ordem do EnumDisplayMonitors, que nao coloca o principal
        necessariamente em primeiro lugar; isso deixava "MON 1" imprevisivel.
        """
        mons = self._open_mss().monitors
        if len(mons) <= 2:
            return mons
        outros = mons[1:]
        primarios = [m for m in outros if m.get("is_primary")]
        resto = [m for m in outros if not m.get("is_primary")]
        return [mons[0], *(primarios + resto)]

    def _monitor_list(self) -> list[dict]:
        return self._ordered_monitors()

    def monitors(self) -> list[dict]:
        return self._pool.submit(self._monitor_list).result(5)

    def reset_cache(self) -> None:
        self._cache = None
        self._cache_kw = (0, 0)

    async def capture(self, width: int, quality: int) -> tuple[bytes | None, bool]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, self._capture, width, quality)

    # -- trabalho pesado

    def _capture(self, width: int, quality: int) -> tuple[bytes | None, bool]:
        t0 = time.perf_counter()
        monitors = self._ordered_monitors()
        index = self.monitor_index if 0 < self.monitor_index < len(monitors) else 1
        mon = monitors[index]
        self.bbox = (mon["left"], mon["top"], mon["width"], mon["height"])

        arr = None
        is_bgr = False

        if not self._gpu_disabled:
            cam = self._camera(index)
            if cam is not None:
                try:
                    arr = cam.grab()
                except Exception:
                    self._drop_camera()
                    self._gpu_disabled = True
                    self.backend = "gdi"
                    arr = None
                else:
                    is_bgr = True
                    if arr is None:
                        # nada mudou na tela: reaproveita o ultimo JPEG
                        if self._cache is not None and self._cache_kw == (width, quality):
                            return self._cache, False

        if arr is None:
            arr = np.asarray(self._open_mss().grab(mon))
            is_bgr = False

        jpeg = self._encode(arr, is_bgr, width, quality)
        self._cache = jpeg
        self._cache_kw = (width, quality)
        self.last_grab_ms = (time.perf_counter() - t0) * 1000.0
        return jpeg, True

    def _encode(self, arr: np.ndarray, is_bgr: bool, width: int, quality: int) -> bytes:
        h, w = arr.shape[:2]
        out_w = width if 0 < width < w else w
        out_h = int(round(h * out_w / w))
        out_w -= out_w % 2
        out_h -= out_h % 2

        if cv2 is not None:
            frame = cv2.resize(arr, (out_w, out_h), interpolation=cv2.INTER_AREA)
            if not is_bgr:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            ok, buf = cv2.imencode(
                ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
            )
            if not ok:
                raise RuntimeError("falha ao codificar JPEG")
            return buf.tobytes()

        # fallback puro Pillow
        mode = "raw", "BGR" if is_bgr else "BGRX"
        img = Image.frombytes("RGB", (w, h), arr.tobytes(), mode[1])
        if out_w != w:
            img = img.resize((out_w, out_h), Image.BILINEAR)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=int(quality))
        return out.getvalue()


# ------------------------------------------------------------------ conexao

class Conn:
    """Escrita serializada: video, cursor e pong vem de tasks diferentes."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self._lock = asyncio.Lock()

    async def send(self, mtype: int, payload: bytes = b"", *, drain: bool = True) -> None:
        async with self._lock:
            self.writer.write(pack_msg(mtype, payload))
            if drain:
                await self.writer.drain()

    def backlog(self) -> int:
        """Bytes ja escritos que o sistema ainda nao conseguiu enviar."""
        transport = getattr(self.writer, "transport", None)
        if transport is None:
            return 0
        try:
            return transport.get_write_buffer_size()
        except (AttributeError, RuntimeError):
            return 0

    async def send_json(self, mtype: int, obj: dict) -> None:
        await self.send(mtype, json.dumps(obj, separators=(",", ":")).encode())

    def close(self) -> None:
        try:
            self.writer.close()
        except Exception:
            pass


@dataclass
class Session:
    name: str = "celular"
    width: int = 1600
    quality: int = 70
    fps: int = 30
    monitor: int = 1


def _clamp_int(value: object, default: int, low: int, high: int) -> int:
    """Converte um campo do HELLO sem deixar um JSON malicioso derrubar a conexao."""
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


class Server:
    def __init__(
        self,
        args: argparse.Namespace,
        pin_record: security.PinRecord,
        limiter: security.RateLimiter,
        tls_enabled: bool,
    ) -> None:
        self.args = args
        self.pin_record = pin_record
        self.limiter = limiter
        self.tls_enabled = tls_enabled
        self.grabber = Grabber(use_gpu=not args.no_gpu)
        self.grabber.monitor_index = args.monitor
        self.mouse = wininput.Mouse()
        self.keyboard = wininput.Keyboard()

    # -------------------------------------------------------------- video

    async def stream(self, conn: Conn, session: Session) -> None:
        interval = 1.0 / max(1, session.fps)
        last_sent = 0.0
        last_cursor: tuple[int, int] | None = None
        frames = 0
        mark = time.perf_counter()
        congested = False

        while True:
            t0 = time.perf_counter()

            # Cliente lento: pular o frame e' melhor que enfileira-lo. Capturar e
            # codificar adiantaria um quadro que so chegaria ainda mais atrasado.
            if conn.backlog() > FLOW_HIGH_BYTES:
                if not congested:
                    congested = True
                    log(f"rede lenta ({conn.backlog() // 1024} KB na fila); pulando frames")
                await asyncio.sleep(interval)
                continue
            if congested:
                congested = False
                log("rede recuperada")

            jpeg, changed = await self.grabber.capture(session.width, session.quality)
            now = time.perf_counter()

            bx, by, bw, bh = self.grabber.bbox
            cx, cy = wininput.cursor_pos()
            nx = int(max(0, min(65535, (cx - bx) / max(1, bw) * 65535)))
            ny = int(max(0, min(65535, (cy - by) / max(1, bh) * 65535)))

            # Buffer baixo: esperar o drain (detecta quedas de conexao e limita a
            # memoria). Buffer alto: so escrever, sem segurar o loop.
            drain = conn.backlog() < FLOW_LOW_BYTES

            # cursor anda mesmo com a tela parada: mensagem minuscula so pra ele
            if last_cursor != (nx, ny):
                await conn.send(MSG_CURSOR, struct.pack(">HH", nx, ny), drain=drain)
                last_cursor = (nx, ny)

            if jpeg is not None and (changed or now - last_sent >= KEEPALIVE):
                await conn.send(MSG_VIDEO, struct.pack(">HH", nx, ny) + jpeg, drain=drain)
                last_sent = now
                frames += 1

                if frames % 60 == 0:
                    elapsed = time.perf_counter() - mark
                    log(
                        f"video: {frames / max(elapsed, 0.001):4.1f} fps "
                        f"| {self.grabber.backend} "
                        f"| {self.grabber.last_grab_ms:4.1f} ms "
                        f"| {len(jpeg) / 1024:5.0f} KB/frame"
                    )
                    frames = 0
                    mark = time.perf_counter()

            wait = interval - (time.perf_counter() - t0)
            await asyncio.sleep(wait if wait > 0 else 0.01)

    # -------------------------------------------------------------- entrada

    async def input_loop(self, conn: Conn, session: Session) -> None:
        while True:
            mtype, payload = await read_msg(conn.reader)
            if mtype == MSG_PING:
                await conn.send(MSG_PONG, payload, drain=conn.backlog() < FLOW_LOW_BYTES)
                continue
            if mtype != MSG_INPUT:
                continue
            try:
                msg = json.loads(payload)
            except json.JSONDecodeError:
                continue
            await self.handle_input(conn, session, msg)

    async def handle_input(self, conn: Conn, session: Session, msg: dict) -> None:
        kind = msg.get("t")

        if kind == "m":  # movimento absoluto (toque na tela)
            self.mouse.set_bbox(self.grabber.bbox)
            self.mouse.move_abs(float(msg.get("x", 0)), float(msg.get("y", 0)))
        elif kind == "mr":  # movimento relativo (touchpad)
            self.mouse.move_rel(float(msg.get("dx", 0)), float(msg.get("dy", 0)))
        elif kind == "b":  # botao pressionado/solto
            self.mouse.button(str(msg.get("btn", "left")), bool(msg.get("down")))
        elif kind == "c":  # clique
            btn = str(msg.get("btn", "left"))
            count = int(msg.get("count", 1))
            if count >= 2:
                self.mouse.double_click(btn)
            else:
                self.mouse.click(btn)
        elif kind == "s":  # rolagem
            self.mouse.scroll(float(msg.get("dy", 0)), float(msg.get("dx", 0)))
        elif kind == "k":  # tecla (com modificadores)
            self.keyboard.tap(str(msg.get("key", "")), list(msg.get("mods") or []))
        elif kind == "kt":  # texto digitado
            self.keyboard.type_text(str(msg.get("text", "")))
        elif kind == "ping":  # latencia (o app manda junto dos eventos)
            await conn.send(MSG_PONG, json.dumps({"ts": msg.get("ts", 0)}).encode())
        elif kind == "r":  # reconfigurar qualidade/tamanho/fps
            if "width" in msg:
                session.width = max(320, min(2560, int(msg["width"])))
            if "quality" in msg:
                session.quality = max(20, min(95, int(msg["quality"])))
            if "fps" in msg:
                session.fps = max(5, min(60, int(msg["fps"])))
            log(f"qualidade ajustada: {session.width}px q{session.quality} {session.fps}fps")
        elif kind == "mon":  # trocar de monitor
            index = int(msg.get("i", 1))
            monitors = self.grabber.monitors()
            if 0 < index < len(monitors):
                self.grabber.monitor_index = index
                self.grabber.reset_cache()
                session.monitor = index
                mon = monitors[index]
                self.mouse.set_bbox((mon["left"], mon["top"], mon["width"], mon["height"]))
                await conn.send_json(
                    MSG_SCREEN,
                    {
                        "w": mon["width"],
                        "h": mon["height"],
                        "monitor": index,
                        "monitors": len(monitors) - 1,
                    },
                )
                log(f"monitor alterado para {index}")

    # -------------------------------------------------------------- conexao

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername") or ("?", 0)
        ip = str(peer[0])
        conn = Conn(reader, writer)

        # Teto no buffer do kernel: mantem a fila de envio curta para o controle
        # de fluxo (que olha o buffer do asyncio) enxergar a congestao cedo.
        raw_socket = writer.get_extra_info("socket")
        if raw_socket is not None:
            try:
                raw_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SEND_BUFFER_BYTES)
            except OSError:
                pass

        log(f"conexao de {ip}")

        stream_task: asyncio.Task | None = None
        try:
            bloqueio = self.limiter.blocked_for(ip)
            if bloqueio > 0:
                await conn.send_json(
                    MSG_INFO,
                    {
                        "error": "muitas tentativas de PIN; "
                        f"tente de novo em {int(bloqueio) + 1}s"
                    },
                )
                log(f"conexao de {ip} recusada: bloqueado por mais {bloqueio:.0f}s")
                return

            # 1) Desafio: nonce novo a cada conexao. Sem ele, um MAC capturado
            #    nao pode ser reaproveitado (replay).
            nonce = security.new_nonce()
            await conn.send_json(
                MSG_CHALLENGE, security.challenge_json(self.pin_record, nonce)
            )

            # 2) HELLO com HMAC-SHA256(chave_do_PIN, nonce), dentro do prazo.
            mtype, payload = await asyncio.wait_for(
                read_msg(reader), timeout=HELLO_TIMEOUT
            )
            if mtype != MSG_HELLO:
                await conn.send_json(MSG_INFO, {"error": "esperado HELLO"})
                log(f"conexao de {ip} recusada: primeira mensagem nao foi HELLO")
                return

            try:
                hello = json.loads(payload)
            except json.JSONDecodeError:
                hello = None
            if not isinstance(hello, dict):
                await conn.send_json(MSG_INFO, {"error": "HELLO invalido"})
                log(f"HELLO invalido de {ip}")
                return

            mac = hello.get("mac")
            if not isinstance(mac, str) or not security.verify_mac(
                self.pin_record, nonce, mac
            ):
                info = self.limiter.failure(ip)
                extra = (
                    f", bloqueado por {info.blocked_for:.0f}s"
                    if info.blocked_for > 0
                    else ""
                )
                log(
                    f"autenticacao falhou de {ip} "
                    f"(tentativa {info.attempts}, atraso {info.delay:.0f}s{extra})"
                )
                try:
                    await conn.send_json(
                        MSG_INFO, {"error": "autenticacao falhou", "delay": info.delay}
                    )
                except (ConnectionError, OSError):
                    pass
                # atraso progressivo (1s, 2s, 4s...): encarece a forca bruta
                await asyncio.sleep(info.delay)
                return

            self.limiter.success(ip)

            session = Session(
                name=str(hello.get("name", "celular"))[:32],
                width=_clamp_int(hello.get("width"), self.args.width, 320, 2560),
                quality=_clamp_int(hello.get("quality"), self.args.quality, 20, 95),
                fps=_clamp_int(hello.get("fps"), self.args.fps, 5, 60),
                monitor=_clamp_int(hello.get("monitor"), self.args.monitor, 1, 16),
            )
            monitors = self.grabber.monitors()
            ultimo = len(monitors) - 1
            if ultimo >= 1:
                session.monitor = min(max(1, session.monitor), ultimo)
            else:
                session.monitor = 0
            self.grabber.monitor_index = session.monitor
            self.grabber.reset_cache()

            mon = monitors[session.monitor]
            self.mouse.set_bbox((mon["left"], mon["top"], mon["width"], mon["height"]))

            await conn.send_json(
                MSG_SCREEN,
                {
                    "name": socket.gethostname(),
                    "version": VERSION,
                    "w": mon["width"],
                    "h": mon["height"],
                    "monitor": session.monitor,
                    "monitors": max(0, ultimo),
                    "tls": self.tls_enabled,
                },
            )
            log(
                f"app conectado: {session.name} ({ip}) | {session.width}px "
                f"q{session.quality} {session.fps}fps"
            )

            stream_task = asyncio.create_task(self.stream(conn, session))
            await self.input_loop(conn, session)

        except asyncio.IncompleteReadError:
            pass
        except asyncio.TimeoutError:
            log(f"timeout esperando o HELLO de {ip} ({HELLO_TIMEOUT:.0f}s)")
        except ValueError as exc:
            # cabecalho de tamanho invalido (tentativa de alocar memoria demais)
            log(f"conexao de {ip} encerrada: {exc}")
        except (ConnectionError, OSError):
            pass
        except Exception as exc:  # noqa: BLE001
            log(f"erro na conexao de {ip}: {exc!r}")
        finally:
            if stream_task is not None:
                stream_task.cancel()
                try:
                    await stream_task
                except BaseException:
                    pass
            conn.close()
            log(f"desconectado {ip}")

    # -------------------------------------------------------------- descoberta

    async def discovery(self) -> None:
        loop = asyncio.get_running_loop()
        port = self.args.port
        dport = self.args.discovery_port

        class Protocol(asyncio.DatagramProtocol):
            def connection_made(self, transport) -> None:  # type: ignore[override]
                self.transport = transport

            def datagram_received(self, data: bytes, addr: tuple) -> None:  # type: ignore[override]
                if data.strip() != DISCOVERY_MAGIC:
                    return
                info = {
                    "app": "localcontrol",
                    "name": socket.gethostname(),
                    "port": port,
                    "version": VERSION,
                    "tls": self.tls_enabled,
                }
                self.transport.sendto(json.dumps(info).encode(), addr)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", dport))
        sock.setblocking(False)
        transport, _ = await loop.create_datagram_endpoint(Protocol, sock=sock)
        self._discovery_transport = transport
        log(f"descoberta UDP ativa na porta {dport}")

    # -------------------------------------------------------------- run

    async def run(self, ssl_ctx=None) -> None:
        extra = {}
        if ssl_ctx is not None:
            extra = {"ssl": ssl_ctx, "ssl_handshake_timeout": HELLO_TIMEOUT}
        server = await asyncio.start_server(
            self.handle_client, host=self.args.bind, port=self.args.port, **extra
        )
        try:
            await self.discovery()
        except OSError as exc:
            log(f"aviso: descoberta UDP indisponivel ({exc}); conecte pelo IP")

        for ip in local_ips():
            log(f"ouvindo em {ip}:{self.args.port}")
        log("pronto. Abra o app no celular e conecte.")
        log(
            "USB: rode  adb reverse tcp:%d tcp:%d  e use 127.0.0.1"
            % (self.args.port, self.args.port)
        )

        async with server:
            await server.serve_forever()


def local_ips() -> list[str]:
    ips: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass
    return ips or ["127.0.0.1"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Servidor de controle remoto local",
        epilog="O PIN e configurado uma vez com --set-pin e fica salvo em pin.txt.",
    )
    parser.add_argument("--port", type=int, default=8765, help="porta TCP (padrao 8765)")
    parser.add_argument(
        "--discovery-port",
        type=int,
        default=DISCOVERY_PORT,
        help=f"porta UDP de descoberta (padrao {DISCOVERY_PORT})",
    )
    parser.add_argument("--bind", default="0.0.0.0", help="interface de escuta")
    parser.add_argument("--monitor", type=int, default=1, help="monitor inicial (1 = principal)")
    parser.add_argument("--width", type=int, default=1600, help="largura inicial do video")
    parser.add_argument("--quality", type=int, default=70, help="qualidade JPEG inicial")
    parser.add_argument("--fps", type=int, default=30, help="fps inicial")
    parser.add_argument("--no-gpu", action="store_true", help="forcar captura GDI (mss)")
    parser.add_argument(
        "--set-pin",
        action="store_true",
        help="define/troca o PIN (pede no terminal) e sai",
    )
    parser.add_argument(
        "--pin",
        default="",
        help="PIN para usar junto de --set-pin (evite: fica no historico)",
    )
    parser.add_argument(
        "--no-tls",
        action="store_true",
        help="desliga o TLS (APENAS diagnostico; exige PIN de 8+ caracteres)",
    )
    parser.add_argument("--cert", default=str(CERT_PATH), help="certificado PEM")
    parser.add_argument("--key", default=str(KEY_PATH), help="chave privada PEM")
    return parser.parse_args()


def configure_pin(tls_enabled: bool, provided: str) -> int:
    """Cria/troca o PIN e devolve o codigo de saida do processo."""
    if provided:
        pin = provided
    else:
        try:
            pin = getpass.getpass("Novo PIN: ")
            repetido = getpass.getpass("Repita o PIN: ")
        except (KeyboardInterrupt, EOFError):
            print("\ncancelado.")
            return 1
        if pin != repetido:
            print("os PINs nao conferem.")
            return 1

    try:
        record = security.save_pin(PIN_PATH, pin, tls_enabled=tls_enabled)
    except (ValueError, security.PinFileError) as exc:
        print(f"erro: {exc}")
        return 1

    modo = "com TLS" if tls_enabled else "SEM TLS (--no-tls)"
    minimo = security.MIN_PIN_TLS if tls_enabled else security.MIN_PIN_PLAIN
    print(f"PIN salvo em {PIN_PATH} ({modo}).")
    print(
        "O PIN nao e gravado: pin.txt guarda apenas a chave derivada "
        f"(PBKDF2-HMAC-SHA256, {record.iterations} iteracoes)."
    )
    print(f"Minimo neste modo: {minimo} caracteres.")
    if record.requires_tls:
        print("PIN curto: so sera aceito com TLS ativo.")
    print("Reinicie o servidor para o novo PIN valer.")
    return 0


def main() -> None:
    if sys.platform != "win32":
        print("Este servidor usa APIs do Windows (SendInput). Rode no Windows.")
        raise SystemExit(1)

    setup_logging()
    _silence_comtypes_shutdown()

    args = parse_args()
    tls_enabled = not args.no_tls
    cert_path = Path(args.cert)
    key_path = Path(args.key)

    if args.pin and not args.set_pin:
        print("erro: --pin na linha de comando ficaria visivel no historico.")
        print("       use  server.py --set-pin  (o PIN fica salvo em pin.txt).")
        raise SystemExit(2)

    if args.set_pin:
        raise SystemExit(configure_pin(tls_enabled, args.pin))

    try:
        pin_record = security.load_pin(PIN_PATH)
    except security.PinFileError as exc:
        print(f"erro: {exc}")
        raise SystemExit(1)

    if pin_record is None:
        print(f"nenhum PIN configurado ({PIN_PATH}).")
        print("rode:  server.py --set-pin")
        raise SystemExit(1)

    if pin_record.requires_tls and not tls_enabled:
        print("erro: o PIN salvo e curto (4 a 7 caracteres) e exige TLS.")
        print("       rode com TLS, ou defina um PIN de 8+ caracteres:")
        print("       server.py --no-tls --set-pin")
        raise SystemExit(1)

    ssl_ctx = None
    fingerprint = ""
    if tls_enabled:
        try:
            novo = security.ensure_certificate(cert_path, key_path)
            ssl_ctx = security.build_ssl_context(cert_path, key_path)
            fingerprint = security.spki_fingerprint(cert_path)
        except Exception as exc:  # noqa: BLE001
            print(f"erro ao preparar o TLS: {exc}")
            print("para diagnostico sem TLS: server.py --no-tls (exige PIN de 8+)")
            raise SystemExit(1)

    wininput.init_dpi()

    banner = r"""
  _                    _    ___            _             _
 | |   ___   ___ __ _  | |  / __|___  _ _ | |_ _ _ _ _  | |_ ___
 | |__/ _ \ / __/ _` | | |_| (__/ _ \| ' \|  _| '_| ' \ |  _/ _ \
 |____\___/ \___\__,_| |____\___\___/|_||_|\__|_| |_||_| \__\___/
        controle remoto local do seu PC pelo celular
"""
    print(banner)
    log(f"versao {VERSION}")

    if tls_enabled:
        log("TLS 1.3 ativo (certificado ECDSA P-256).")
        if novo:
            log(f"certificado novo em {cert_path}")
        log("impressao digital da chave publica (confira no app):")
        log("  " + security.format_fingerprint(fingerprint))
    else:
        log("AVISO: TLS DESATIVADO (--no-tls): o trafego vai em texto claro.")
        log("       use apenas para diagnostico em rede confiavel.")

    limiter = security.RateLimiter(STATE_PATH)

    server: Server | None = None
    try:
        server = Server(args, pin_record, limiter, tls_enabled)
        asyncio.run(server.run(ssl_ctx))
    except KeyboardInterrupt:
        print()
        log("encerrado.")
    except Exception:  # noqa: BLE001
        logger.exception("erro fatal")
        raise SystemExit(1)
    finally:
        # libera dxcam/mss antes do interpretador desmontar os objetos COM
        if server is not None:
            server.grabber.close()
        logging.shutdown()


if __name__ == "__main__":
    main()
