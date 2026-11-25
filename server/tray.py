# SPDX-License-Identifier: AGPL-3.0-or-later
"""Icone de bandeja do Windows e aviso de conexao ativa.

O icone muda de cor quando alguem esta controlando o PC e mostra uma notificacao
no primeiro momento da conexao. O menu permite gerar um novo QR de pareamento,
listar/esquecer aparelhos e encerrar o servidor.

Se o `pystray` nao estiver instalado, o servidor continua normalmente e o aviso
vai para o titulo do console (ver `_set_console_title` em server.py).
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path


def _message(text: str, title: str, flags: int = 0x40) -> int:
    """MessageBoxW do Windows (0x40 = informacao, 0x04|0x20 = sim/nao)."""
    try:
        import ctypes

        return int(ctypes.windll.user32.MessageBoxW(None, text, title, flags))
    except Exception:  # noqa: BLE001
        return 0


class Tray:
    def __init__(self, server, pystray, image_module, draw_module) -> None:
        self.server = server
        self._pystray = pystray
        self._Image = image_module
        self._ImageDraw = draw_module
        self._lock = threading.Lock()
        self._last_count = 0
        self._connected_image = self._make_icon(True)
        self._idle_image = self._make_icon(False)

        menu = pystray.Menu(
            pystray.MenuItem(
                "Pareamento por QR", self._on_qr, default=True
            ),
            pystray.MenuItem("Aparelhos pareados", self._on_devices),
            pystray.MenuItem("Esquecer aparelhos", self._on_forget),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Abrir pasta do servidor", self._on_folder),
            pystray.MenuItem("Sair", self._on_quit),
        )
        self.icon = pystray.Icon(
            "poltergeist", self._idle_image, "Poltergeist", menu
        )

    # ------------------------------------------------------------ desenho

    def _make_icon(self, connected: bool):
        img = self._Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = self._ImageDraw.Draw(img)
        cor = (220, 38, 38, 255) if connected else (22, 163, 74, 255)
        draw.ellipse((2, 2, 62, 62), fill=cor)
        # desenho simples de monitor
        draw.rectangle((18, 20, 46, 38), outline=(255, 255, 255, 255), width=3)
        draw.line((32, 38, 32, 45), fill=(255, 255, 255, 255), width=3)
        draw.line((24, 46, 40, 46), fill=(255, 255, 255, 255), width=3)
        return img

    # ------------------------------------------------------------ ciclo de vida

    def start(self) -> None:
        threading.Thread(target=self._run, name="lc-tray", daemon=True).start()

    def _run(self) -> None:
        try:
            self.icon.run()
        except Exception:  # noqa: BLE001
            # sem bandeja: o console continua avisando pelo titulo
            pass

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:  # noqa: BLE001
            pass

    def update(self, count: int, names: str) -> None:
        with self._lock:
            anterior = self._last_count
            self._last_count = count
            try:
                self.icon.icon = self._connected_image if count > 0 else self._idle_image
                if count <= 0:
                    self.icon.title = "Poltergeist - nenhuma conexao ativa"
                elif count == 1:
                    self.icon.title = f"Poltergeist - conectado: {names}"
                else:
                    self.icon.title = f"Poltergeist - {count} conexoes ativas"
            except Exception:  # noqa: BLE001
                return

            if count > anterior:
                texto = (
                    f"{names} esta controlando o PC"
                    if count == 1
                    else f"{count} conexoes ativas: {names}"
                )
                self._notify(texto)
            elif count == 0 and anterior > 0:
                self._notify("Conexao encerrada")

    def _notify(self, texto: str) -> None:
        try:
            self.icon.notify(texto, "Poltergeist")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ menu

    def _on_qr(self, _icon=None, _item=None) -> None:
        self.server.request_pairing(open_image=True)

    def _on_devices(self, _icon=None, _item=None) -> None:
        recs = self.server.devices.all()
        if not recs:
            _message("Nenhum aparelho pareado.", "Poltergeist")
            return
        linhas = []
        for rec in recs:
            quando = datetime.fromtimestamp(rec.created).strftime("%d/%m/%Y %H:%M")
            linhas.append(f"{rec.name}  ({rec.id})\n  pareado em {quando}")
        _message("\n\n".join(linhas), "Aparelhos pareados")

    def _on_forget(self, _icon=None, _item=None) -> None:
        resposta = _message(
            "Esquecer todos os aparelhos pareados?\n\n"
            "Eles precisarao parear de novo pelo QR ou pelo PIN.\n"
            "Uma conexao ja aberta continua ate ser encerrada no app.",
            "Poltergeist",
            0x04 | 0x20,
        )
        if resposta == 6:  # IDYES
            self.server.request_forget()

    def _on_folder(self, _icon=None, _item=None) -> None:
        try:
            os.startfile(Path(__file__).resolve().parent)  # type: ignore[attr-defined]
        except OSError:
            pass

    def _on_quit(self, _icon=None, _item=None) -> None:
        self.server.request_stop()


def start(server):
    """Cria e inicia a bandeja; devolve None se o pystray nao estiver instalado."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001
        return None

    tray = Tray(server, pystray, Image, ImageDraw)
    tray.start()
    return tray
