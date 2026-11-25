#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gera os icones do build a partir do icon.jpg.

- poltergeist.ico : icone do .exe e dos atalhos (varios tamanhos)
- brand.png      : versao pequena usada na bandeja e na janela (o icon.jpg
                   original tem 2,6 MB e nao vale embutir no executavel)
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

AQUI = Path(__file__).resolve().parent
ORIGEM = AQUI.parent / "icon.jpg"
ICONE = AQUI / "poltergeist.ico"
MARCA = AQUI / "brand.png"


def main() -> int:
    if not ORIGEM.exists():
        print(f"erro: {ORIGEM} nao encontrado.")
        return 1

    img = Image.open(ORIGEM).convert("RGBA")
    lado = min(img.size)
    esquerda = (img.width - lado) // 2
    topo = (img.height - lado) // 2
    quadrada = img.crop((esquerda, topo, esquerda + lado, topo + lado))

    marca = quadrada.resize((192, 192), Image.LANCZOS)
    marca.save(MARCA, format="PNG", optimize=True)

    tamanhos = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    quadrada.resize((256, 256), Image.LANCZOS).save(
        ICONE, format="ICO", sizes=tamanhos
    )

    print(f"icone: {ICONE}")
    print(f"marca: {MARCA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
