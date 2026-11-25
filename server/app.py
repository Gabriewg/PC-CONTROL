#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Poltergeist Desktop: a janela unica do servidor no Windows.

Este e' o ponto de entrada do Poltergeist.exe. Ele abre a interface, liga o
servidor na mesma hora e cuida de QR, PIN, aparelhos e sessoes - sem console e
sem .bat. Os dados (PIN, certificado, aparelhos) ficam em
%LOCALAPPDATA%\\Poltergeist quando empacotado; rodando pelo Python, ficam ao
lado do server.py.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import queue
import sys
import tkinter as tk
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from desktop import logbus, platform_win
from desktop import theme as T
from desktop.host import ServerHost
from desktop.window import MainWindow

import server as srv


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="Poltergeist",
        description="Janela do servidor Poltergeist (controle remoto local).",
    )
    parser.add_argument("--port", type=int, default=8765, help="porta TCP (padrao 8765)")
    parser.add_argument(
        "--discovery-port", type=int, default=8766,
        help="porta UDP da descoberta (padrao 8766)",
    )
    parser.add_argument("--no-gpu", action="store_true", help="forcar captura GDI")
    parser.add_argument("--version", action="store_true", help="mostra a versao e sai")
    return parser.parse_args(argv)


def _prepare_streams() -> None:
    """Sem console (pythonw/.exe) sys.stdout e sys.stderr sao None."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _app_user_model_id() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Poltergeist")
    except Exception:  # noqa: BLE001
        pass


def main(argv=None) -> int:
    args = _parse_args(argv)
    if args.version:
        print(f"Poltergeist {srv.VERSION}")
        return 0
    if sys.platform != "win32":
        print("O Poltergeist Desktop usa APIs do Windows. Rode no Windows.")
        return 1

    _prepare_streams()
    escala = platform_win.enable_dpi_awareness()
    T.set_scale(escala)
    _app_user_model_id()

    data = platform_win.data_dir()
    srv.set_data_dir(data)
    srv._silence_comtypes_shutdown()  # noqa: SLF001 - mesmo pacote

    log_queue: "queue.Queue[str]" = queue.Queue()
    logbus.setup(data / "server.log", log_queue.put)

    aviso_migracao = platform_win.migracao_concluida()
    if aviso_migracao:
        logging.getLogger("poltergeist").warning(aviso_migracao)

    if not platform_win.acquire_single_instance():
        platform_win.focus_existing()
        return 0

    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", escala * 96.0 / 72.0)
    except tk.TclError:
        pass

    host = ServerHost(
        data,
        port=args.port,
        discovery_port=args.discovery_port,
        no_gpu=args.no_gpu,
    )
    MainWindow(root, host, log_queue)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
