# SPDX-License-Identifier: AGPL-3.0-or-later
"""Widgets desenhados no Canvas para o tema preto/vinho.

O Tk classico tem cara de Windows 95; aqui os cartoes, botoes, chaves e barras
sao desenhados com cantos arredondados e as cores do `theme.py`.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

from . import theme as T


# ------------------------------------------------------------------ utilidades


def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, radius, **kwargs):
    """Retangulo de cantos arredondados (poligono suavizado)."""
    r = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


def font_of(spec, size_delta: int = 0):
    family, size, *rest = spec
    return (family, size + size_delta, *rest)


def _exists(widget) -> bool:
    """winfo_exists sem explodir quando a janela ja foi destruida."""
    try:
        return bool(widget.winfo_exists())
    except tk.TclError:
        return False


# ------------------------------------------------------------------ cartao


class Card(tk.Canvas):
    """Cartao arredondado com um Frame interno para o conteudo.

    `fill=False` deixa a altura acompanhar o conteudo; `fill=True` ocupa toda a
    celula do grid/pack (usado no painel de atividade).
    """

    def __init__(
        self,
        master,
        *,
        pad: int | None = None,
        radius: int | None = None,
        fill: bool = False,
        bg: str = T.BG,
        card: str = T.CARD,
        border: str = T.BORDER,
        **kwargs,
    ) -> None:
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, **kwargs)
        self._pad = T.PAD if pad is None else pad
        self._radius = T.RADIUS if radius is None else radius
        self._fill = fill
        self._card = card
        self._border = border
        self._target_height = 0
        self._body = tk.Frame(self, bg=card)
        self._window = self.create_window(
            self._pad, self._pad, anchor="nw", window=self._body
        )
        self.bind("<Configure>", self._on_configure)
        self._body.bind("<Configure>", self._on_body_configure)

    @property
    def body(self) -> tk.Frame:
        return self._body

    def _on_configure(self, event) -> None:
        w, h = max(2, event.width), max(2, event.height)
        self.delete("cardbg")
        round_rect(
            self, 1, 1, w - 1, h - 1, self._radius,
            fill=self._card, outline=self._border, width=1, tags="cardbg",
        )
        self.tag_lower("cardbg")
        self.coords(self._window, self._pad, self._pad)
        self.itemconfigure(self._window, width=max(1, w - 2 * self._pad))
        if self._fill:
            self.itemconfigure(self._window, height=max(1, h - 2 * self._pad))

    def _on_body_configure(self, _event=None) -> None:
        if self._fill:
            return
        target = self._body.winfo_reqheight() + 2 * self._pad
        if abs(target - self._target_height) > 1:
            self._target_height = target
            self.configure(height=target)


# ------------------------------------------------------------------ botao


class Button(tk.Canvas):
    """Botao com hover/press e quatro variantes visuais."""

    VARIANTS = {
        "primary": (T.ACCENT, T.ACCENT_HOVER, T.ACCENT_PRESS, "", T.WHITE),
        "secondary": (T.CARD_SOFT, T.CARD_HOVER, T.WINE_DEEP, T.BORDER, T.TEXT),
        "ghost": (T.CARD, T.CARD_HOVER, T.WINE_DEEP, "", T.TEXT_MUTED),
        "danger": (T.CARD, T.RED_SOFT, T.RED_SOFT, T.BORDER, T.RED),
        "success": (T.GREEN_SOFT, "#184634", "#0E2A20", "", T.GREEN),
    }

    def __init__(
        self,
        master,
        text: str,
        command=None,
        *,
        variant: str = "secondary",
        icon: str = "",
        height: int | None = None,
        width: int | None = None,
        min_width: int = 0,
        padx: int | None = None,
        radius: int | None = None,
        font=None,
        bg: str = T.BG,
        anchor: str = "center",
    ) -> None:
        h = T.px(38) if height is None else height
        self._radius = T.RADIUS_SM if radius is None else radius
        self._font = font or T.F_BODY_BOLD
        self._padx = T.px(16) if padx is None else padx
        self._text = text
        self._icon = icon
        self._variant = variant
        self._command = command
        self._enabled = True
        self._hover = False
        self._pressed = False

        measure = tkfont.Font(font=self._font)
        icon_w = measure.measure(icon) + T.px(8) if icon else 0
        needed = measure.measure(text) + icon_w + 2 * self._padx
        super().__init__(
            master,
            width=width if width is not None else max(min_width, needed),
            height=h,
            bg=bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    # ------------------------------------------------------------ estado

    def set_text(self, text: str) -> None:
        self._text = text
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def set_variant(self, variant: str) -> None:
        self._variant = variant
        self._draw()

    # ------------------------------------------------------------ desenho

    def _colors(self):
        fill, hover, press, outline, fg = self.VARIANTS[self._variant]
        if not self._enabled:
            return T.CARD_SOFT, "", T.TEXT_DIM
        if self._pressed:
            return press, "", fg
        if self._hover:
            return hover, outline, fg
        return fill, outline, fg

    def _draw(self) -> None:
        if not _exists(self):
            return
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1:
            w = int(float(self["width"]))
        if h <= 1:
            h = int(float(self["height"]))
        fill, outline, fg = self._colors()
        round_rect(
            self, 0, 0, w - 1, h - 1, self._radius,
            fill=fill, outline=outline or fill, width=1,
        )
        if self._icon:
            self.create_text(
                self._padx, h / 2, text=self._icon, anchor="w",
                fill=fg, font=self._font,
            )
            self.create_text(
                self._padx + tkfont.Font(font=self._font).measure(self._icon) + T.px(8),
                h / 2, text=self._text, anchor="w", fill=fg, font=self._font,
            )
        else:
            self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=self._font)

    # ------------------------------------------------------------ eventos

    def _on_enter(self, _e=None) -> None:
        if self._enabled:
            self._hover = True
            self._draw()

    def _on_leave(self, _e=None) -> None:
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, _e=None) -> None:
        if self._enabled:
            self._pressed = True
            self._draw()

    def _on_release(self, event) -> None:
        if not self._enabled:
            return
        was = self._pressed
        self._pressed = False
        self._draw()
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        if was and inside and self._command is not None:
            self._command()


class LinkButton(tk.Label):
    """Link de texto discreto (ex.: 'Trocar PIN')."""

    def __init__(self, master, text: str, command=None, *, bg: str = T.CARD) -> None:
        super().__init__(
            master, text=text, bg=bg, fg=T.ACCENT_HOVER,
            font=T.F_SMALL_BOLD, cursor="hand2", bd=0,
        )
        self._command = command
        self.bind("<Button-1>", lambda _e: command() if command else None)
        self.bind("<Enter>", lambda _e: self.configure(fg=T.TEXT))
        self.bind("<Leave>", lambda _e: self.configure(fg=T.ACCENT_HOVER))


# ------------------------------------------------------------------ chave


class Toggle(tk.Canvas):
    """Chave liga/desliga com animacao curta."""

    def __init__(
        self,
        master,
        value: bool = False,
        command=None,
        *,
        width: int | None = None,
        height: int | None = None,
        bg: str = T.BG,
    ) -> None:
        self._track_w = T.px(52) if width is None else width
        self._track_h = T.px(30) if height is None else height
        super().__init__(
            master, width=self._track_w, height=self._track_h, bg=bg,
            highlightthickness=0, bd=0, cursor="hand2",
        )
        self._value = bool(value)
        self._command = command
        self._pos = 1.0 if value else 0.0
        self._after = None
        self.bind("<Button-1>", self._click)
        self.bind("<Configure>", lambda _e: self._draw())

    def get(self) -> bool:
        return self._value

    def set(self, value: bool, notify: bool = False) -> None:
        value = bool(value)
        if value == self._value:
            return
        self._value = value
        self._animate()
        if notify and self._command is not None:
            self._command()

    def _click(self, _e=None) -> None:
        self._value = not self._value
        self._animate()
        if self._command is not None:
            self._command()

    def _animate(self) -> None:
        target = 1.0 if self._value else 0.0
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except Exception:  # noqa: BLE001
                pass
            self._after = None
        step = 0.18 if target > self._pos else -0.18
        self._pos = max(0.0, min(1.0, self._pos + step))
        self._draw()
        if self._pos != target:
            try:
                self._after = self.after(14, self._animate)
            except tk.TclError:
                self._after = None

    def _draw(self) -> None:
        if not _exists(self):
            return
        self.delete("all")
        w, h = self._track_w, self._track_h
        r = h / 2
        track = T.ACCENT if self._value else T.CARD_SOFT
        outline = T.ACCENT_HOVER if self._value else T.BORDER
        round_rect(self, 1, 1, w - 1, h - 1, r, fill=track, outline=outline, width=1)
        knob = h - T.px(8)
        x0 = T.px(4) + self._pos * (w - knob - T.px(8))
        self.create_oval(
            x0, T.px(4), x0 + knob, T.px(4) + knob,
            fill=T.WHITE if self._value else T.TEXT_MUTED, outline="",
        )


# ------------------------------------------------------------------ diversos


class StatusPill(tk.Canvas):
    """Selo de estado com bolinha colorida."""

    def __init__(self, master, *, bg: str = T.BG) -> None:
        super().__init__(
            master, width=T.px(120), height=T.px(30), bg=bg,
            highlightthickness=0, bd=0,
        )
        self._active = False
        self._text = "Servidor parado"
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, active: bool, text: str) -> None:
        self._active = bool(active)
        self._text = text
        self._draw()

    def _draw(self) -> None:
        if not _exists(self):
            return
        self.delete("all")
        h = T.px(30)
        f = tkfont.Font(font=T.F_SMALL_BOLD)
        w = f.measure(self._text) + T.px(40)
        self.configure(width=w)
        round_rect(
            self, 0, 0, w - 1, h - 1, h / 2,
            fill=T.GREEN_SOFT if self._active else T.CARD_SOFT,
            outline=T.GREEN if self._active else T.BORDER, width=1,
        )
        cor = T.GREEN if self._active else T.TEXT_DIM
        self.create_oval(T.px(12), h / 2 - 3, T.px(18), h / 2 + 3, fill=cor, outline="")
        self.create_text(
            T.px(26), h / 2, text=self._text, anchor="w",
            fill=T.GREEN if self._active else T.TEXT_MUTED, font=T.F_SMALL_BOLD,
        )


class ProgressBar(tk.Canvas):
    """Barra fina usada na validade do QR."""

    def __init__(self, master, *, height: int | None = None, bg: str = T.CARD) -> None:
        h = T.px(4) if height is None else height
        super().__init__(master, height=h, bg=bg, highlightthickness=0, bd=0)
        self._h = h
        self._fraction = 0.0
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, fraction: float) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self._draw()

    def _draw(self) -> None:
        if not _exists(self):
            return
        self.delete("all")
        w = self.winfo_width()
        if w <= 1:
            return
        h = self._h
        round_rect(self, 0, 0, w - 1, h - 1, h / 2, fill=T.CARD_SOFT, outline="")
        if self._fraction > 0:
            round_rect(
                self, 0, 0, max(h, w * self._fraction) - 1, h - 1, h / 2,
                fill=T.ACCENT_HOVER, outline="",
            )


class Divider(tk.Frame):
    def __init__(self, master, *, bg: str = T.CARD, color: str | None = None) -> None:
        super().__init__(master, height=1, bg=color or T.BORDER_SOFT)
        self.pack_propagate(False)


# ------------------------------------------------------------------ modal


class Modal(tk.Toplevel):
    """Janela modal sem barra nativa, no mesmo tema."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        subtitle: str = "",
        *,
        width: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=T.BG)
        self.transient(parent)
        self._parent = parent
        self._width = T.px(430) if width is None else width
        self._pad = T.px(22)

        self._canvas = tk.Canvas(self, bg=T.BG, highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)
        self._body = tk.Frame(self._canvas, bg=T.CARD)
        self._win = self._canvas.create_window(
            self._pad, self._pad, anchor="nw", window=self._body
        )
        self._canvas.bind("<Configure>", self._on_configure)

        header = tk.Frame(self._body, bg=T.CARD)
        header.pack(fill="x")
        self._header = header
        tk.Label(
            header, text=title, bg=T.CARD, fg=T.TEXT, font=T.F_TITLE, anchor="w",
        ).pack(side="left")
        close = tk.Label(
            header, text="\u00d7", bg=T.CARD, fg=T.TEXT_MUTED,
            font=(T.FONT, 15), cursor="hand2", padx=T.px(6),
        )
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: self.cancel())
        close.bind("<Enter>", lambda _e: close.configure(fg=T.TEXT))
        close.bind("<Leave>", lambda _e: close.configure(fg=T.TEXT_MUTED))
        if subtitle:
            tk.Label(
                self._body, text=subtitle, bg=T.CARD, fg=T.TEXT_MUTED,
                font=T.F_SMALL, anchor="w", justify="left", wraplength=self._width - 2 * self._pad,
            ).pack(fill="x", pady=(T.px(6), 0))

        self.content = tk.Frame(self._body, bg=T.CARD)
        self.content.pack(fill="both", expand=True, pady=(T.px(16), 0))

        for widget in (header, self._body):
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)

        self.bind("<Escape>", lambda _e: self.cancel())
        self._drag_from = (0, 0)

    # ------------------------------------------------------------ ciclo

    def show(self) -> None:
        self.update_idletasks()
        h = self._body.winfo_reqheight() + 2 * self._pad
        parent = self._parent
        try:
            px = parent.winfo_rootx() + (parent.winfo_width() - self._width) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        except Exception:  # noqa: BLE001
            px = py = 120
        px = max(0, px)
        py = max(0, py)
        self.geometry(f"{self._width}x{h}+{px}+{py}")
        self.deiconify()
        self.lift()
        self.grab_set()
        self.focus_force()

    def cancel(self) -> None:
        try:
            self.grab_release()
        except Exception:  # noqa: BLE001
            pass
        self.destroy()

    # ------------------------------------------------------------ layout

    def _on_configure(self, event) -> None:
        w, h = max(2, event.width), max(2, event.height)
        self._canvas.delete("modalbg")
        round_rect(
            self._canvas, 1, 1, w - 1, h - 1, T.RADIUS,
            fill=T.CARD, outline=T.BORDER, width=1, tags="modalbg",
        )
        self._canvas.tag_lower("modalbg")
        self._canvas.coords(self._win, self._pad, self._pad)
        self._canvas.itemconfigure(self._win, width=max(1, w - 2 * self._pad))

    # ------------------------------------------------------------ arrastar

    def _start_drag(self, event) -> None:
        self._drag_from = (event.x_root, event.y_root)
        self._origin = (self.winfo_x(), self.winfo_y())

    def _drag(self, event) -> None:
        dx = event.x_root - self._drag_from[0]
        dy = event.y_root - self._drag_from[1]
        self.geometry(f"+{self._origin[0] + dx}+{self._origin[1] + dy}")


def entry(master, *, show: str | None = None, font=None) -> tk.Entry:
    """Entry com o visual dos campos escuros."""
    return tk.Entry(
        master,
        bg=T.CARD_SOFT,
        fg=T.TEXT,
        insertbackground=T.TEXT,
        disabledbackground=T.CARD_SOFT,
        disabledforeground=T.TEXT_DIM,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=T.BORDER,
        highlightcolor=T.ACCENT_HOVER,
        font=font or T.F_BODY,
        show=show or "",
    )
