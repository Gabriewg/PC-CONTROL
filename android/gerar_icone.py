# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gera os mipmaps do icone do app a partir de icon.jpg.

O icone e' exatamente a arte de icon.jpg: nada e' desenhado nem redesenhado.
So' recortamos a margem sobrando em volta do assunto e geramos as densidades.

Rode de qualquer lugar:
    .venv\\Scripts\\python.exe android/gerar_icone.py
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

RAIZ = Path(__file__).resolve().parent
SRC = RAIZ.parent / "icon.jpg"
RES = RAIZ / "app" / "src" / "main" / "res"

# densidade -> fator (mdpi=1x, hdpi=1.5x, ...)
DENSIDADES = {"mdpi": 1.0, "hdpi": 1.5, "xhdpi": 2.0, "xxhdpi": 3.0, "xxxhdpi": 4.0}

# Folga em volta do assunto no recorte quadrado (1.10 = 10% de margem).
MARGEM = 1.10
# Quanto do canvas do icone adaptativo o assunto ocupa. O launcher recorta as
# bordas: 0.57 deixa a arte inteira (inclusive os pes e a cabeca) dentro da
# area segura, que e' um circulo de 72/108 = 0.667 do canvas.
ESCALA_FG = 0.57
# Diferenca minima de cor para considerar um pixel como "assunto" e nao fundo.
LIMIAR = 40


def cor_fundo(img: Image.Image) -> tuple[int, int, int]:
    """Cor media dos cantos, usada para separar o assunto do fundo."""
    w, h = img.size
    pontos = ((2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3))
    amostras = [img.getpixel(p) for p in pontos]
    return tuple(sum(c[i] for c in amostras) // len(amostras) for i in range(3))


def recorte_quadrado(img: Image.Image) -> Image.Image:
    """Recorta um quadrado em volta do assunto, com folga.

    Detecta a area que difere do fundo para centralizar o desenho, em vez de
    assumir que ele ja esta no centro da imagem. O conteudo nao e' alterado:
    apenas a margem sobrando e' descartada.
    """
    fundo = Image.new("RGB", img.size, cor_fundo(img))
    diff = ImageChops.difference(img, fundo).convert("L")
    mascara = diff.point(lambda p: 255 if p > LIMIAR else 0)
    caixa = mascara.getbbox() or (0, 0, img.size[0], img.size[1])

    x0, y0, x1, y1 = caixa
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    lado = int(max(x1 - x0, y1 - y0) * MARGEM)
    lado = min(lado, img.size[0], img.size[1])

    x = max(0, min(img.size[0] - lado, cx - lado // 2))
    y = max(0, min(img.size[1] - lado, cy - lado // 2))
    return img.crop((x, y, x + lado, y + lado))


def com_cantos(img: Image.Image, raio: float = 0.22) -> Image.Image:
    """Aplica cantos arredondados com transparencia (icone legado)."""
    lado = img.size[0]
    mascara = Image.new("L", (lado, lado), 0)
    ImageDraw.Draw(mascara).rounded_rectangle(
        (0, 0, lado - 1, lado - 1), radius=int(lado * raio), fill=255
    )
    out = img.convert("RGBA")
    out.putalpha(mascara)
    return out


def cor_icon_bg() -> str:
    """Le o valor atual de icon_bg em res/values/colors.xml."""
    arvore = ET.parse(RES / "values" / "colors.xml")
    for item in arvore.getroot().findall("color"):
        if item.get("name") == "icon_bg":
            return (item.text or "").strip()
    return ""


def foreground(base: Image.Image, lado: int) -> Image.Image:
    """Camada da frente do icone adaptativo (Android 8+).

    So' a arte, reduzida e centralizada, sobre fundo transparente. O fundo do
    icone adaptativo e' @color/icon_bg, que o gerador confere ser a cor media
    dos cantos de icon.jpg (a mesma moldura da arte).
    """
    alvo = int(lado * ESCALA_FG)
    fig = base.resize((alvo, alvo), Image.LANCZOS).convert("RGBA")
    out = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    deslocamento = (lado - alvo) // 2
    out.alpha_composite(fig, (deslocamento, deslocamento))
    return out


def preview(base: Image.Image, cor: tuple[int, int, int]) -> Image.Image:
    """Monta um preview: icone legado + adaptativo recortado em circulo."""
    lado = 256
    margem = 24
    canvas = Image.new("RGB", (lado * 2 + margem * 3, lado + margem * 2), (32, 24, 28))

    legado = com_cantos(base.resize((lado, lado), Image.LANCZOS))
    canvas.paste(legado, (margem, margem), legado)

    # Simula a mascara circular do launcher (area segura de 72/108 do canvas).
    adapt = Image.new("RGBA", (lado, lado), cor + (255,))
    fig = base.resize(
        (int(lado * ESCALA_FG), int(lado * ESCALA_FG)), Image.LANCZOS
    ).convert("RGBA")
    adapt.alpha_composite(fig, ((lado - fig.width) // 2, (lado - fig.height) // 2))
    mascara = Image.new("L", (lado, lado), 0)
    raio = int(lado * (72 / 108) / 2)
    centro = lado // 2
    ImageDraw.Draw(mascara).ellipse(
        (centro - raio, centro - raio, centro + raio, centro + raio), fill=255
    )
    canvas.paste(adapt, (lado + margem * 2, margem), mascara)

    return canvas


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"nao encontrei {SRC}")

    original = Image.open(SRC).convert("RGB")
    base = recorte_quadrado(original)
    cor = cor_fundo(original)

    preview(base, cor).save(RAIZ / "preview_icone.png", optimize=True)

    hex_cor = f"#{cor[0]:02X}{cor[1]:02X}{cor[2]:02X}"
    atual = cor_icon_bg()
    if atual.upper() == hex_cor.upper():
        print(f"icon_bg confere: {hex_cor}")
    else:
        print(
            f"aviso: icon_bg em colors.xml e' {atual or '(vazio)'}; "
            f"o ideal para emendar com a arte e' {hex_cor}"
        )

    for nome, escala in DENSIDADES.items():
        pasta = RES / f"mipmap-{nome}"
        pasta.mkdir(parents=True, exist_ok=True)

        # icone legado (Android < 8): bitmap quadrado com cantos arredondados
        lado = int(48 * escala)
        com_cantos(base.resize((lado, lado), Image.LANCZOS)).save(
            pasta / "ic_launcher.png", optimize=True
        )

        # foreground do icone adaptativo: arte centralizada dentro da area segura
        lado_fg = int(108 * escala)
        foreground(base, lado_fg).save(
            pasta / "ic_launcher_foreground.png", optimize=True
        )
        print(f"mipmap-{nome}: {lado}px / foreground {lado_fg}px")

    print("pronto:", RAIZ / "preview_icone.png")


if __name__ == "__main__":
    main()
