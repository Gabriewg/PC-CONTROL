"""
Injecao de mouse e teclado no Windows via SendInput.

Nao usa nenhuma dependencia externa: apenas a API nativa do Windows (ctypes).
Isso garante baixa latencia e suporte a movimento absoluto (cursor vai direto
ao ponto tocado no celular), movimento relativo (estilo touchpad) e teclado
com acentos/unicode.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

# ---------------------------------------------------------------- constantes

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSE_MOVE = 0x0001
MOUSE_LEFT_DOWN = 0x0002
MOUSE_LEFT_UP = 0x0004
MOUSE_RIGHT_DOWN = 0x0008
MOUSE_RIGHT_UP = 0x0010
MOUSE_MIDDLE_DOWN = 0x0020
MOUSE_MIDDLE_UP = 0x0040
MOUSE_WHEEL = 0x0800
MOUSE_HWHEEL = 0x1000
MOUSE_ABSOLUTE = 0x8000
MOUSE_VIRTUAL_DESK = 0x4000

KEY_EXTENDED = 0x0001
KEY_UP = 0x0002
KEY_UNICODE = 0x0004
KEY_SCANCODE = 0x0008

MAPVK_VK_TO_VSC = 0

# Teclas virtuais (Virtual-Key codes)
VK = {
    "esc": 0x1B,
    "tab": 0x09,
    "enter": 0x0D,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "space": 0x20,
    "capslock": 0x14,
    "numlock": 0x90,
    "printscreen": 0x2C,
    "win": 0x5B,
    "apps": 0x5D,
    "ctrl": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}

# Teclas que no Windows precisam do flag "extended"
_EXTENDED_VKS = {
    0x25, 0x26, 0x27, 0x28,  # setas
    0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22,  # insert/delete/home/end/pgup/pgdn
    0x5D, 0x5C, 0x2C,       # apps, rwin, printscreen
}


# ---------------------------------------------------------------- estruturas

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
user32.MapVirtualKeyW.restype = wintypes.UINT


def _send(inputs: list[INPUT]) -> None:
    if not inputs:
        return
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError(ctypes.get_last_error(), "SendInput falhou")


def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    item = INPUT()
    item.type = INPUT_MOUSE
    item.mi = MOUSEINPUT(dx, dy, wintypes.DWORD(data & 0xFFFFFFFF), flags, 0, 0)
    return item


def _key(vk: int, up: bool, scan_only: bool = False) -> INPUT:
    item = INPUT()
    item.type = INPUT_KEYBOARD
    flags = 0
    if up:
        flags |= KEY_UP
    if vk in _EXTENDED_VKS:
        flags |= KEY_EXTENDED
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    if scan_only:
        flags |= KEY_SCANCODE
        item.ki = KEYBDINPUT(0, scan, flags, 0, 0)
    else:
        # wVk + wScan juntos: funciona em apps normais e tambem na tecla Win
        # (o Windows ignora Win quando enviamos apenas o scancode).
        item.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return item


def _unicode_char(ch: str, up: bool) -> INPUT:
    item = INPUT()
    item.type = INPUT_KEYBOARD
    flags = KEY_UNICODE | (KEY_UP if up else 0)
    item.ki = KEYBDINPUT(0, ord(ch), flags, 0, 0)
    return item


# ---------------------------------------------------------------- utilitarios

def init_dpi() -> None:
    """Deixa o processo DPI-aware para que coordenadas reais == pixels capturados."""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == -4
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def virtual_bounds() -> tuple[int, int, int, int]:
    """Retorna (x, y, largura, altura) da area total de todos os monitores."""
    gsm = user32.GetSystemMetrics
    return gsm(76), gsm(77), gsm(78), gsm(79)


def cursor_pos() -> tuple[int, int]:
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


# ---------------------------------------------------------------- mouse

class Mouse:
    """Estado do mouse remoto. bbox = regiao da tela exibida no celular."""

    def __init__(self) -> None:
        self.bbox = (0, 0, 1920, 1080)
        self._virtual = virtual_bounds()
        self._buttons = set()

    def set_bbox(self, bbox: tuple[int, int, int, int]) -> None:
        self.bbox = bbox
        self._virtual = virtual_bounds()

    def move_abs(self, nx: float, ny: float) -> None:
        """Move para posicao normalizada (0..1) dentro da tela capturada."""
        bx, by, bw, bh = self.bbox
        vx, vy, vw, vh = self._virtual
        x = bx + max(0.0, min(1.0, nx)) * bw
        y = by + max(0.0, min(1.0, ny)) * bh
        ax = int(round((x - vx) / max(1, vw) * 65535))
        ay = int(round((y - vy) / max(1, vh) * 65535))
        ax = max(0, min(65535, ax))
        ay = max(0, min(65535, ay))
        _send([_mouse(MOUSE_MOVE | MOUSE_ABSOLUTE | MOUSE_VIRTUAL_DESK, ax, ay)])

    def move_rel(self, dx: float, dy: float) -> None:
        dx = int(round(dx))
        dy = int(round(dy))
        if dx == 0 and dy == 0:
            return
        _send([_mouse(MOUSE_MOVE, dx, dy)])

    def button(self, btn: str, down: bool) -> None:
        flags = {
            ("left", True): MOUSE_LEFT_DOWN,
            ("left", False): MOUSE_LEFT_UP,
            ("right", True): MOUSE_RIGHT_DOWN,
            ("right", False): MOUSE_RIGHT_UP,
            ("middle", True): MOUSE_MIDDLE_DOWN,
            ("middle", False): MOUSE_MIDDLE_UP,
        }.get((btn, down))
        if flags is None:
            return
        _send([_mouse(flags)])

    def click(self, btn: str = "left") -> None:
        self.button(btn, True)
        self.button(btn, False)

    def double_click(self, btn: str = "left") -> None:
        self.click(btn)
        # intervalo curto para o Windows reconhecer como duplo clique
        ctypes.windll.kernel32.Sleep(30)
        self.click(btn)

    def scroll(self, dy: float, dx: float = 0.0) -> None:
        events = []
        if dy:
            events.append(_mouse(MOUSE_WHEEL, data=int(round(dy))))
        if dx:
            events.append(_mouse(MOUSE_HWHEEL, data=int(round(dx))))
        _send(events)


# ---------------------------------------------------------------- teclado

class Keyboard:
    def __init__(self) -> None:
        self._held: set[str] = set()

    def _vk(self, key: str) -> int | None:
        key = key.lower()
        if key in VK:
            return VK[key]
        if len(key) == 1:
            ch = key.upper()
            if "A" <= ch <= "Z" or "0" <= ch <= "9":
                return ord(ch)
        return None

    def tap(self, key: str, mods: list[str] | None = None) -> None:
        vk = self._vk(key)
        if vk is None:
            return
        mods = [m for m in (mods or []) if self._vk(m) is not None]
        events: list[INPUT] = []
        for mod in mods:
            events.append(_key(self._vk(mod), False))
        events.append(_key(vk, False))
        events.append(_key(vk, True))
        for mod in reversed(mods):
            events.append(_key(self._vk(mod), True))
        _send(events)

    def type_text(self, text: str) -> None:
        events: list[INPUT] = []
        for ch in text:
            if ch == "\n" or ch == "\r":
                events.append(_key(VK["enter"], False))
                events.append(_key(VK["enter"], True))
                continue
            if ch == "\t":
                events.append(_key(VK["tab"], False))
                events.append(_key(VK["tab"], True))
                continue
            # surrogate pairs (emoji) precisam de duas unidades UTF-16
            encoded = ch.encode("utf-16-le")
            for i in range(0, len(encoded), 2):
                unit = int.from_bytes(encoded[i:i + 2], "little")
                events.append(_unicode_unit(unit, False))
                events.append(_unicode_unit(unit, True))
        _send(events)


def _unicode_unit(unit: int, up: bool) -> INPUT:
    item = INPUT()
    item.type = INPUT_KEYBOARD
    item.ki = KEYBDINPUT(0, unit, KEY_UNICODE | (KEY_UP if up else 0), 0, 0)
    return item
