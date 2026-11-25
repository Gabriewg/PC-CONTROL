# SPDX-License-Identifier: AGPL-3.0-or-later
"""Salva um print da tela do PC (diagnostico)."""

from __future__ import annotations

import sys

import mss

factory = getattr(mss, "MSS", None) or mss.mss
with factory() as sct:
    shot = sct.grab(sct.monitors[1])
    mss.tools.to_png(shot.rgb, shot.size, output=sys.argv[1] if len(sys.argv) > 1 else "pc.png")
print("ok")
