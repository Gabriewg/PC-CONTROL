# SPDX-License-Identifier: AGPL-3.0-or-later
"""Janela principal do Poltergeist: servidor, QR, aparelhos e sessoes."""

from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

from . import platform_win
from . import theme as T
from .dialogs import ConfirmModal, PinModal, UsbModal
from .host import HostError, ServerHost
from .tray import GuiTray
from .widgets import (
    Button, Card, Divider, LinkButton, ProgressBar, SlimScrollbar, StatusPill,
    Toggle, round_rect,
)

import security
import server as srv


def _label(parent, text, font=T.F_BODY, fg=T.TEXT, bg=T.CARD, **kwargs) -> tk.Label:
    return tk.Label(parent, text=text, font=font, fg=fg, bg=bg, **kwargs)


def _section(parent, text: str, bg: str = T.CARD) -> tk.Label:
    return tk.Label(
        parent, text=text, font=T.F_TINY, fg=T.TEXT_DIM, bg=bg,
    )


def _fmt_date(timestamp: int) -> str:
    if not timestamp:
        return "-"
    try:
        return datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y")
    except (OverflowError, OSError, ValueError):
        return "-"


def _fmt_seen(timestamp: int) -> str:
    if not timestamp:
        return "nunca usado"
    hoje = datetime.now().date()
    try:
        dia = datetime.fromtimestamp(timestamp).date()
    except (OverflowError, OSError, ValueError):
        return "nunca usado"
    if dia == hoje:
        return "visto hoje"
    if (hoje - dia).days == 1:
        return "visto ontem"
    return f"visto em {dia.strftime('%d/%m/%Y')}"


def _fmt_uptime(seconds: int) -> str:
    if seconds < 60:
        return "agora"
    minutos = seconds // 60
    if minutos < 60:
        return f"{minutos} min"
    horas, minutos = divmod(minutos, 60)
    return f"{horas} h {minutos:02d}"


def _short_fingerprint(fingerprint: str) -> str:
    if not fingerprint:
        return "indisponivel"
    grupos = security.format_fingerprint(fingerprint).split()
    return " ".join(grupos[:3]) + (" ..." if len(grupos) > 3 else "")


class MainWindow:
    def __init__(
        self,
        root: tk.Tk,
        host: ServerHost,
        log_queue: "queue.Queue[str]",
    ) -> None:
        self.root = root
        self.host = host
        self.log_queue = log_queue
        self.resource_dir = platform_win.resource_dir()

        self._queue: "queue.Queue" = queue.Queue()
        self._qr_photo = None
        self._qr_uri = ""
        self._qr_expires = 0.0
        self._qr_expired = False
        self._qr_used = False
        self._sessions_sig = None
        self._session_rows: dict[tuple[str, str], tk.Label] = {}
        self._devices_sig = None
        self._state = "off"
        self._quitting = False
        self._toast_after = None
        self._placeholder_cache: dict[str, object] = {}
        self._tray: GuiTray | None = None
        self._bar_visible = False

        self._win_w, self._win_h = self._initial_size()
        # Telas baixas (768p) ou com DPI alto precisam de uma versao mais justa.
        self._compact = self._win_h / max(T.get_scale(), 0.01) < 789
        self._qr_target = 176 if self._compact else 224

        self._build()
        self._setup_window()
        self._refresh_devices(force=True)
        self._refresh_sessions()
        self._set_state("off")
        self._refresh_firewall()
        self._start_tray()
        self._poll()
        self._tick()
        self.root.after(80, self._fit_content)

        if self.host.has_pin:
            self.root.after(200, self.start_server)
        else:
            self.root.after(300, self._first_run_pin)

    # ================================================================ janela

    def _initial_size(self) -> tuple[int, int]:
        root = self.root
        largura = min(T.px(1180), root.winfo_screenwidth() - T.px(60))
        altura = min(T.px(790), root.winfo_screenheight() - T.px(110))
        return largura, altura

    def _setup_window(self) -> None:
        root = self.root
        root.title("Poltergeist")
        root.configure(bg=T.BG)
        root.minsize(min(T.px(980), root.winfo_screenwidth() - T.px(40)),
                     min(T.px(650), root.winfo_screenheight() - T.px(90)))
        largura, altura = self._win_w, self._win_h
        x = (root.winfo_screenwidth() - largura) // 2
        y = max(0, (root.winfo_screenheight() - altura) // 2 - T.px(18))
        root.geometry(f"{largura}x{altura}+{x}+{y}")
        platform_win.apply_dark_titlebar(root)
        platform_win.set_window_icon(root)
        root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        root.bind("<Control-q>", lambda _e: self.quit())
        root.bind("<F5>", lambda _e: self.generate_qr())

    def _m(self, normal: int, compact: int | None = None) -> int:
        """Medida em px: usa a versao compacta quando a tela e' baixa."""
        if compact is None or not self._compact:
            return T.px(normal)
        return T.px(compact)

    def _build(self) -> None:
        self._build_header()

        self._toast = tk.Label(
            self.root, text="", bg=T.WINE, fg=T.TEXT, font=T.F_SMALL_BOLD,
            padx=T.px(16), pady=T.px(9), bd=0,
        )

        self._build_footer()

        # Conteudo rolavel: em 768p (ou DPI alto) sobra pouco espaco, e nada
        # pode ficar escondido atras do rodape.
        shell = tk.Frame(self.root, bg=T.BG)
        shell.pack(fill="both", expand=True, padx=T.px(24), pady=(0, self._m(10, 8)))

        self._scroll = tk.Canvas(
            shell, bg=T.BG, highlightthickness=0, bd=0, takefocus=0,
        )
        self._scroll.pack(side="left", fill="both", expand=True, padx=(0, T.px(14)))
        self._scroll_bar = SlimScrollbar(
            shell, command=self._scroll.yview,
            bg=T.BG, thumb=T.BORDER, width=T.px(8),
        )
        self._scroll.configure(yscrollcommand=self._on_scroll_set)

        content = tk.Frame(self._scroll, bg=T.BG)
        self._content = content
        self._scroll_window = self._scroll.create_window(
            (0, 0), anchor="nw", window=content,
        )
        content.grid_columnconfigure(0, minsize=T.px(300))
        content.grid_columnconfigure(1, weight=1, minsize=T.px(370))
        content.grid_columnconfigure(2, minsize=T.px(320))
        content.grid_rowconfigure(0, weight=1)

        self._scroll.bind("<Configure>", self._fit_content)
        content.bind("<Configure>", self._fit_content)
        self.root.bind_all("<MouseWheel>", self._on_wheel, add="+")

        esquerda = tk.Frame(content, bg=T.BG)
        esquerda.grid(row=0, column=0, sticky="nsew", padx=(0, self._m(14, 12)))
        centro = tk.Frame(content, bg=T.BG)
        centro.grid(row=0, column=1, sticky="nsew", padx=(0, self._m(14, 12)))
        direita = tk.Frame(content, bg=T.BG)
        direita.grid(row=0, column=2, sticky="nsew")

        self._build_server_card(esquerda)
        self._build_usb_card(esquerda)
        self._build_qr_card(centro)
        self._build_sessions_card(centro)
        self._build_devices_card(direita)
        self._build_log_card(direita)

    # ---------------------------------------------------------------- rolagem

    def _fit_content(self, _event=None) -> None:
        """Estica o conteudo ate' a altura da janela (ou o quanto ele pedir)."""
        try:
            largura = max(1, self._scroll.winfo_width())
            natural = self._content.winfo_reqheight()
            altura = max(self._scroll.winfo_height(), natural)
            self._scroll.itemconfigure(
                self._scroll_window, width=largura, height=altura,
            )
            self._scroll.configure(scrollregion=(0, 0, largura, altura))
        except tk.TclError:
            return
        self.root.after_idle(self._sync_scrollbar)

    def _on_scroll_set(self, first, last) -> None:
        self._scroll_bar.set(first, last)
        self._sync_scrollbar()

    def _sync_scrollbar(self) -> None:
        try:
            precisa = (
                self._content.winfo_height() > self._scroll.winfo_height() + 1
            )
        except tk.TclError:
            return
        if precisa == self._bar_visible:
            return
        self._bar_visible = precisa
        if precisa:
            self._scroll_bar.place(
                relx=1.0, rely=0.0, anchor="ne", relheight=1.0, width=T.px(8),
            )
        else:
            self._scroll_bar.place_forget()
            self._scroll.yview_moveto(0)

    def _on_wheel(self, event) -> None:
        try:
            x0 = self._scroll.winfo_rootx()
            y0 = self._scroll.winfo_rooty()
            x1 = x0 + self._scroll.winfo_width()
            y1 = y0 + self._scroll.winfo_height()
            if not (x0 <= event.x_root < x1 and y0 <= event.y_root < y1):
                return
            if self._content.winfo_height() <= self._scroll.winfo_height():
                return
        except tk.TclError:
            return
        passo = -1 if event.delta > 0 else 1
        self._scroll.yview_scroll(passo * 3, "units")

    # ---------------------------------------------------------------- topo

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=T.BG, height=self._m(86, 76))
        header.pack(fill="x", padx=T.px(24), pady=(self._m(16, 10), self._m(6, 4)))
        header.pack_propagate(False)

        logo = tk.Canvas(
            header, width=T.px(44), height=T.px(44), bg=T.BG, highlightthickness=0,
        )
        logo.pack(side="left", pady=T.px(8))
        round_rect(logo, 0, 0, T.px(44) - 1, T.px(44) - 1, T.px(12),
                   fill=T.ACCENT, outline=T.ACCENT_HOVER, width=1)
        lw = T.px(44)
        logo.create_rectangle(
            T.px(11), T.px(14), lw - T.px(11), T.px(27),
            outline=T.WHITE, width=max(1, T.px(2)),
        )
        logo.create_line(
            lw / 2, T.px(27), lw / 2, T.px(32), fill=T.WHITE, width=max(1, T.px(2)),
        )
        logo.create_line(
            T.px(15), T.px(33), lw - T.px(15), T.px(33),
            fill=T.WHITE, width=max(1, T.px(2)),
        )

        titulos = tk.Frame(header, bg=T.BG)
        titulos.pack(side="left", padx=(T.px(14), 0), pady=self._m(6, 2))
        _label(titulos, "Poltergeist", T.F_DISPLAY, T.TEXT, T.BG).pack(anchor="w")
        _label(
            titulos, "Controle remoto local - sem nuvem, sem conta",
            T.F_SMALL, T.TEXT_MUTED, T.BG,
        ).pack(anchor="w")

        self.pill = StatusPill(header, bg=T.BG)
        self.pill.pack(side="right", pady=self._m(16, 12))

    # ---------------------------------------------------------------- rodape

    def _build_footer(self) -> None:
        borda = tk.Frame(self.root, bg=T.BORDER_SOFT)
        borda.pack(side="bottom", fill="x")
        footer = tk.Frame(borda, bg=T.BG_DEEP, height=self._m(58, 52))
        footer.pack(fill="x", pady=(1, 0))
        footer.pack_propagate(False)

        linha = tk.Frame(footer, bg=T.BG_DEEP)
        linha.pack(fill="x", padx=T.px(24), pady=self._m(11, 8))

        self.firewall_btn = Button(
            linha, "Liberar firewall", self._firewall_click,
            variant="ghost", height=T.px(34), width=T.px(150),
            bg=T.BG_DEEP, font=T.F_SMALL_BOLD,
        )
        self.firewall_btn.pack(side="left")

        auto = tk.Frame(linha, bg=T.BG_DEEP)
        auto.pack(side="left", padx=(T.px(18), 0))
        self.autostart_toggle = Toggle(
            auto, value=platform_win.autostart_enabled(),
            command=self._toggle_autostart, width=T.px(40), height=T.px(23),
            bg=T.BG_DEEP,
        )
        self.autostart_toggle.pack(side="left")
        _label(
            auto, "Iniciar com o Windows", T.F_SMALL, T.TEXT_MUTED, T.BG_DEEP,
        ).pack(side="left", padx=(T.px(9), 0))

        LinkButton(
            linha, "Pasta de dados", lambda: platform_win.open_path(self.host.data_dir),
            bg=T.BG_DEEP,
        ).pack(side="left", padx=(T.px(20), 0))

        _label(
            linha, f"v{srv.VERSION}  -  porta {self.host.port}",
            T.F_TINY, T.TEXT_DIM, T.BG_DEEP,
        ).pack(side="right")

        Button(
            linha, "Sair", self.quit, variant="ghost", height=T.px(34),
            bg=T.BG_DEEP, font=T.F_SMALL_BOLD,
        ).pack(side="right", padx=(0, T.px(12)))

    # ---------------------------------------------------------------- servidor

    def _build_server_card(self, parent: tk.Frame) -> None:
        card = Card(parent, pad=self._m(T.PAD, 15))
        card.pack(fill="x")
        body = card.body

        _section(body, "SERVIDOR").pack(anchor="w")
        linha = tk.Frame(body, bg=T.CARD)
        linha.pack(fill="x", pady=(self._m(14, 12), 0))

        self.toggle = Toggle(linha, value=False, command=self.toggle_server, bg=T.CARD)
        self.toggle.pack(side="left", pady=T.px(2))

        textos = tk.Frame(linha, bg=T.CARD)
        textos.pack(side="left", padx=(T.px(12), 0))
        self.server_state = _label(textos, "Servidor desligado", T.F_BODY_BOLD, T.TEXT_MUTED)
        self.server_state.pack(anchor="w")
        self.server_sub = _label(textos, "Clique na chave para ligar", T.F_SMALL, T.TEXT_DIM)
        self.server_sub.pack(anchor="w")

        Divider(body, bg=T.CARD).pack(fill="x", pady=(self._m(16, 12), self._m(14, 10)))

        self.host_label = self._info_row(body, "COMPUTADOR", platform_win.hostname())
        self.addr_label = self._info_row(
            body, "ENDERECO", f"{self.host.guess_host()}:{self.host.port}",
            mono=True, action=self._copy_address,
        )
        self.pin_label = self._info_row(
            body, "PIN",
            "Definido" if self.host.has_pin else "Nao definido",
            action=self._pin_action,
            action_label="Trocar" if self.host.has_pin else "Definir",
        )
        self._fingerprint_label = self._info_row(
            body, "CHAVE PUBLICA", _short_fingerprint(self.host.fingerprint),
            mono=True, action=self._copy_fingerprint,
        )

    def _info_row(
        self,
        parent: tk.Frame,
        caption: str,
        value: str,
        *,
        mono: bool = False,
        action=None,
        action_label: str = "Copiar",
    ) -> tk.Label:
        linha = tk.Frame(parent, bg=T.CARD)
        linha.pack(fill="x", pady=(0, self._m(12, 9)))
        _label(linha, caption, T.F_TINY, T.TEXT_DIM).pack(anchor="w")
        valores = tk.Frame(linha, bg=T.CARD)
        valores.pack(fill="x", pady=(T.px(2), 0))
        label = tk.Label(
            valores, text=value, bg=T.CARD, fg=T.TEXT,
            font=T.F_MONO if mono else T.F_BODY_BOLD, anchor="w", justify="left",
        )
        label.pack(side="left")
        if action is not None:
            LinkButton(valores, action_label, action, bg=T.CARD).pack(side="right")
        return label

    def _build_usb_card(self, parent: tk.Frame) -> None:
        card = Card(parent, pad=self._m(T.PAD, 15))
        card.pack(fill="x", pady=(self._m(14, 12), 0))
        _section(card.body, "CONEXAO USB").pack(anchor="w")
        if not self._compact:
            _label(
                card.body,
                "Cabo + depuracao USB: mais rapido e estavel que o Wi-Fi.",
                T.F_SMALL, T.TEXT_MUTED, wraplength=T.px(240), justify="left",
            ).pack(anchor="w", pady=(T.px(8), T.px(12)))
        Button(
            card.body, "Configurar tunel USB", self._open_usb,
            variant="secondary", height=self._m(36, 34), bg=T.CARD,
        ).pack(fill="x", pady=(0 if not self._compact else self._m(0, 10), 0))

    # ---------------------------------------------------------------- QR

    def _build_qr_card(self, parent: tk.Frame) -> None:
        card = Card(parent, pad=self._m(T.PAD, 15))
        card.pack(fill="x")
        body = card.body

        topo = tk.Frame(body, bg=T.CARD)
        topo.pack(fill="x")
        _section(topo, "PAREAMENTO").pack(side="left")
        tk.Label(
            topo, text="1 uso", bg=T.ACCENT_SOFT, fg=T.ACCENT_HOVER,
            font=T.F_TINY, padx=T.px(8), pady=T.px(2),
        ).pack(side="right")

        moldura = tk.Frame(body, bg=T.WHITE, padx=self._m(10, 8), pady=self._m(10, 8))
        moldura.pack(pady=(self._m(14, 10), 0))
        self.qr_label = tk.Label(moldura, bg=T.WHITE, bd=0)
        self.qr_label.pack()
        self.qr_label.configure(image=self._placeholder("Ligue o servidor"))

        linha = tk.Frame(body, bg=T.CARD)
        linha.pack(fill="x", pady=(self._m(14, 10), 0))
        self.qr_status = _label(linha, "Servidor desligado", T.F_SMALL, T.TEXT_MUTED)
        self.qr_status.pack(side="left")
        self.qr_time = _label(linha, "", T.F_SMALL_BOLD, T.TEXT)
        self.qr_time.pack(side="right")

        self.qr_progress = ProgressBar(body, bg=T.CARD)
        self.qr_progress.pack(fill="x", pady=(self._m(8, 6), 0))

        self.qr_button = Button(
            body, "Gerar novo QR", self.generate_qr, variant="primary",
            height=self._m(42, 38), bg=T.CARD,
        )
        self.qr_button.pack(fill="x", pady=(self._m(14, 10), 0))

        _label(
            body,
            "No celular: Poltergeist > Conectar > Ler QR Code",
            T.F_TINY, T.TEXT_DIM, wraplength=self._m(330, 300), justify="center",
        ).pack(pady=(self._m(10, 6), 0))

    # ---------------------------------------------------------------- sessoes

    def _build_sessions_card(self, parent: tk.Frame) -> None:
        card = Card(
            parent, fill=True, pad=self._m(T.PAD, 15), height=T.px(90),
        )
        self.sessions_card = card
        card.pack(fill="both", expand=True, pady=(self._m(14, 12), 0))
        topo = tk.Frame(card.body, bg=T.CARD)
        topo.pack(fill="x")
        _section(topo, "SESSOES ATIVAS").pack(side="left")
        self.sessions_count = tk.Label(
            topo, text="", bg=T.CARD_SOFT, fg=T.TEXT_MUTED,
            font=T.F_TINY, padx=T.px(8), pady=T.px(2),
        )
        self.sessions_count.pack(side="right")

        self.sessions_box = tk.Frame(card.body, bg=T.CARD)
        self.sessions_box.pack(fill="both", expand=True, pady=(self._m(12, 10), 0))

    # ---------------------------------------------------------------- aparelhos

    def _build_devices_card(self, parent: tk.Frame) -> None:
        card = Card(parent, pad=self._m(T.PAD, 15))
        card.pack(fill="x")
        topo = tk.Frame(card.body, bg=T.CARD)
        topo.pack(fill="x")
        _section(topo, "APARELHOS PARECIDOS").pack(side="left")
        self.devices_count = tk.Label(
            topo, text="", bg=T.CARD_SOFT, fg=T.TEXT_MUTED,
            font=T.F_TINY, padx=T.px(8), pady=T.px(2),
        )
        self.devices_count.pack(side="right")

        self.devices_box = tk.Frame(card.body, bg=T.CARD)
        self.devices_box.pack(fill="x", pady=(self._m(12, 10), 0))

        self.forget_btn = Button(
            card.body, "Esquecer todos", self._forget_all, variant="ghost",
            height=self._m(34, 32), bg=T.CARD, font=T.F_SMALL_BOLD,
        )
        self.forget_btn.pack(fill="x", pady=(self._m(4, 2), 0))
        self.forget_btn.set_enabled(False)

    # ---------------------------------------------------------------- atividade

    def _build_log_card(self, parent: tk.Frame) -> None:
        card = Card(
            parent, fill=True, pad=self._m(T.PAD, 15), height=T.px(180),
        )
        card.pack(fill="both", expand=True, pady=(self._m(14, 12), 0))
        topo = tk.Frame(card.body, bg=T.CARD)
        topo.pack(fill="x")
        _section(topo, "ATIVIDADE").pack(side="left")
        LinkButton(
            topo, "Abrir log",
            lambda: platform_win.open_path(self.host.data_dir / "server.log"),
            bg=T.CARD,
        ).pack(side="right", padx=(0, T.px(4)))

        self.log_text = tk.Text(
            card.body, height=6, bg=T.BG_DEEP, fg=T.TEXT_MUTED,
            font=T.F_MONO_SMALL, relief="flat", bd=0, highlightthickness=0,
            wrap="word", padx=T.px(10), pady=T.px(8), cursor="arrow",
        )
        self.log_text.pack(fill="both", expand=True, pady=(self._m(10, 8), 0))
        self.log_text.configure(state="disabled")

    # ================================================================ estado

    def _set_state(self, state: str) -> None:
        self._state = state
        if state == "on":
            self.toggle.set(True)
            self.server_state.configure(text="Servidor ligado", fg=T.TEXT)
            self.server_sub.configure(
                text=f"Ouvindo em {self.host.guess_host()}:{self.host.port}",
                fg=T.TEXT_MUTED,
            )
            self.pill.set(True, "Servidor ativo")
        elif state == "starting":
            self.toggle.set(True)
            self.server_state.configure(text="Ligando...", fg=T.TEXT)
            self.server_sub.configure(
                text="Preparando certificado e porta", fg=T.TEXT_MUTED,
            )
            self.pill.set(False, "Iniciando...")
        elif state == "stopping":
            self.toggle.set(False)
            self.server_state.configure(text="Desligando...", fg=T.TEXT_MUTED)
            self.server_sub.configure(text="Encerrando as conexoes", fg=T.TEXT_DIM)
            self.pill.set(False, "Desligando...")
        else:
            self.toggle.set(False)
            self.server_state.configure(text="Servidor desligado", fg=T.TEXT_MUTED)
            self.server_sub.configure(
                text="Clique na chave para ligar", fg=T.TEXT_DIM,
            )
            self.pill.set(False, "Servidor parado")
            self._clear_qr()
            self._sessions_sig = None
            self._refresh_sessions()
            if self._tray is not None:
                self._tray.update(False, 0)
        self.qr_button.set_enabled(state == "on")

    # ================================================================ acoes

    def toggle_server(self) -> None:
        if self._state in ("starting", "stopping"):
            self.toggle.set(self._state == "starting")
            return
        if self._state == "on":
            self.stop_server()
        else:
            self.start_server()

    def start_server(self) -> None:
        if self._state in ("on", "starting", "stopping"):
            return
        if not self.host.has_pin:
            self._first_run_pin()
            return
        self._set_state("starting")
        self.host.start()

    def stop_server(self) -> None:
        if self._state != "on":
            return
        self._set_state("stopping")
        threading.Thread(target=self.host.stop, name="pd-stop", daemon=True).start()

    def _first_run_pin(self) -> None:
        def salvar(pin: str) -> None:
            self.host.set_pin(pin)
            self.pin_label.configure(text="Definido")
            self.show_toast("PIN criado. Ligando o servidor...", "ok")
            self.root.after(250, self.start_server)

        PinModal(
            self.root, first_run=True, on_save=salvar,
            on_cancel=self.quit,
        ).show()

    def change_pin(self) -> None:
        def salvar(pin: str) -> None:
            self.host.set_pin(pin)
            self.pin_label.configure(text="Definido")
            self.show_toast("PIN alterado. Vale para as proximas conexoes.", "ok")

        PinModal(self.root, first_run=False, on_save=salvar).show()

    def _pin_action(self) -> None:
        if self.host.has_pin:
            self.change_pin()
        else:
            self._first_run_pin()

    def generate_qr(self) -> None:
        if self._state != "on" or not self.host.ready:
            self.show_toast("Ligue o servidor para gerar o QR.", "error")
            return
        try:
            uri, expira = self.host.new_pairing()
        except Exception as exc:  # noqa: BLE001
            self.show_toast(f"Nao foi possivel gerar o QR: {exc}", "error")
            return
        if not uri:
            self.show_toast("QR indisponivel: o TLS nao esta ativo.", "error")
            return
        self._qr_uri = uri
        self._qr_expires = expira
        self._qr_expired = False
        self._qr_used = False
        self._render_qr(uri)
        self.qr_status.configure(text="Escaneie no app do celular", fg=T.TEXT_MUTED)
        self.qr_time.configure(text="", fg=T.TEXT)

    # ---------------------------------------------------------------- QR

    def _render_qr(self, uri: str) -> None:
        try:
            import qrcode
            from PIL import ImageTk
        except ImportError:
            self.qr_status.configure(text="QR indisponivel (falta a lib qrcode)")
            return
        try:
            qr = qrcode.QRCode(
                error_correction=qrcode.constants.ERROR_CORRECT_M, border=2
            )
            qr.add_data(uri)
            qr.make(fit=True)
            alvo = T.px(self._qr_target)
            modulos = qr.modules_count + 4
            qr.box_size = max(3, alvo // modulos)
            img = qr.make_image(fill_color="#2A0A14", back_color="#FFFFFF").convert("RGB")
            photo = ImageTk.PhotoImage(img)
            self.qr_label.configure(image=photo)
            self._qr_photo = photo
            self.root.after(80, self._fit_content)
        except Exception as exc:  # noqa: BLE001
            self.qr_status.configure(text=f"Falha ao desenhar o QR: {exc}")

    def _clear_qr(self) -> None:
        self._qr_uri = ""
        self._qr_expires = 0.0
        self._qr_expired = False
        self._qr_used = False
        self.qr_label.configure(image=self._placeholder("Ligue o servidor"))
        self.qr_status.configure(text="Servidor desligado", fg=T.TEXT_MUTED)
        self.qr_time.configure(text="", fg=T.TEXT)
        self.qr_progress.set(0)
        self.root.after(80, self._fit_content)

    def _placeholder(self, text: str):
        from PIL import Image, ImageDraw, ImageFont, ImageTk

        cache = self._placeholder_cache.get(text)
        if cache is not None:
            return cache
        size = T.px(self._qr_target)
        img = Image.new("RGB", (size, size), "#FFFFFF")
        draw = ImageDraw.Draw(img)
        try:
            fonte = ImageFont.truetype(
                str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"),
                T.px(13),
            )
        except Exception:  # noqa: BLE001
            fonte = ImageFont.load_default()

        # Quebra em ate duas linhas para caber no quadro.
        palavras = text.split()
        linhas, atual = [], ""
        for palavra in palavras:
            teste = f"{atual} {palavra}".strip()
            if draw.textlength(teste, font=fonte) > size - T.px(24) and atual:
                linhas.append(atual)
                atual = palavra
            else:
                atual = teste
        if atual:
            linhas.append(atual)
        linhas = linhas[:2]

        altura_linha = T.px(19)
        total = len(linhas) * altura_linha
        y = (size - total) / 2
        for linha in linhas:
            largura = draw.textlength(linha, font=fonte)
            draw.text(((size - largura) / 2, y), linha, fill="#8E1B36", font=fonte)
            y += altura_linha

        photo = ImageTk.PhotoImage(img)
        self._placeholder_cache[text] = photo
        return photo

    def _tick_qr(self) -> None:
        if not self._qr_uri:
            return
        restante = self._qr_expires - time.time()
        if restante <= 0:
            if not self._qr_expired:
                self._qr_expired = True
                self.qr_status.configure(text="QR expirado", fg=T.RED)
                self.qr_time.configure(text="gere um novo", fg=T.RED)
                self.qr_progress.set(0)
            return
        minutos, segundos = divmod(int(restante), 60)
        self.qr_time.configure(text=f"expira em {minutos:02d}:{segundos:02d}", fg=T.TEXT)
        ttl = max(1.0, float(self.host.tokens.ttl))
        self.qr_progress.set(min(1.0, restante / ttl))

        if not self._qr_used and self.host.tokens.active_count() == 0:
            self._qr_used = True
            self.qr_status.configure(text="QR usado - aparelho pareado", fg=T.GREEN)
            self.qr_time.configure(text="1 uso", fg=T.GREEN)
            self.qr_progress.set(0)
            self._refresh_devices(force=True)

    # ---------------------------------------------------------------- sessoes

    @staticmethod
    def _set_badge(label: tk.Label, value: str) -> None:
        if value:
            if label.cget("text") != value:
                label.configure(text=value)
            if not label.winfo_manager():
                label.pack(side="right")
        elif label.winfo_manager():
            label.configure(text="")
            label.pack_forget()

    def _refresh_sessions(self) -> None:
        sessoes = self.host.session_list() if self.host.ready else []
        assinatura = tuple((s["name"], s["ip"]) for s in sessoes)
        self._set_badge(self.sessions_count, str(len(sessoes)) if sessoes else "")

        if assinatura != self._sessions_sig:
            self._sessions_sig = assinatura
            for filho in self.sessions_box.winfo_children():
                filho.destroy()
            self._session_rows = {}
            if not sessoes:
                _label(
                    self.sessions_box, "Nenhum aparelho conectado agora.",
                    T.F_SMALL, T.TEXT_DIM,
                ).pack(anchor="w", pady=(T.px(4), 0))
            for sessao in sessoes:
                self._session_rows[(sessao["name"], sessao["ip"])] = self._session_row(sessao)

        self.sessions_card.fit(T.px(90))
        self.root.after_idle(self._fit_content)
        self.root.after(80, self._fit_content)

        for sessao in sessoes:
            label = self._session_rows.get((sessao["name"], sessao["ip"]))
            if label is not None:
                label.configure(text=_fmt_uptime(sessao["seconds"]))

    def _session_row(self, sessao: dict) -> tk.Label:
        linha = tk.Frame(self.sessions_box, bg=T.CARD_SOFT)
        linha.pack(fill="x", pady=(0, T.px(8)))
        interno = tk.Frame(linha, bg=T.CARD_SOFT)
        interno.pack(fill="x", padx=T.px(12), pady=T.px(9))

        _label(interno, "\u25cf", (T.FONT, 9), T.GREEN, T.CARD_SOFT).pack(side="left")
        textos = tk.Frame(interno, bg=T.CARD_SOFT)
        textos.pack(side="left", padx=(T.px(8), 0))
        _label(textos, sessao["name"], T.F_BODY_BOLD, T.TEXT, T.CARD_SOFT).pack(anchor="w")
        _label(textos, sessao["ip"], T.F_TINY, T.TEXT_DIM, T.CARD_SOFT).pack(anchor="w")

        tempo = _label(
            interno, _fmt_uptime(sessao["seconds"]), T.F_SMALL, T.TEXT_MUTED, T.CARD_SOFT,
        )
        tempo.pack(side="right")
        return tempo

    # ---------------------------------------------------------------- aparelhos

    def _refresh_devices(self, force: bool = False) -> None:
        aparelhos = self.host.device_list()
        assinatura = tuple((a["id"], a["name"], a["last_seen"]) for a in aparelhos)
        self._set_badge(self.devices_count, str(len(aparelhos)) if aparelhos else "")
        self.forget_btn.set_enabled(bool(aparelhos))
        if not force and assinatura == self._devices_sig:
            return
        self._devices_sig = assinatura
        self.root.after(80, self._fit_content)

        for filho in self.devices_box.winfo_children():
            filho.destroy()

        if not aparelhos:
            _label(
                self.devices_box,
                "Nenhum aparelho pareado ainda.\nLeia o QR para conectar.",
                T.F_SMALL, T.TEXT_DIM, justify="left",
            ).pack(anchor="w", pady=(T.px(2), T.px(6)))
            return

        for aparelho in aparelhos[:6]:
            self._device_row(aparelho)

        if len(aparelhos) > 6:
            _label(
                self.devices_box, f"e mais {len(aparelhos) - 6} aparelho(s)",
                T.F_TINY, T.TEXT_DIM,
            ).pack(anchor="w", pady=(T.px(2), 0))

    def _device_row(self, aparelho: dict) -> None:
        row = Card(
            self.devices_box, pad=T.px(11), radius=T.RADIUS_SM,
            card=T.CARD_SOFT, border=T.BORDER_SOFT, bg=T.CARD,
        )
        row.pack(fill="x", pady=(0, T.px(8)))
        body = row.body

        botao = Button(
            body, "Revogar", lambda a=aparelho: self._revoke(a),
            variant="danger", height=T.px(29), padx=T.px(9),
            bg=T.CARD_SOFT, font=T.F_TINY,
        )
        botao.pack(side="right", padx=(T.px(8), 0))

        textos = tk.Frame(body, bg=T.CARD_SOFT)
        textos.pack(side="left", fill="x", expand=True)
        _label(textos, aparelho["name"], T.F_SMALL_BOLD, T.TEXT, T.CARD_SOFT).pack(anchor="w")
        _label(
            textos, f"pareado {_fmt_date(aparelho['created'])} - {_fmt_seen(aparelho['last_seen'])}",
            T.F_TINY, T.TEXT_DIM, T.CARD_SOFT,
        ).pack(anchor="w")

    def _revoke(self, aparelho: dict) -> None:
        def confirmado() -> None:
            try:
                self.host.revoke(aparelho["id"])
            except Exception as exc:  # noqa: BLE001
                self.show_toast(f"Nao foi possivel revogar: {exc}", "error")
                return
            self._refresh_devices(force=True)
            self.show_toast(f"{aparelho['name']} revogado.", "ok")

        ConfirmModal(
            self.root, "Revogar aparelho",
            f"{aparelho['name']} precisara parear de novo pelo QR ou pelo PIN. "
            "Uma conexao ja aberta continua ate ser encerrada no celular.",
            confirm_label="Revogar", on_confirm=confirmado, danger=True,
        ).show()

    def _forget_all(self) -> None:
        quantidade = len(self.host.device_list())
        if quantidade == 0:
            return

        def confirmado() -> None:
            try:
                self.host.forget_all()
            except Exception as exc:  # noqa: BLE001
                self.show_toast(f"Nao foi possivel esquecer: {exc}", "error")
                return
            self._refresh_devices(force=True)
            self.show_toast(f"{quantidade} aparelho(s) esquecido(s).", "ok")

        ConfirmModal(
            self.root, "Esquecer aparelhos",
            f"Esquecer os {quantidade} aparelho(s) pareado(s)? Eles precisarao "
            "parear de novo pelo QR ou pelo PIN.",
            confirm_label="Esquecer todos", on_confirm=confirmado, danger=True,
        ).show()

    # ---------------------------------------------------------------- extras

    def _open_usb(self) -> None:
        UsbModal(
            self.root, port=self.host.port, post=self.post, notify=self.show_toast,
        ).show()

    def _copy_address(self) -> None:
        self._copy(f"{self.host.guess_host()}:{self.host.port}", "Endereco")

    def _copy_fingerprint(self) -> None:
        self._copy(security.format_fingerprint(self.host.fingerprint), "Chave publica")

    def _copy(self, text: str, rotulo: str) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            pass
        self.show_toast(f"{rotulo} copiado.", "ok")

    def _toggle_autostart(self) -> None:
        desejado = self.autostart_toggle.get()
        ok, erro = platform_win.set_autostart(desejado)
        if not ok:
            self.autostart_toggle.set(not desejado)
            self.show_toast(f"Nao foi possivel alterar: {erro}", "error")
            return
        self.show_toast(
            "Poltergeist vai abrir junto com o Windows."
            if desejado else "Poltergeist nao abre mais sozinho.",
            "ok",
        )

    def _refresh_firewall(self) -> None:
        threading.Thread(target=self._firewall_worker, args=(False,), daemon=True).start()

    def _firewall_click(self) -> None:
        self.firewall_btn.set_enabled(False)
        threading.Thread(target=self._firewall_worker, args=(True,), daemon=True).start()

    def _firewall_worker(self, aplicar: bool) -> None:
        ativo = platform_win.firewall_enabled(self.host.port)
        if aplicar and not ativo:
            ok, erro = platform_win.open_firewall(self.host.port, self.host.discovery_port)
            if not ok:
                self.post(lambda: self._firewall_result(False, erro))
                return
            time.sleep(4.0)
            ativo = platform_win.firewall_enabled(self.host.port)
            self.post(lambda: self._firewall_result(ativo, "" if ativo else "ainda bloqueado"))
            return
        self.post(lambda: self._firewall_result(ativo, ""))

    def _firewall_result(self, ativo: bool, erro: str) -> None:
        self.firewall_btn.set_enabled(True)
        self.firewall_btn.set_text("Firewall liberado" if ativo else "Liberar firewall")
        self.firewall_btn.set_variant("success" if ativo else "ghost")
        if erro:
            self.show_toast(f"Firewall: {erro}", "error")
        elif ativo and self._state == "on":
            self.show_toast("Firewall liberado para a porta do Poltergeist.", "ok")

    # ---------------------------------------------------------------- bandeja

    def _start_tray(self) -> None:
        self._tray = GuiTray(self)
        if not self._tray.start():
            self._tray = None

    def hide_to_tray(self) -> None:
        if self._tray is None:
            self.quit()
            return
        self.root.withdraw()

    def show_window(self) -> None:
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    # ---------------------------------------------------------------- avisos

    def show_toast(self, texto: str, kind: str = "info") -> None:
        cores = {
            "info": (T.WINE, T.TEXT),
            "ok": (T.GREEN_SOFT, T.GREEN),
            "error": (T.RED_SOFT, T.RED),
        }
        fundo, frente = cores.get(kind, cores["info"])
        try:
            self._toast.configure(text=texto, bg=fundo, fg=frente)
            self._toast.place(relx=0.5, rely=1.0, anchor="s", y=-T.px(76))
            self._toast.lift()
        except tk.TclError:
            return
        if self._toast_after is not None:
            try:
                self.root.after_cancel(self._toast_after)
            except Exception:  # noqa: BLE001
                pass
        self._toast_after = self.root.after(4200, self._toast.place_forget)

    def _append_log(self, linha: str) -> None:
        if not self.log_text.winfo_exists():
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", linha + "\n")
        total = int(self.log_text.index("end-1c").split(".")[0])
        if total > 400:
            self.log_text.delete("1.0", "100.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ================================================================ loop

    def post(self, fn) -> None:
        """Agenda algo na thread da interface (usado por bandeja/threads)."""
        self._queue.put(fn)

    def _poll(self) -> None:
        try:
            while True:
                self._queue.get_nowait()()
        except queue.Empty:
            pass
        except tk.TclError:
            return

        if not self._alive():
            return

        try:
            while True:
                self._on_event(self.host.events.get_nowait())
        except queue.Empty:
            pass

        try:
            while True:
                self._append_log(self.log_queue.get_nowait())
        except queue.Empty:
            pass

        if not self._alive():
            return
        try:
            self.root.after(120, self._poll)
        except tk.TclError:
            pass

    def _refresh_fingerprint(self) -> None:
        """A chave publica so' existe depois que o servidor sobe (TLS)."""
        texto = _short_fingerprint(self.host.fingerprint)
        if self._fingerprint_label.cget("text") != texto:
            self._fingerprint_label.configure(text=texto)

    def _tick(self) -> None:
        if not self._alive():
            return
        self._tick_qr()
        self._refresh_sessions()
        self._refresh_fingerprint()
        if self.host.ready:
            self._refresh_devices()
        self._fit_content()
        try:
            self.root.after(1000, self._tick)
        except tk.TclError:
            pass

    def _alive(self) -> bool:
        try:
            return bool(self.root.winfo_exists())
        except tk.TclError:
            return False

    def _on_event(self, evento: tuple) -> None:
        tipo = evento[0]
        if tipo == "starting":
            self._set_state("starting")
        elif tipo == "ready":
            self._set_state("on")
            self.addr_label.configure(text=f"{evento[1]}:{evento[2]}")
            self.generate_qr()
            self._refresh_devices(force=True)
            self._refresh_sessions()
        elif tipo == "activity":
            quantidade = int(evento[1])
            nomes = str(evento[2])
            self._refresh_sessions()
            self._refresh_devices(force=True)
            if self._tray is not None:
                self._tray.update(quantidade > 0, quantidade)
            if quantidade > 0:
                self.show_toast(f"{nomes} conectado.", "ok")
        elif tipo == "error":
            self._set_state("off")
            self.show_toast(str(evento[1]), "error")
            self._append_log(f"erro: {evento[1]}")
        elif tipo == "stopped":
            self._set_state("off")

    # ================================================================ sair

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.show_toast("Encerrando...", "info")
        threading.Thread(target=self._shutdown, name="pd-quit", daemon=True).start()

    def _shutdown(self) -> None:
        try:
            self.host.stop()
        finally:
            self.post(self._destroy)

    def _destroy(self) -> None:
        if self._tray is not None:
            self._tray.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
