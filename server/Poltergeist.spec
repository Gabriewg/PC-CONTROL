# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build do Poltergeist.exe (PyInstaller, arquivo unico, sem console).

Nada de segredo entra aqui: pin.txt, cert.pem, key.pem, devices.json e
auth_state.json sao criados em %LOCALAPPDATA%\\Poltergeist na primeira execucao.
O dxcam fica de fora (dependencia opcional): sem ele o servidor usa GDI.
"""

from pathlib import Path

RAIZ = Path(SPECPATH).resolve()                 # server/
REPO = RAIZ.parent
ICONE = RAIZ / "poltergeist.ico"
MARCA = RAIZ / "brand.png"

if not ICONE.exists() or not MARCA.exists():
    raise SystemExit("Rode 'python gerar_icone_exe.py' antes do PyInstaller.")

a = Analysis(
    [str(RAIZ / "app.py")],
    pathex=[str(RAIZ)],
    binaries=[],
    datas=[(str(MARCA), ".")],
    hiddenimports=[
        "pystray._win32",
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "dxcam",        # opcional: sem ele a captura cai para GDI
        "comtypes",     # so' era usado pelo dxcam
        "pytest",
        "tkinter.test",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Poltergeist",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICONE),
    version=str(RAIZ / "version_info.txt"),
)
