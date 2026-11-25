# SPDX-License-Identifier: AGPL-3.0-or-later
"""Janelas modais: PIN, confirmacao e tunel USB."""

from __future__ import annotations

import threading
import tkinter as tk

from . import platform_win
from . import theme as T
from .widgets import Button, LinkButton, Modal, entry


def _label(parent, text, font=T.F_BODY, fg=T.TEXT, **kwargs) -> tk.Label:
    return tk.Label(parent, text=text, font=font, fg=fg, bg=T.CARD, **kwargs)


class PinModal(Modal):
    """Criar (primeiro uso) ou trocar o PIN, sem console."""

    def __init__(self, parent, *, first_run: bool, on_save, on_cancel=None) -> None:
        if first_run:
            titulo = "Crie seu PIN de acesso"
            subtitulo = (
                "O PIN e' seu e fica so' neste PC (nunca vai para a rede). "
                "Com ele voce tambem conecta sem ler o QR. Use 4 ou mais caracteres."
            )
        else:
            titulo = "Trocar o PIN"
            subtitulo = (
                "O novo PIN vale na hora. Os aparelhos ja pareados continuam "
                "conectando sem pedir PIN."
            )
        super().__init__(parent, titulo, subtitulo, width=T.px(440))
        self._on_save = on_save
        self._on_cancel = on_cancel
        self._first_run = first_run

        _label(self.content, "PIN", T.F_SMALL_BOLD, T.TEXT_MUTED).pack(anchor="w")
        self.pin_entry = entry(self.content, show="\u2022")
        self.pin_entry.pack(fill="x", ipady=T.px(7), ipadx=T.px(8), pady=(T.px(6), T.px(14)))

        _label(self.content, "Confirme o PIN", T.F_SMALL_BOLD, T.TEXT_MUTED).pack(anchor="w")
        self.confirm_entry = entry(self.content, show="\u2022")
        self.confirm_entry.pack(fill="x", ipady=T.px(7), ipadx=T.px(8), pady=(T.px(6), T.px(6)))

        linha = tk.Frame(self.content, bg=T.CARD)
        linha.pack(fill="x")
        self._show_link = LinkButton(linha, "Mostrar PIN", self._toggle_show)
        self._show_link.pack(side="right")

        self.error = _label(self.content, "", T.F_SMALL, T.RED)
        self.error.pack(anchor="w", pady=(T.px(6), 0))

        acoes = tk.Frame(self.content, bg=T.CARD)
        acoes.pack(fill="x", pady=(T.px(18), 0))
        Button(
            acoes, "Salvar", self._save, variant="primary",
            height=T.px(38), bg=T.CARD,
        ).pack(side="right")
        Button(
            acoes, "Cancelar", self.cancel, variant="ghost",
            height=T.px(38), bg=T.CARD,
        ).pack(side="right", padx=(0, T.px(8)))

        self.pin_entry.bind("<Return>", lambda _e: self._save())
        self.confirm_entry.bind("<Return>", lambda _e: self._save())

    def show(self) -> None:
        super().show()
        self.pin_entry.focus_set()

    def _toggle_show(self) -> None:
        mostrar = self.pin_entry.cget("show") == ""
        self.pin_entry.configure(show="" if mostrar else "\u2022")
        self.confirm_entry.configure(show="" if mostrar else "\u2022")
        self._show_link.configure(text="Ocultar PIN" if mostrar else "Mostrar PIN")

    def _save(self) -> None:
        pin = self.pin_entry.get()
        if len(pin.strip()) < 4:
            self.error.configure(text="O PIN precisa ter pelo menos 4 caracteres.")
            return
        if pin != self.confirm_entry.get():
            self.error.configure(text="Os PINs nao conferem.")
            return
        try:
            self._on_save(pin.strip())
        except ValueError as exc:
            self.error.configure(text=str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.error.configure(text=f"Nao foi possivel salvar: {exc}")
            return
        self.cancel()

    def cancel(self) -> None:
        if self._first_run and self._on_cancel is not None:
            self._on_cancel()
            return
        super().cancel()


class ConfirmModal(Modal):
    def __init__(
        self,
        parent,
        title: str,
        text: str,
        *,
        confirm_label: str = "Confirmar",
        on_confirm=None,
        danger: bool = False,
    ) -> None:
        super().__init__(parent, title, width=T.px(430))
        self._on_confirm = on_confirm
        _label(
            self.content, text, T.F_BODY, T.TEXT_MUTED,
            wraplength=T.px(380), justify="left",
        ).pack(anchor="w", fill="x")

        acoes = tk.Frame(self.content, bg=T.CARD)
        acoes.pack(fill="x", pady=(T.px(20), 0))
        Button(
            acoes, confirm_label, self._confirm,
            variant="danger" if danger else "primary",
            height=T.px(38), bg=T.CARD,
        ).pack(side="right")
        Button(
            acoes, "Cancelar", self.cancel, variant="ghost",
            height=T.px(38), bg=T.CARD,
        ).pack(side="right", padx=(0, T.px(8)))

    def _confirm(self) -> None:
        callback = self._on_confirm
        self.cancel()
        if callback is not None:
            callback()


class UsbModal(Modal):
    """Tunel USB (adb reverse) com o resultado na propria janela."""

    def __init__(self, parent, *, port: int, post, notify) -> None:
        super().__init__(
            parent,
            "Conexao por USB",
            "Ligue o cabo, ative a depuracao USB no celular e aceite o aviso "
            "do computador. No app, use 127.0.0.1 na porta "
            f"{port} (mais rapido e estavel que o Wi-Fi).",
            width=T.px(480),
        )
        self._port = port
        self._post = post
        self._notify = notify
        self._adb = platform_win.adb_available()

        self.out = tk.Text(
            self.content, height=6, bg=T.BG_DEEP, fg=T.TEXT_MUTED,
            font=T.F_MONO_SMALL, relief="flat", bd=0, highlightthickness=0,
            wrap="word", padx=T.px(10), pady=T.px(8),
        )
        self.out.pack(fill="x", pady=(0, T.px(12)))
        self.out.insert("1.0", "Verificando o adb...")
        self.out.configure(state="disabled")

        acoes = tk.Frame(self.content, bg=T.CARD)
        acoes.pack(fill="x")
        self.tunnel_btn = Button(
            acoes, "Criar tunel USB", self._tunnel, variant="primary",
            height=T.px(38), bg=T.CARD,
        )
        self.tunnel_btn.pack(side="right")
        self.check_btn = Button(
            acoes, "Verificar celular", self._check, variant="secondary",
            height=T.px(38), bg=T.CARD,
        )
        self.check_btn.pack(side="right", padx=(0, T.px(8)))
        Button(
            acoes, "Fechar", self.cancel, variant="ghost",
            height=T.px(38), bg=T.CARD,
        ).pack(side="left")

        if not self._adb:
            self.tunnel_btn.set_enabled(False)
            self.check_btn.set_enabled(False)
            self._write(
                "adb nao encontrado no PATH.\n\n"
                "Instale as Platform Tools do Android e adicione a pasta ao PATH, "
                "ou conecte pelo Wi-Fi usando o IP mostrado na tela principal."
            )

    def show(self) -> None:
        super().show()
        if self._adb:
            self._check()

    # ------------------------------------------------------------ acoes

    def _check(self) -> None:
        self._write("Verificando dispositivos...")
        threading.Thread(target=self._worker, args=("check",), daemon=True).start()

    def _tunnel(self) -> None:
        self._write("Criando o tunel...")
        self.tunnel_btn.set_enabled(False)
        threading.Thread(target=self._worker, args=("tunnel",), daemon=True).start()

    def _worker(self, acao: str) -> None:
        if acao == "tunnel":
            ok, saida = platform_win.adb_reverse(self._port)
            texto = (
                f"Tunel criado. No app use 127.0.0.1:{self._port}."
                if ok
                else f"Falhou:\n{saida or 'sem resposta do adb'}"
            )
        else:
            ok, saida = platform_win.adb_devices()
            texto = saida or "adb nao respondeu"
        self._post(lambda: self._finish(acao, ok, texto))

    def _finish(self, acao: str, ok: bool, texto: str) -> None:
        if not self.winfo_exists():
            return
        self._write(texto)
        if acao == "tunnel":
            self.tunnel_btn.set_enabled(True)
            self._notify(
                f"Tunel USB ativo na porta {self._port}" if ok
                else "Nao foi possivel criar o tunel USB",
                "ok" if ok else "error",
            )

    def _write(self, texto: str) -> None:
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        self.out.insert("1.0", texto)
        self.out.configure(state="disabled")
