# SPDX-License-Identifier: AGPL-3.0-or-later
"""Host do servidor para a janela: liga/desliga sem console e sem .bat."""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import logging
import queue
import threading
from pathlib import Path

import security
import server as srv

log = logging.getLogger("localcontrol")


class HostError(RuntimeError):
    """Falha esperada ao ligar o servidor (PIN, porta, certificado...)."""


class ServerHost:
    """Mantem o servidor Python rodando em uma thread propria.

    A janela so' conversa com esta classe: nada de bloquear o loop do Tk com
    asyncio, e nada de console. Os eventos chegam pela fila `events`.
    """

    def __init__(
        self,
        data_dir: Path,
        *,
        port: int = 8765,
        discovery_port: int = 8766,
        no_gpu: bool = False,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.port = port
        self.discovery_port = discovery_port
        self.no_gpu = no_gpu

        self.events: queue.Queue = queue.Queue()
        self.devices = security.DeviceStore(self.data_dir / "devices.json")
        self.limiter = security.RateLimiter(self.data_dir / "auth_state.json")
        self.tokens = security.PairingTokens(180)

        self.server: srv.Server | None = None
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ssl_ctx = None
        self.pin_record: security.PinRecord | None = None
        self.fingerprint = ""
        self.host = ""
        self.ready = False
        self._lock = threading.Lock()

        try:
            self.pin_record = security.load_pin(self.data_dir / "pin.txt")
        except security.PinFileError:
            self.pin_record = None
        cert = self.data_dir / "cert.pem"
        if cert.exists():
            try:
                self.fingerprint = security.spki_fingerprint(cert)
            except Exception:  # noqa: BLE001
                self.fingerprint = ""

    # ------------------------------------------------------------ estado

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    @property
    def has_pin(self) -> bool:
        return self.pin_record is not None

    def guess_host(self) -> str:
        if self.host:
            return self.host
        try:
            ips = srv.local_ips()
        except Exception:  # noqa: BLE001
            return "127.0.0.1"
        for ip in ips:
            if srv._is_lan_ip(ip):  # noqa: SLF001 - mesmo pacote
                return ip
        return ips[0] if ips else "127.0.0.1"

    # ------------------------------------------------------------ ciclo de vida

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self.ready = False
            self.events.put(("starting",))
            self.thread = threading.Thread(
                target=self._thread_main, name="pd-server", daemon=True
            )
            self.thread.start()

    def _thread_main(self) -> None:
        try:
            self._prepare()
            asyncio.run(self._serve())
        except HostError as exc:
            self.events.put(("error", str(exc)))
        except Exception as exc:  # noqa: BLE001
            log.exception("falha inesperada no servidor")
            self.events.put(("error", f"{type(exc).__name__}: {exc}"))
        finally:
            self.ready = False
            servidor = self.server
            self.server = None
            self.loop = None
            if servidor is not None:
                try:
                    servidor.grabber.close()
                except Exception:  # noqa: BLE001
                    pass
            self.events.put(("stopped",))

    def _prepare(self) -> None:
        if self.pin_record is None:
            self.pin_record = security.load_pin(self.data_dir / "pin.txt")
        if self.pin_record is None:
            raise HostError("Defina um PIN para ligar o servidor.")

        cert = self.data_dir / "cert.pem"
        key = self.data_dir / "key.pem"
        try:
            security.ensure_certificate(cert, key)
            self.ssl_ctx = security.build_ssl_context(cert, key)
            self.fingerprint = security.spki_fingerprint(cert)
        except Exception as exc:  # noqa: BLE001
            raise HostError(f"Nao foi possivel preparar o TLS: {exc}") from exc

    async def _serve(self) -> None:
        args = argparse.Namespace(
            port=self.port,
            discovery_port=self.discovery_port,
            bind="0.0.0.0",
            monitor=1,
            width=1600,
            quality=70,
            fps=30,
            no_gpu=self.no_gpu,
            pair_ttl=180,
            no_qr=True,
            qr_open=False,
            no_tray=True,
            no_console=True,
            no_tls=False,
            set_pin=False,
            pin="",
            forget_devices=False,
            cert=str(self.data_dir / "cert.pem"),
            key=str(self.data_dir / "key.pem"),
        )
        self.loop = asyncio.get_running_loop()
        servidor = srv.Server(
            args,
            self.pin_record,
            self.limiter,
            True,
            tokens=self.tokens,
            devices=self.devices,
            fingerprint=self.fingerprint,
            activity_cb=self._on_activity,
            ready_cb=self._on_ready,
        )
        self.host = servidor.pairing_host()
        self.server = servidor
        try:
            await servidor.run(self.ssl_ctx)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 10048 or exc.errno in (48, 98, 10048):
                raise HostError(
                    f"A porta {self.port} ja esta em uso. Feche o outro "
                    "PocketDesk (ou o servidor antigo) e ligue de novo."
                ) from exc
            raise

    def stop(self, timeout: float = 6.0) -> None:
        servidor = self.server
        if servidor is not None:
            servidor.request_stop()
        thread = self.thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)

    # ------------------------------------------------------------ eventos

    def _on_ready(self) -> None:
        self.ready = True
        self.events.put(("ready", self.host, self.port))

    def _on_activity(self, count: int, names: str) -> None:
        self.events.put(("activity", count, names))

    # ------------------------------------------------------------ acoes

    def _in_loop(self, fn, timeout: float = 6.0):
        loop = self.loop
        if loop is None or self.server is None:
            raise HostError("O servidor nao esta ligado.")
        future: concurrent.futures.Future = concurrent.futures.Future()

        def run() -> None:
            try:
                future.set_result(fn())
            except BaseException as exc:  # noqa: BLE001
                future.set_exception(exc)

        loop.call_soon_threadsafe(run)
        return future.result(timeout=timeout)

    def new_pairing(self) -> tuple[str, float]:
        """Gera um QR novo; devolve (uri, expira_em_epoch)."""
        def gen():
            return self.server.create_pairing()  # type: ignore[union-attr]

        return self._in_loop(gen)

    def session_list(self) -> list[dict]:
        if self.server is None:
            return []
        try:
            return self._in_loop(lambda: self.server.session_list(), timeout=2.0)
        except Exception:  # noqa: BLE001
            return []

    def device_list(self) -> list[dict]:
        return [
            {
                "id": rec.id,
                "name": rec.name,
                "created": rec.created,
                "last_seen": rec.last_seen,
            }
            for rec in self.devices.all()
        ]

    def revoke(self, device_id: str) -> bool:
        def remover() -> bool:
            return self.devices.remove(device_id)

        return bool(self._in_loop(remover))

    def forget_all(self) -> int:
        def limpar() -> int:
            quantidade = len(self.devices.all())
            self.devices.clear()
            self.tokens.clear()
            return quantidade

        return int(self._in_loop(limpar))

    def set_pin(self, pin: str) -> None:
        """Troca o PIN e aplica na hora (sem reiniciar)."""
        record = security.save_pin(self.data_dir / "pin.txt", pin, tls_enabled=True)
        self.pin_record = record
        if self.server is not None:
            self.server.pin_record = record
