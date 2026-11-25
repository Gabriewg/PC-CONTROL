# SPDX-License-Identifier: AGPL-3.0-or-later
"""Icone de bandeja da janela (fechar minimiza, como no AnyDesk)."""

from __future__ import annotations

import threading

from . import platform_win
from . import theme as T


class GuiTray:
    def __init__(self, app) -> None:
        self.app = app
        self.icon = None
        self._active = False

    # ------------------------------------------------------------ ciclo

    def start(self) -> bool:
        try:
            import pystray
        except Exception:  # noqa: BLE001
            return False
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Abrir Poltergeist", self._open, default=True),
                pystray.MenuItem("Gerar novo QR", self._qr),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Sair", self._quit),
            )
            self.icon = pystray.Icon(
                "Poltergeist", self._image(False), "Poltergeist", menu
            )
            if hasattr(self.icon, "run_detached"):
                self.icon.run_detached()
            else:
                threading.Thread(target=self.icon.run, daemon=True).start()
            return True
        except Exception:  # noqa: BLE001
            self.icon = None
            return False

    def stop(self) -> None:
        try:
            if self.icon is not None:
                self.icon.stop()
        except Exception:  # noqa: BLE001
            pass

    def update(self, active: bool, count: int = 0) -> None:
        if self.icon is None or active == self._active:
            return
        self._active = active
        try:
            self.icon.icon = self._image(active)
            if active:
                texto = (
                    "Poltergeist - conectado"
                    if count <= 1
                    else f"Poltergeist - {count} conexoes"
                )
            else:
                texto = "Poltergeist - aguardando conexao"
            self.icon.title = texto
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ menu

    def _open(self, _icon=None, _item=None) -> None:
        self.app.post(self.app.show_window)

    def _qr(self, _icon=None, _item=None) -> None:
        self.app.post(self.app.generate_qr)

    def _quit(self, _icon=None, _item=None) -> None:
        self.app.post(self.app.quit)

    # ------------------------------------------------------------ imagem

    def _image(self, active: bool):
        from PIL import Image, ImageDraw

        base = None
        try:
            caminho = platform_win.brand_image_path()
            if caminho is not None:
                base = Image.open(caminho).convert("RGBA")
                base = base.resize((64, 64), Image.LANCZOS)
        except Exception:  # noqa: BLE001
            base = None

        if base is None:
            base = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(base)
            draw.ellipse((2, 2, 62, 62), fill=T.ACCENT)
            draw.rectangle((18, 20, 46, 38), outline=(255, 255, 255, 255), width=3)
            draw.line((32, 38, 32, 45), fill=(255, 255, 255, 255), width=3)
            draw.line((24, 46, 40, 46), fill=(255, 255, 255, 255), width=3)
            return base

        # Bolinha de estado no canto (verde = alguem conectado).
        draw = ImageDraw.Draw(base)
        cor = (62, 207, 142, 255) if active else (110, 93, 99, 255)
        draw.ellipse((44, 44, 62, 62), fill=cor, outline=(10, 6, 8, 255), width=3)
        return base
