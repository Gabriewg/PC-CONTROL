#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
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
  0x12 INFO     : JSON {"warn":"secure_desktop"|"admin_window","on":bool}
                  (aviso nao fatal; {"error":...} continua sendo fatal)
  0x13 PING     : JSON {"ts": ...}   (cliente -> servidor)
  0x14 PONG     : JSON {"ts": ...}   (servidor -> cliente)
  0x15 CHALLENGE: JSON {"nonce","salt","iter","kdf"} enviado antes do HELLO
  0x16 PAIR_OK  : JSON {"id","key","name"} apos pareamento por QR (so uma vez)

O PIN nunca trafega: o servidor manda um nonce novo a cada conexao e o app
responde com HMAC-SHA256(chave_derivada_do_PIN, nonce). O pin.txt guarda apenas
o resultado da KDF (PBKDF2-HMAC-SHA256 com salt).

O pareamento por QR usa um token de uso unico (2 a 5 minutos). O app prova que
tem o token com HMAC-SHA256(token, nonce) e recebe do servidor uma chave
exclusiva do aparelho; nas conexoes seguintes ele autentica com essa chave, sem
precisar do PIN.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import io
import ipaddress
import json
import logging
import os
import socket
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
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
MSG_PAIR_OK = 0x16

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

VERSION = "1.5"

# Arquivos locais ficam ao lado do server.py (nao dependem do diretorio atual).
# Nenhum deles vai para o Git: veja .gitignore.
BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = str(BASE_DIR / "server.log")
PIN_PATH = BASE_DIR / "pin.txt"
CERT_PATH = BASE_DIR / "cert.pem"
KEY_PATH = BASE_DIR / "key.pem"
STATE_PATH = BASE_DIR / "auth_state.json"
DEVICES_PATH = BASE_DIR / "devices.json"
PAIR_IMAGE_PATH = BASE_DIR / "pair.png"
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
        # Depois de um erro do DXGI (ACCESS_LOST quando o Windows troca para a
        # area segura) tentamos recriar o duplicador em vez de desligar a GPU
        # para sempre. Enquanto isso o GDI mantem o video vivo.
        self._gpu_retry_at = 0.0
        self._gpu_error_logged = False
        self._gdi_error_logged = False
        self._dxgi_create_logged = False
        self._black_since = 0.0
        self._last_capture_at = 0.0
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

        criados = 0
        for out_idx in candidates:
            try:
                cam = dxcam.create(output_idx=out_idx, output_color="BGR")
            except Exception as exc:  # noqa: BLE001
                if not self._dxgi_create_logged:
                    log(f"output DXGI {out_idx} indisponivel ({exc!r})")
                    self._dxgi_create_logged = True
                continue
            criados += 1
            self._dxgi_create_logged = False
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

        if criados == 0:
            # Provavelmente a area segura esta ativa e o DXGI nao pode ser
            # aberto agora. Nao desliga a GPU para sempre: tenta de novo.
            self._gpu_retry_at = time.monotonic() + 2.0
            self.backend = "gdi"
            return None

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
        self._last_capture_at = time.monotonic()
        monitors = self._ordered_monitors()
        index = self.monitor_index if 0 < self.monitor_index < len(monitors) else 1
        mon = monitors[index]
        self.bbox = (mon["left"], mon["top"], mon["width"], mon["height"])

        arr = None
        is_bgr = False
        now = time.monotonic()

        if not self._gpu_disabled and now >= self._gpu_retry_at:
            cam = self._camera(index)
            if cam is not None:
                try:
                    arr = cam.grab()
                except Exception as exc:  # noqa: BLE001
                    # ACCESS_LOST/E_ACCESSDENIED acontecem quando o Windows
                    # troca para a area segura. Nao desliga a GPU para sempre:
                    # usa GDI agora e tenta recriar o duplicador em 2 s.
                    self._drop_camera()
                    self._gpu_retry_at = time.monotonic() + 2.0
                    self.backend = "gdi"
                    if not self._gpu_error_logged:
                        log(
                            "captura DXGI interrompida "
                            f"({exc!r}); usando GDI e tentando de novo"
                        )
                        self._gpu_error_logged = True
                    arr = None
                else:
                    if self._gpu_error_logged:
                        log("captura DXGI recuperada")
                        self._gpu_error_logged = False
                    is_bgr = True
                    if arr is None:
                        # nada mudou na tela: reaproveita o ultimo JPEG
                        if self._cache is not None and self._cache_kw == (width, quality):
                            return self._cache, False

        if arr is None:
            try:
                arr = np.asarray(self._open_mss().grab(mon))
            except Exception as exc:  # noqa: BLE001
                # Durante UAC/bloqueio o GDI tambem pode falhar. Nao derruba a
                # conexao: o monitor avisa o app e o video volta sozinho.
                if not self._gdi_error_logged:
                    log(f"captura GDI falhou ({exc!r}); mantendo a conexao")
                    self._gdi_error_logged = True
                return None, False
            if self._gdi_error_logged:
                log("captura GDI recuperada")
                self._gdi_error_logged = False
            is_bgr = False

        if self._is_black(arr):
            if self._black_since <= 0.0:
                self._black_since = time.monotonic()
        else:
            self._black_since = 0.0

        jpeg = self._encode(arr, is_bgr, width, quality)
        self._cache = jpeg
        self._cache_kw = (width, quality)
        self.last_grab_ms = (time.perf_counter() - t0) * 1000.0
        return jpeg, True

    @staticmethod
    def _is_black(arr: np.ndarray) -> bool:
        """Quadro 100% preto? (ignora o canal alfa do mss, que vem em 255)"""
        try:
            pixels = arr[:, :, :3] if arr.ndim == 3 else arr
            return bool(pixels.size) and int(pixels.max()) <= 2
        except Exception:  # noqa: BLE001
            return False

    def black_for(self) -> float:
        """Ha quantos segundos a captura esta 100% preta (0 = nao esta)."""
        if self._black_since <= 0.0:
            return 0.0
        # Sem capturas recentes o dado e' velho: nao acusa tela preta a toa.
        if time.monotonic() - self._last_capture_at > 2.0:
            return 0.0
        return time.monotonic() - self._black_since

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


class ProtectionMonitor:
    """Detecta tela protegida (UAC/bloqueio/login) e janela elevada.

    Roda em uma thread propria a cada 0.5 s para nao competir com a captura.
    O callback recebe "secure_desktop", "admin_window" ou None e so e' chamado
    quando o estado muda, depois de 3 verificacoes iguais (histerese).
    """

    def __init__(self, grabber: Grabber, on_change, interval: float = 0.5) -> None:
        self._grabber = grabber
        self._on_change = on_change
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._candidate: str | None = None
        self._hits = 0
        self._state: str | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="lc-guard", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _sample(self) -> str | None:
        try:
            estado = wininput.input_desktop_state()
        except Exception:  # noqa: BLE001
            estado = None
        if estado is True:
            return "secure_desktop"
        # Reserva: quadros 100% pretos por mais de 1 s. A area segura do Windows
        # costuma devolver preto tanto no DXGI quanto no GDI.
        if self._grabber.black_for() >= 1.0:
            return "secure_desktop"
        try:
            if wininput.foreground_is_elevated():
                return "admin_window"
        except Exception:  # noqa: BLE001
            pass
        return None

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            kind = self._sample()
            if kind == self._candidate:
                self._hits += 1
            else:
                self._candidate = kind
                self._hits = 1
            # 3 verificacoes iguais (~1,5 s) evitam piscar o aviso.
            if self._hits >= 3 and kind != self._state:
                self._state = kind
                try:
                    self._on_change(kind)
                except Exception:  # noqa: BLE001
                    pass


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

    async def send_json(self, mtype: int, obj: dict, *, drain: bool = True) -> None:
        await self.send(mtype, json.dumps(obj, separators=(",", ":")).encode(), drain=drain)

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
        *,
        tokens: security.PairingTokens | None = None,
        devices: security.DeviceStore | None = None,
        fingerprint: str = "",
        activity_cb=None,
    ) -> None:
        self.args = args
        self.pin_record = pin_record
        self.limiter = limiter
        self.tls_enabled = tls_enabled
        self.grabber = Grabber(use_gpu=not args.no_gpu)
        self.grabber.monitor_index = args.monitor
        self.mouse = wininput.Mouse()
        self.keyboard = wininput.Keyboard()

        self.tokens = tokens or security.PairingTokens(
            getattr(args, "pair_ttl", security.PAIR_TTL)
        )
        self.devices = devices or security.DeviceStore(DEVICES_PATH)
        self.fingerprint = fingerprint
        self.activity_cb = activity_cb

        self.loop: asyncio.AbstractEventLoop | None = None
        self.tray = None
        self.last_pairing_uri = ""
        self.last_pairing_expires = 0.0
        self._stop_event: asyncio.Event | None = None
        self._discovery_transport = None
        self._sessions: dict[int, tuple[str, str, float]] = {}
        self._session_seq = 0
        # Aviso de tela protegida/janela elevada: enviado uma vez quando muda.
        self._warning: str | None = None
        self._warning_seq = 0
        self._guard: ProtectionMonitor | None = None

    # -------------------------------------------------------------- aviso no PC

    def _activity_changed(self) -> None:
        """Atualiza o icone/notificacao do PC quando alguem conecta ou sai."""
        count = len(self._sessions)
        nomes = ", ".join(sorted({name for name, _ip, _t in self._sessions.values()}))
        if self.activity_cb is not None:
            try:
                self.activity_cb(count, nomes)
            except Exception:  # noqa: BLE001
                pass
        elif self.tray is not None:
            try:
                self.tray.update(count, nomes)
            except Exception:  # noqa: BLE001
                pass
        else:
            _set_console_title(count, nomes)

    def _session_started(self, name: str, ip: str) -> int:
        self._session_seq += 1
        key = self._session_seq
        self._sessions[key] = (name, ip, time.time())
        log(f">>> CONEXAO ATIVA: {name} ({ip}) | {len(self._sessions)} ativa(s)")
        self._activity_changed()
        return key

    def _session_ended(self, key: int) -> None:
        self._sessions.pop(key, None)
        self._activity_changed()

    def _set_warning(self, kind: str | None) -> None:
        """Muda o aviso global; cada stream envia o novo estado uma vez."""
        if kind == self._warning:
            return
        self._warning = kind
        self._warning_seq += 1
        if kind == "secure_desktop":
            log("tela protegida pelo Windows (UAC/bloqueio/login); avisando o app")
        elif kind == "admin_window":
            log("janela de administrador em primeiro plano; entrada pode ser ignorada")
        else:
            log("tela normalizada; video e controle remoto de volta")

    # -------------------------------------------------------------- pareamento

    def pairing_host(self) -> str:
        bind = str(getattr(self.args, "bind", "0.0.0.0"))
        if bind not in ("0.0.0.0", "::", ""):
            return bind
        ips = local_ips()
        # Prefere um IP de LAN privado; Tailscale (100.64/10) fica por ultimo
        # porque o QR normalmente e lido com o celular na mesma rede Wi-Fi.
        for ip in ips:
            if _is_lan_ip(ip):
                return ip
        return ips[0]

    def show_pairing(self, open_image: bool = False) -> str:
        """Gera um token novo e mostra o QR (console + pair.png)."""
        if not self.fingerprint:
            print(
                "pareamento por QR indisponivel: o TLS esta desligado (--no-tls).\n"
                "Ligue o TLS para o app conseguir fixar a chave do PC."
            )
            return ""

        # Um novo QR invalida os anteriores: se um deles vazou, deixa de valer.
        self.tokens.clear()
        item = self.tokens.create()
        host = self.pairing_host()
        uri = security.pairing_uri(
            host, self.args.port, self.fingerprint, item.token, socket.gethostname()
        )
        self.last_pairing_uri = uri
        self.last_pairing_expires = item.expires

        print()
        print("=" * 62)
        print(" PAREAMENTO POR QR")
        print(f" Aparelho: {socket.gethostname()}  ({host}:{self.args.port})")
        print(f" Valido por {int(self.tokens.ttl)}s e somente UMA vez.")
        print("=" * 62)
        print(uri)
        print()
        _print_qr(uri)
        if _save_pair_image(uri, PAIR_IMAGE_PATH):
            print(f"QR salvo em {PAIR_IMAGE_PATH}")
        if open_image:
            try:
                os.startfile(PAIR_IMAGE_PATH)  # type: ignore[attr-defined]
            except OSError as exc:
                log(f"nao consegui abrir {PAIR_IMAGE_PATH}: {exc}")
        return uri

    def print_devices(self) -> None:
        recs = self.devices.all()
        if not recs:
            print("nenhum aparelho pareado.")
            return
        print(f"{len(recs)} aparelho(s) pareado(s):")
        for rec in recs:
            quando = datetime.fromtimestamp(rec.created).strftime("%d/%m/%Y %H:%M")
            visto = (
                datetime.fromtimestamp(rec.last_seen).strftime("%d/%m/%Y %H:%M")
                if rec.last_seen
                else "nunca"
            )
            print(f"  {rec.id}  {rec.name:<16}  pareado em {quando}  ultimo uso {visto}")

    def forget_devices(self) -> None:
        quantidade = len(self.devices.all())
        self.devices.clear()
        self.tokens.clear()
        log(f"{quantidade} aparelho(s) pareado(s) esquecido(s); QR antigos invalidados")
        print(f"{quantidade} aparelho(s) esquecido(s).")

    def request_pairing(self, open_image: bool = True) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.show_pairing, open_image)

    def request_devices(self) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.print_devices)

    def request_forget(self) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.forget_devices)

    def request_stop(self) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.stop)

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    def start_console(self) -> None:
        """Comandos no console: q = novo QR, d = aparelhos, x = sair."""
        if sys.stdin is None or not sys.stdin.isatty():
            return
        print("Comandos: q = novo QR de pareamento | d = aparelhos | x = sair")

        def reader() -> None:
            try:
                for line in sys.stdin:
                    cmd = line.strip().lower()
                    if self.loop is None:
                        break
                    if cmd in ("q", "qr", "p", "pair", "parear"):
                        self.loop.call_soon_threadsafe(self.show_pairing, False)
                    elif cmd in ("d", "devices", "aparelhos"):
                        self.loop.call_soon_threadsafe(self.print_devices)
                    elif cmd in ("x", "sair", "quit", "exit"):
                        self.loop.call_soon_threadsafe(self.stop)
                        break
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=reader, name="lc-console", daemon=True).start()

    def start_tray(self) -> None:
        if getattr(self.args, "no_tray", False):
            return
        try:
            import tray as tray_module

            self.tray = tray_module.start(self)
        except Exception as exc:  # noqa: BLE001
            log(f"aviso: icone de bandeja indisponivel ({exc})")
            self.tray = None

    # -------------------------------------------------------------- video

    async def stream(self, conn: Conn, session: Session) -> None:
        interval = 1.0 / max(1, session.fps)
        last_sent = 0.0
        last_cursor: tuple[int, int] | None = None
        frames = 0
        mark = time.perf_counter()
        congested = False
        warning_seq = -1
        warning_sent = False

        while True:
            t0 = time.perf_counter()

            # Aviso de tela protegida/janela elevada: so quando o estado muda.
            # Vai antes do controle de fluxo para nao ficar preso atras do video.
            if self._warning_seq != warning_seq:
                warning_seq = self._warning_seq
                warn = self._warning
                if warn is not None:
                    await conn.send_json(
                        MSG_INFO,
                        {"warn": warn, "on": True},
                        drain=conn.backlog() < FLOW_LOW_BYTES,
                    )
                    warning_sent = True
                elif warning_sent:
                    await conn.send_json(
                        MSG_INFO,
                        {"warn": "", "on": False},
                        drain=conn.backlog() < FLOW_LOW_BYTES,
                    )
                    warning_sent = False

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

    async def _reject_auth(self, conn: Conn, ip: str, reason: str) -> None:
        info = self.limiter.failure(ip)
        extra = (
            f", bloqueado por {info.blocked_for:.0f}s" if info.blocked_for > 0 else ""
        )
        log(
            f"autenticacao falhou de {ip} ({reason}; "
            f"tentativa {info.attempts}, atraso {info.delay:.0f}s{extra})"
        )
        try:
            await conn.send_json(
                MSG_INFO, {"error": reason, "delay": info.delay}
            )
        except (ConnectionError, OSError):
            pass
        # atraso progressivo (1s, 2s, 4s...): encarece a forca bruta
        await asyncio.sleep(info.delay)

    async def authenticate(
        self, conn: Conn, ip: str, nonce: bytes, hello: dict
    ) -> bool:
        """Valida PIN, chave de aparelho ou token de pareamento."""
        mac = hello.get("mac")
        pid = hello.get("pid")
        device_id = hello.get("device")

        # 1) Pareamento por QR: HMAC(token, nonce), token de uso unico.
        if isinstance(pid, str) and pid:
            if not isinstance(mac, str) or not self.tokens.verify_and_consume(
                pid, nonce, mac
            ):
                await self._reject_auth(conn, ip, "pareamento invalido ou expirado")
                return False
            nome = str(hello.get("name", "celular"))[:32]
            rec = self.devices.add(nome)
            await conn.send_json(
                MSG_PAIR_OK,
                {
                    "v": 1,
                    "id": rec.id,
                    "key": security.b64e(rec.key),
                    "name": rec.name,
                },
            )
            log(f"pareamento concluido: {rec.name} ({ip}) id {rec.id}")
            self.limiter.success(ip)
            return True

        # 2) Aparelho ja pareado: HMAC(chave_do_aparelho, nonce).
        if isinstance(device_id, str) and device_id:
            if not isinstance(mac, str) or not self.devices.verify(
                device_id, nonce, mac
            ):
                await self._reject_auth(conn, ip, "aparelho nao reconhecido")
                return False
            rec = self.devices.get(device_id)
            log(f"aparelho pareado autenticado: {rec.name if rec else device_id} ({ip})")
            self.limiter.success(ip)
            return True

        # 3) PIN (compatibilidade e conexao manual).
        if not isinstance(mac, str) or not security.verify_mac(
            self.pin_record, nonce, mac
        ):
            await self._reject_auth(conn, ip, "autenticacao falhou")
            return False
        self.limiter.success(ip)
        return True

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
        session_key: int | None = None
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

            # 2) HELLO com HMAC (PIN, chave do aparelho ou token de pareamento).
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

            if not await self.authenticate(conn, ip, nonce, hello):
                return

            session = Session(
                name=str(hello.get("name", "celular"))[:32],
                width=_clamp_int(hello.get("width"), self.args.width, 320, 2560),
                quality=_clamp_int(hello.get("quality"), self.args.quality, 20, 95),
                fps=_clamp_int(hello.get("fps"), self.args.fps, 5, 60),
                monitor=_clamp_int(hello.get("monitor"), self.args.monitor, 1, 16),
            )
            session_key = self._session_started(session.name, ip)
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
            if session_key is not None:
                self._session_ended(session_key)
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
        self.loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()

        # Detecta UAC/bloqueio/login e janelas elevadas desde o inicio, para que
        # um app que conecte no meio do aviso ja receba o estado atual.
        self._guard = ProtectionMonitor(self.grabber, self._set_warning)
        self._guard.start()

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

        self.start_tray()
        self.start_console()
        if not getattr(self.args, "no_qr", False):
            self.show_pairing(open_image=getattr(self.args, "qr_open", False))

        try:
            await self._stop_event.wait()
        finally:
            server.close()
            try:
                await server.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            if self._discovery_transport is not None:
                try:
                    self._discovery_transport.close()
                except Exception:  # noqa: BLE001
                    pass
            if self.tray is not None:
                try:
                    self.tray.stop()
                except Exception:  # noqa: BLE001
                    pass
            if self._guard is not None:
                self._guard.stop()
                self._guard = None
            _set_console_title(0, "")


def _is_lan_ip(ip: str) -> bool:
    """IP privado de LAN (exclui Tailscale/CGNAT 100.64/10)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version != 4:
        return False
    if ip.startswith("100."):
        return False
    return addr.is_private and not addr.is_loopback and not addr.is_link_local


def _set_console_title(count: int, names: str = "") -> None:
    """Fallback quando nao ha icone de bandeja: avisa no titulo do console."""
    if os.name != "nt":
        return
    try:
        import ctypes

        if count <= 0:
            text = "Local Control - nenhuma conexao ativa"
        elif count == 1:
            text = f"Local Control - CONECTADO: {names}"
        else:
            text = f"Local Control - {count} conexoes ativas: {names}"
        ctypes.windll.kernel32.SetConsoleTitleW(text)
    except Exception:  # noqa: BLE001
        pass


def _print_qr(uri: str) -> None:
    """Desenha o QR no terminal (blocos Unicode)."""
    try:
        import qrcode
    except ImportError:
        print("(instale 'qrcode' para ver o QR no terminal: pip install qrcode)")
        return
    try:
        qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(uri)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception as exc:  # noqa: BLE001
        print(f"(nao foi possivel desenhar o QR: {exc})")


def _save_pair_image(uri: str, path: Path) -> bool:
    try:
        import qrcode

        img = qrcode.make(uri)
        img.save(path)
        security.restrict_permissions(path)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"aviso: nao consegui salvar {path}: {exc}")
        return False


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
    parser.add_argument(
        "--pair-ttl",
        type=int,
        default=int(security.PAIR_TTL),
        help="validade do QR de pareamento em segundos (30 a 600; padrao 180)",
    )
    parser.add_argument(
        "--no-qr",
        action="store_true",
        help="nao mostra o QR de pareamento ao iniciar (use q no console)",
    )
    parser.add_argument(
        "--qr-open",
        action="store_true",
        help="abre a imagem do QR (pair.png) ao iniciar",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="nao usa o icone de bandeja (aviso de conexao so no console)",
    )
    parser.add_argument(
        "--forget-devices",
        action="store_true",
        help="esquece todos os aparelhos pareados e sai",
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

    devices = security.DeviceStore(DEVICES_PATH)
    if args.forget_devices:
        quantidade = len(devices.all())
        devices.clear()
        print(f"{quantidade} aparelho(s) pareado(s) esquecido(s).")
        print("Os aparelhos precisarao parear de novo (QR ou PIN).")
        return

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
    tokens = security.PairingTokens(args.pair_ttl)

    server: Server | None = None
    try:
        server = Server(
            args,
            pin_record,
            limiter,
            tls_enabled,
            tokens=tokens,
            devices=devices,
            fingerprint=fingerprint,
        )
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
