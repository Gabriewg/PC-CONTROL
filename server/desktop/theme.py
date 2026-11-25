# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paleta e medidas do Poltergeist Desktop.

A identidade e' preto profundo com vinho escuro: o fundo fica quase preto, os
cartoes um tom acima e o vinho aparece so' no que importa (acao principal,
estado ligado, destaque do QR).
"""

from __future__ import annotations

# ------------------------------------------------------------------ cores

BG = "#0A0608"          # fundo da janela
BG_DEEP = "#070405"     # faixas e rodape
CARD = "#150D11"        # cartoes
CARD_SOFT = "#1B1117"   # campos, areas internas
CARD_HOVER = "#201419"
BORDER = "#2A1A21"      # contorno dos cartoes
BORDER_SOFT = "#201319"

WINE = "#4A0F1E"
WINE_DEEP = "#330A14"
ACCENT = "#8E1B36"      # botao principal / estado ligado
ACCENT_HOVER = "#A82443"
ACCENT_PRESS = "#6E1329"
ACCENT_SOFT = "#3A1220"

TEXT = "#F4EDEA"
TEXT_MUTED = "#A08E94"
TEXT_DIM = "#6E5D63"

GREEN = "#3ECF8E"
GREEN_SOFT = "#12352A"
RED = "#E5646B"
RED_SOFT = "#33141A"
YELLOW = "#E5B45A"

WHITE = "#FFFFFF"

# ------------------------------------------------------------------ fontes

FONT = "Segoe UI"
FONT_MONO = "Consolas"

# Tamanhos em pontos (o Tk converte para pixels conforme o DPI).
F_DISPLAY = (FONT, 21, "bold")
F_TITLE = (FONT, 13, "bold")
F_SUBTITLE = (FONT, 11, "bold")
F_BODY = (FONT, 10)
F_BODY_BOLD = (FONT, 10, "bold")
F_SMALL = (FONT, 9)
F_SMALL_BOLD = (FONT, 9, "bold")
F_TINY = (FONT, 8)
F_MONO = (FONT_MONO, 9)
F_MONO_SMALL = (FONT_MONO, 8)

# ------------------------------------------------------------------ medidas

_SCALE = 1.0


def set_scale(value: float) -> None:
    """Fator de escala do monitor (1.0 = 96 DPI)."""
    global _SCALE
    _SCALE = max(0.75, min(3.0, float(value)))


def get_scale() -> float:
    return _SCALE


def px(value: float) -> int:
    """Converte uma medida de projeto (96 DPI) para pixels da tela atual."""
    return int(round(value * _SCALE))


# Medidas de projeto mais usadas.
RADIUS = px(16)
RADIUS_SM = px(10)
PAD = px(18)
GAP = px(14)
