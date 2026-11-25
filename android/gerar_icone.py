# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gera os mipmaps do icone do app a partir de icon.jpg.

Rode de qualquer lugar:
    .venv\\Scripts\\python.exe android/gerar_icone.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

RAIZ = Path(__file__).resolve().parent
SRC = RAIZ.parent / "icon.jpg"
RES = RAIZ / "app" / "src" / "main" / "res"

# densidade -> fator (mdpi=1x, hdpi=1.5x, ...)
DENSIDADES = {"mdpi": 1.0, "hdpi": 1.5, "xhdpi": 2.0, "xxhdpi": 3.0, "xxxhdpi": 4.0}

# Folga em volta do assunto no recorte quadrado (1.10 = 10% de margem).
MARGEM = 1.10
# Quanto do canvas do icone adaptativo o assunto ocupa (o launcher recorta as bordas).
ESCALA_FG = 0.78
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
    assumir que ele ja esta no centro da imagem.
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


def icone_adaptativo(original: Image.Image, recorte: Image.Image, lado: int) -> Image.Image:
    """Foreground do icone adaptativo (Android 8+).

    O launcher aplica a mascara (circulo, squircle...) e recorta as bordas. Para
    o desenho nao perder as pontas, ele e reduzido e centralizado sobre o fundo
    esticado da propria arte.
    """
    fundo = original.resize((lado, lado), Image.LANCZOS)
    alvo = int(lado * ESCALA_FG)
    fig = recorte.resize((alvo, alvo), Image.LANCZOS)
    deslocamento = (lado - alvo) // 2
    fundo.paste(fig, (deslocamento, deslocamento))
    return fundo


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"nao encontrei {SRC}")

    original = Image.open(SRC).convert("RGB")
    base = recorte_quadrado(original)

    preview = RAIZ / "preview_icone.png"
    base.resize((512, 512), Image.LANCZOS).save(preview)

    for nome, escala in DENSIDADES.items():
        pasta = RES / f"mipmap-{nome}"
        pasta.mkdir(parents=True, exist_ok=True)

        # icone legado (Android < 8): bitmap quadrado com cantos arredondados
        lado = int(48 * escala)
        com_cantos(base.resize((lado, lado), Image.LANCZOS)).save(
            pasta / "ic_launcher.png", optimize=True
        )

        # foreground do icone adaptativo: assunto centralizado e reduzido para
        # caber na area segura do launcher
        lado_fg = int(108 * escala)
        icone_adaptativo(original, base, lado_fg).save(
            pasta / "ic_launcher_foreground.png", optimize=True
        )
        print(f"mipmap-{nome}: {lado}px / foreground {lado_fg}px")

    print("pronto:", preview)


if __name__ == "__main__":
    main()
