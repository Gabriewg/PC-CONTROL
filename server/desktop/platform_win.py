# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integracao com o Windows: DPI, titulo escuro, autostart, firewall e adb."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183

_mutex_handle = None


# ------------------------------------------------------------------ caminhos


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Pasta do .exe (ou da pasta server/ rodando pelo Python)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Pasta de recursos empacotados (icone) ou a raiz do repositorio."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return app_dir().parent


def brand_image_path() -> Path | None:
    """Imagem da marca: brand.png (build) ou o icon.jpg do repositorio."""
    for nome in ("brand.png", "icon.jpg"):
        caminho = resource_dir() / nome
        if caminho.exists():
            return caminho
    return None


NOME_PASTA = "Poltergeist"
# Nome usado ate' a versao 1.6. Os dados (PIN, certificado, aparelhos) sao
# copiados de la' na primeira execucao com o nome novo; a pasta antiga fica
# intacta, como copia de seguranca.
NOME_PASTA_ANTIGA = "PocketDesk"
MIGRACAO: dict[str, object] = {"origem": None, "arquivos": 0, "falhas": []}


def data_dir() -> Path:
    """Onde ficam PIN, certificado, aparelhos e logs.

    No .exe os dados vao para %LOCALAPPDATA%\\Poltergeist, fora da pasta do
    programa (que pode estar em local somente leitura e e' recriada a cada
    atualizacao). Rodando pelo Python, continua ao lado do server.py.
    """
    override = (
        os.environ.get("POLTERGEIST_DATA_DIR")
        or os.environ.get("POCKETDESK_DATA_DIR")  # nome antigo, ainda aceito
    )
    if override:
        pasta = Path(override).expanduser()
        pasta.mkdir(parents=True, exist_ok=True)
        return pasta

    if not is_frozen():
        return app_dir()

    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    destino = Path(local) / NOME_PASTA
    legado = Path(local) / NOME_PASTA_ANTIGA
    if not destino.exists() and legado.is_dir():
        _copiar_pasta(legado, destino)
    destino.mkdir(parents=True, exist_ok=True)
    _migrar(destino)
    return destino


def _copiar_pasta(origem: Path, destino: Path) -> None:
    """Copia a pasta de dados antiga inteira, sem apagar a original.

    Nunca sobrescreve nada e nunca remove o que estava la': se algum arquivo
    nao puder ser copiado, o nome vai para MIGRACAO["falhas"] e a janela avisa.
    """
    destino.mkdir(parents=True, exist_ok=True)
    copiados = 0
    falhas: list[str] = []
    for item in origem.rglob("*"):
        if not item.is_file():
            continue
        alvo = destino / item.relative_to(origem)
        if alvo.exists():
            continue
        try:
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(item.read_bytes())
            copiados += 1
        except OSError as exc:
            falhas.append(f"{item.name}: {exc}")
    MIGRACAO.update(origem=str(origem), arquivos=copiados, falhas=falhas)


def migracao_concluida() -> str | None:
    """Mensagem para o log quando os dados vieram da pasta antiga."""
    origem = MIGRACAO.get("origem")
    if not origem:
        return None
    copiados = int(MIGRACAO.get("arquivos") or 0)
    falhas = list(MIGRACAO.get("falhas") or [])
    texto = (
        f"dados migrados de {origem} ({copiados} arquivo(s) copiado(s)); "
        f"a pasta antiga foi mantida"
    )
    if falhas:
        texto += f"; falhou: {', '.join(falhas)}"
    return texto


def _migrar(destino: Path) -> None:
    """Traz os dados de uma instalacao portatil antiga, se existirem."""
    origem = app_dir()
    for nome in ("pin.txt", "devices.json", "cert.pem", "key.pem", "auth_state.json"):
        antigo = origem / nome
        novo = destino / nome
        if antigo.exists() and not novo.exists():
            try:
                novo.write_bytes(antigo.read_bytes())
            except OSError:
                pass


# ------------------------------------------------------------------ janela


def enable_dpi_awareness() -> float:
    """DPI awareness por monitor; devolve o fator do monitor principal."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE_V2
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass
    try:
        dpi = int(ctypes.windll.user32.GetDpiForSystem())
    except Exception:  # noqa: BLE001
        try:
            dpi = int(ctypes.windll.user32.GetDeviceCaps(
                ctypes.windll.user32.GetDC(0), 88  # LOGPIXELSX
            ))
        except Exception:  # noqa: BLE001
            dpi = 96
    return max(0.75, min(3.0, dpi / 96.0))


def apply_dark_titlebar(root) -> None:
    """Barra de titulo escura (e vinho no Windows 11)."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        dwm = ctypes.windll.dwmapi

        def colorref(hexcolor: str) -> int:
            r = int(hexcolor[1:3], 16)
            g = int(hexcolor[3:5], 16)
            b = int(hexcolor[5:7], 16)
            return r | (g << 8) | (b << 16)

        def set_attr(attr: int, value: int) -> None:
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

        set_attr(20, 1)                     # DWMWA_USE_IMMERSIVE_DARK_MODE
        set_attr(35, colorref("#150D11"))   # DWMWA_CAPTION_COLOR (Win11)
        set_attr(36, colorref("#F4EDEA"))   # DWMWA_TEXT_COLOR
        set_attr(34, colorref("#2A1A21"))   # DWMWA_BORDER_COLOR
    except Exception:  # noqa: BLE001
        pass


def set_window_icon(root) -> None:
    """Icone da janela/barra de tarefas a partir do icon.jpg do projeto."""
    try:
        from PIL import Image, ImageTk

        caminho = brand_image_path()
        if caminho is None:
            return
        img = Image.open(caminho).convert("RGBA")
        img.thumbnail((64, 64), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        root.iconphoto(True, photo)
        root._pd_icon = photo  # mantem a referencia viva
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ instancia unica


def acquire_single_instance(name: str = "Poltergeist.GUI.Mutex") -> bool:
    """False quando o Poltergeist ja esta aberto."""
    global _mutex_handle
    try:
        kernel32 = ctypes.windll.kernel32
        _mutex_handle = kernel32.CreateMutexW(None, False, name)
        return kernel32.GetLastError() != ERROR_ALREADY_EXISTS
    except Exception:  # noqa: BLE001
        return True


def focus_existing(title: str = "Poltergeist") -> bool:
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ autostart


def autostart_path() -> Path:
    return _startup_dir() / f"{NOME_PASTA}.lnk"


def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def _remove_legacy_autostart() -> None:
    """Apaga o atalho com o nome antigo (senao o PC abriria dois apps)."""
    try:
        (_startup_dir() / f"{NOME_PASTA_ANTIGA}.lnk").unlink(missing_ok=True)
    except OSError:
        pass


def autostart_enabled() -> bool:
    return autostart_path().exists()


def _launch_target() -> tuple[str, str, str]:
    """(executavel, argumentos, diretorio) para o atalho de inicializacao."""
    if is_frozen():
        exe = str(Path(sys.executable).resolve())
        return exe, "", str(app_dir())
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    alvo = pythonw if pythonw.exists() else Path(sys.executable)
    app = Path(__file__).resolve().parent.parent / "app.py"
    return str(alvo), f'"{app}"', str(app.parent)


def set_autostart(enabled: bool) -> tuple[bool, str]:
    caminho = autostart_path()
    if not enabled:
        try:
            caminho.unlink(missing_ok=True)
            _remove_legacy_autostart()
            return True, ""
        except OSError as exc:
            return False, str(exc)

    _remove_legacy_autostart()
    alvo, argumentos, pasta = _launch_target()
    icon = alvo

    def esc(value: str) -> str:
        return value.replace("'", "''")

    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
        "$s.TargetPath='{alvo}';$s.Arguments='{args}';"
        "$s.WorkingDirectory='{pasta}';$s.IconLocation='{icon}';$s.Save()"
    ).format(
        lnk=esc(str(caminho)), alvo=esc(alvo), args=esc(argumentos),
        pasta=esc(pasta), icon=esc(icon),
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=25,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if proc.returncode != 0 or not caminho.exists():
        return False, (proc.stderr or "nao foi possivel criar o atalho").strip()
    return True, ""


# ------------------------------------------------------------------ firewall


def firewall_enabled(port: int = 8765) -> bool:
    try:
        proc = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             f"name=Poltergeist TCP {port}"],
            capture_output=True, text=True, timeout=8,
            creationflags=CREATE_NO_WINDOW,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def open_firewall(port: int = 8765, discovery_port: int = 8766) -> tuple[bool, str]:
    """Cria as regras de entrada com elevacao (UAC)."""
    regras = [
        # remove as regras antigas (nome anterior) para nao deixar buraco aberto
        f'netsh advfirewall firewall delete rule name="{NOME_PASTA_ANTIGA} TCP {port}"',
        f'netsh advfirewall firewall delete rule name="{NOME_PASTA_ANTIGA} UDP {discovery_port}"',
        f'netsh advfirewall firewall delete rule name="Poltergeist TCP {port}"',
        f'netsh advfirewall firewall delete rule name="Poltergeist UDP {discovery_port}"',
        'netsh advfirewall firewall add rule '
        f'name="Poltergeist TCP {port}" dir=in action=allow protocol=TCP '
        f'localport={port} profile=private,domain',
        'netsh advfirewall firewall add rule '
        f'name="Poltergeist UDP {discovery_port}" dir=in action=allow protocol=UDP '
        f'localport={discovery_port} profile=private,domain',
    ]
    script = " & ".join(regras)
    try:
        rc = int(ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "cmd.exe", f'/c {script}', None, 0
        ))
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    if rc <= 32:
        # 5 = acesso negado (UAC cancelado)
        return False, "elevacao cancelada" if rc == 5 else f"codigo {rc}"
    return True, ""


# ------------------------------------------------------------------ USB (adb)


def adb_available() -> bool:
    return shutil.which("adb") is not None


def adb_run(args: list[str], timeout: int = 12) -> tuple[bool, str]:
    if not adb_available():
        return False, "adb nao encontrado no PATH"
    try:
        proc = subprocess.run(
            ["adb", *args], capture_output=True, text=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    saida = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, saida.strip()


def adb_reverse(port: int = 8765) -> tuple[bool, str]:
    return adb_run(["reverse", f"tcp:{port}", f"tcp:{port}"])


def adb_devices() -> tuple[bool, str]:
    return adb_run(["devices", "-l"])


# ------------------------------------------------------------------ diversos


def open_path(path: str | Path) -> None:
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except OSError:
        pass


def hostname() -> str:
    return os.environ.get("COMPUTERNAME") or "este PC"
