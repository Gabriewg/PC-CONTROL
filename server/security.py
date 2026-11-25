"""Autenticacao, limite de tentativas e TLS do servidor Local Control.

O PIN nunca trafega pela rede:

1. o servidor envia um nonce aleatorio de 32 bytes;
2. o app deriva a chave do PIN com PBKDF2-HMAC-SHA256 (salt + iteracoes) e
   responde com HMAC-SHA256(chave, nonce);
3. o servidor confere com hmac.compare_digest.

O arquivo pin.txt guarda apenas o resultado da KDF (salt + chave derivada),
nunca o PIN puro.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

PIN_VERSION = 1
KDF_NAME = "pbkdf2-sha256"
KDF_ITERATIONS = 210_000
SALT_BYTES = 16
NONCE_BYTES = 32
KEY_BYTES = 32
MIN_PIN_TLS = 4
MIN_PIN_PLAIN = 8
MAX_PIN = 128
MIN_ITERATIONS = 10_000
MAX_ITERATIONS = 2_000_000


class PinFileError(RuntimeError):
    """pin.txt ausente, corrompido ou em formato desconhecido."""


def b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(str(text).encode("ascii"), validate=True)


def format_fingerprint(fingerprint: str) -> str:
    """Agrupa a impressao digital em blocos de 4 para facilitar a comparacao."""
    limpo = fingerprint.replace(" ", "")
    return " ".join(limpo[i : i + 4] for i in range(0, len(limpo), 4))


# ------------------------------------------------------------------ PIN / KDF


@dataclass(frozen=True)
class PinRecord:
    salt: bytes
    key: bytes
    iterations: int
    requires_tls: bool
    created: int = 0


def derive_key(pin: str, salt: bytes, iterations: int = KDF_ITERATIONS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations, KEY_BYTES)


def load_pin(path: Path) -> PinRecord | None:
    """Le o pin.txt. Devolve None quando o arquivo nao existe."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PinFileError(f"nao consegui ler {path}: {exc}") from exc

    if not isinstance(data, dict) or data.get("v") != PIN_VERSION:
        raise PinFileError(f"{path} em formato desconhecido (rode --set-pin de novo)")
    if data.get("kdf") != KDF_NAME:
        raise PinFileError(f"{path} usa KDF desconhecida: {data.get('kdf')!r}")

    try:
        salt = b64d(data["salt"])
        key = b64d(data["key"])
        iterations = int(data["iterations"])
    except (KeyError, ValueError, TypeError) as exc:
        raise PinFileError(f"{path} incompleto ou corrompido") from exc

    if len(salt) < 8 or len(key) != KEY_BYTES:
        raise PinFileError(f"{path} tem salt/chave com tamanho invalido")
    if not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
        raise PinFileError(f"{path} tem iteracoes fora da faixa segura: {iterations}")

    return PinRecord(
        salt=salt,
        key=key,
        iterations=iterations,
        requires_tls=bool(data.get("requires_tls", True)),
        created=int(data.get("created", 0)),
    )


def save_pin(path: Path, pin: str, tls_enabled: bool) -> PinRecord:
    """Deriva a chave do PIN e grava salt+chave em pin.txt (nunca o PIN)."""
    pin = pin.strip()
    minimo = MIN_PIN_TLS if tls_enabled else MIN_PIN_PLAIN
    if len(pin) < minimo:
        modo = "com TLS" if tls_enabled else "sem TLS (--no-tls)"
        raise ValueError(
            f"o PIN precisa ter pelo menos {minimo} caracteres {modo}. "
            + ("Sem TLS, use 8 ou mais caracteres." if not tls_enabled else "")
        )
    if len(pin) > MAX_PIN:
        raise ValueError(f"o PIN pode ter no maximo {MAX_PIN} caracteres")

    salt = secrets.token_bytes(SALT_BYTES)
    key = derive_key(pin, salt)
    data = {
        "v": PIN_VERSION,
        "kdf": KDF_NAME,
        "iterations": KDF_ITERATIONS,
        "salt": b64e(salt),
        "key": b64e(key),
        # PIN curto so e aceito com TLS + rate limit ativos
        "requires_tls": len(pin) < MIN_PIN_PLAIN,
        "created": int(time.time()),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        raise PinFileError(f"nao consegui gravar {path}: {exc}") from exc
    restrict_permissions(path)
    return load_pin(path)  # type: ignore[return-value]


# ------------------------------------------------------------------ desafio


def new_nonce() -> bytes:
    return secrets.token_bytes(NONCE_BYTES)


def challenge_json(record: PinRecord | None, nonce: bytes) -> dict:
    """Mensagem enviada ao app antes do HELLO (salt e nonce nao sao segredos)."""
    return {
        "v": 1,
        "kdf": KDF_NAME,
        "iter": record.iterations if record else KDF_ITERATIONS,
        "salt": b64e(record.salt) if record else "",
        "nonce": b64e(nonce),
        "auth": record is not None,
    }


def verify_mac(record: PinRecord, nonce: bytes, mac_b64: str) -> bool:
    try:
        recebido = b64d(mac_b64)
    except (ValueError, TypeError):
        return False
    esperado = hmac.new(record.key, nonce, hashlib.sha256).digest()
    return hmac.compare_digest(esperado, recebido)


# ------------------------------------------------------------------ pareamento

# O QR carrega um token de uso unico e curta duracao. Ele NAO e o PIN: serve
# apenas para o primeiro pareamento. Depois disso o servidor cria uma chave
# exclusiva do aparelho (device key), que o app usa nas conexoes seguintes.
PAIR_TOKEN_BYTES = 32
PAIR_TTL = 180.0
PAIR_TTL_MIN = 30.0
PAIR_TTL_MAX = 600.0
DEVICE_KEY_BYTES = 32
DEVICE_ID_BYTES = 8
DEVICES_VERSION = 1


def b64u(raw: bytes) -> str:
    """base64 URL-safe sem padding (cabe em query string sem escape)."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64u_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def token_id(token: str) -> str:
    """Identificador publico do token (nunca o token em si)."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()[:32]


def fingerprint_to_url(fingerprint_b64: str) -> str:
    return b64u(b64d(fingerprint_b64))


def fingerprint_from_url(value: str) -> str:
    return b64e(b64u_decode(value))


def pairing_uri(
    host: str, port: int, fingerprint_b64: str, token: str, name: str = ""
) -> str:
    """Monta o link do QR: localcontrol://host:porta?fp=...&t=...&n=..."""
    from urllib.parse import urlencode

    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # IPv6 literal
    query = urlencode(
        {
            "v": 1,
            "fp": fingerprint_to_url(fingerprint_b64),
            "t": token,
            "n": name,
        }
    )
    return f"localcontrol://{host}:{int(port)}?{query}"


@dataclass
class PairingToken:
    token: str
    pid: str
    created: float
    expires: float
    used: bool = False


class PairingTokens:
    """Tokens de pareamento em memoria, de uso unico e com expiracao curta.

    Nada e gravado em disco: reiniciar o servidor invalida todos os QR antigos.
    """

    def __init__(self, ttl: float = PAIR_TTL, clock=time.time) -> None:
        self.ttl = max(PAIR_TTL_MIN, min(PAIR_TTL_MAX, float(ttl)))
        self._clock = clock
        self._items: dict[str, PairingToken] = {}

    def _prune(self, now: float) -> None:
        for pid in [p for p, item in self._items.items() if item.used or item.expires <= now]:
            del self._items[pid]

    def create(self) -> PairingToken:
        now = self._clock()
        self._prune(now)
        token = secrets.token_urlsafe(PAIR_TOKEN_BYTES)
        item = PairingToken(
            token=token,
            pid=token_id(token),
            created=now,
            expires=now + self.ttl,
        )
        self._items[item.pid] = item
        return item

    def verify_and_consume(self, pid: str, nonce: bytes, mac_b64: str) -> bool:
        """Confere HMAC(token, nonce) e invalida o token na mesma operacao."""
        now = self._clock()
        self._prune(now)
        item = self._items.get(pid)
        if item is None or item.used or item.expires <= now:
            return False
        try:
            recebido = b64d(mac_b64)
        except (ValueError, TypeError):
            return False
        esperado = hmac.new(item.token.encode("ascii"), nonce, hashlib.sha256).digest()
        if not hmac.compare_digest(esperado, recebido):
            return False
        item.used = True
        del self._items[pid]
        return True

    def active_count(self) -> int:
        self._prune(self._clock())
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()


@dataclass
class DeviceRecord:
    id: str
    name: str
    key: bytes
    created: int = 0
    last_seen: int = 0


class DeviceStore:
    """Aparelhos pareados: chave exclusiva por aparelho, revogavel.

    O arquivo guarda a chave (como um arquivo de senhas) com permissao restrita
    ao usuario. Quem tiver acesso a ele ja controla o PC localmente.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: dict[str, DeviceRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("v") != DEVICES_VERSION:
                return
            for did, entry in (data.get("devices") or {}).items():
                if not isinstance(entry, dict):
                    continue
                key = b64d(entry.get("key", ""))
                if len(key) != DEVICE_KEY_BYTES:
                    continue
                self._items[str(did)] = DeviceRecord(
                    id=str(did),
                    name=str(entry.get("name", "celular"))[:32],
                    key=key,
                    created=int(entry.get("created", 0)),
                    last_seen=int(entry.get("last_seen", 0)),
                )
        except (OSError, ValueError, TypeError):
            # arquivo corrompido nao pode impedir o servidor de subir
            self._items = {}

    def _save(self) -> None:
        data = {
            "v": DEVICES_VERSION,
            "devices": {
                rec.id: {
                    "name": rec.name,
                    "key": b64e(rec.key),
                    "created": rec.created,
                    "last_seen": rec.last_seen,
                }
                for rec in self._items.values()
            },
        }
        tmp = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            restrict_permissions(self.path)
        except OSError:
            pass

    def add(self, name: str) -> DeviceRecord:
        agora = int(time.time())
        rec = DeviceRecord(
            id=secrets.token_hex(DEVICE_ID_BYTES),
            name=(name or "celular")[:32],
            key=secrets.token_bytes(DEVICE_KEY_BYTES),
            created=agora,
            last_seen=agora,
        )
        self._items[rec.id] = rec
        self._save()
        return rec

    def get(self, device_id: str) -> DeviceRecord | None:
        return self._items.get(device_id)

    def verify(self, device_id: str, nonce: bytes, mac_b64: str) -> bool:
        rec = self._items.get(device_id)
        if rec is None:
            return False
        try:
            recebido = b64d(mac_b64)
        except (ValueError, TypeError):
            return False
        esperado = hmac.new(rec.key, nonce, hashlib.sha256).digest()
        if not hmac.compare_digest(esperado, recebido):
            return False
        rec.last_seen = int(time.time())
        self._save()
        return True

    def remove(self, device_id: str) -> bool:
        if device_id not in self._items:
            return False
        del self._items[device_id]
        self._save()
        return True

    def clear(self) -> None:
        self._items.clear()
        self._save()

    def all(self) -> list[DeviceRecord]:
        return sorted(self._items.values(), key=lambda r: r.created)


# ------------------------------------------------------------------ rate limit


@dataclass
class FailureInfo:
    delay: float
    attempts: int
    blocked_for: float


class RateLimiter:
    """Bloqueio persistente por IP e global.

    O bloqueio global existe porque, no Tailscale, cada aparelho tem um IP
    diferente: um atacante interno pode girar entre pares para escapar do
    limite por IP.
    """

    def __init__(
        self,
        path: Path,
        *,
        per_ip_max: int = 5,
        per_ip_window: float = 300.0,
        per_ip_block: float = 300.0,
        global_max: int = 20,
        global_window: float = 600.0,
        global_block: float = 300.0,
        max_delay: float = 15.0,
    ) -> None:
        self.path = path
        self.per_ip_max = per_ip_max
        self.per_ip_window = per_ip_window
        self.per_ip_block = per_ip_block
        self.global_max = global_max
        self.global_window = global_window
        self.global_block = global_block
        self.max_delay = max_delay
        self._ips: dict[str, dict] = {}
        self._global: dict = {"fails": [], "blocked_until": 0.0}
        self._load()

    # -- persistencia

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            ips = data.get("ips") or {}
            glob = data.get("global") or {}
            if isinstance(ips, dict):
                self._ips = {
                    str(ip): {
                        "fails": [float(t) for t in (entry.get("fails") or [])],
                        "blocked_until": float(entry.get("blocked_until", 0)),
                    }
                    for ip, entry in ips.items()
                    if isinstance(entry, dict)
                }
            if isinstance(glob, dict):
                self._global = {
                    "fails": [float(t) for t in (glob.get("fails") or [])],
                    "blocked_until": float(glob.get("blocked_until", 0)),
                }
        except (OSError, ValueError, TypeError):
            # estado corrompido nao pode impedir o servidor de subir
            self._ips = {}
            self._global = {"fails": [], "blocked_until": 0.0}

    def _save(self) -> None:
        data = {"ips": self._ips, "global": self._global}
        tmp = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    # -- consulta

    def _prune(self, now: float) -> None:
        for ip in list(self._ips):
            entry = self._ips[ip]
            entry["fails"] = [t for t in entry["fails"] if now - t <= self.per_ip_window]
            if not entry["fails"] and entry["blocked_until"] <= now:
                del self._ips[ip]
        self._global["fails"] = [
            t for t in self._global["fails"] if now - t <= self.global_window
        ]

    def blocked_for(self, ip: str) -> float:
        now = time.time()
        self._prune(now)
        until_ip = self._ips.get(ip, {}).get("blocked_until", 0.0)
        until = max(until_ip, self._global.get("blocked_until", 0.0))
        return max(0.0, until - now)

    def attempts_for(self, ip: str) -> int:
        now = time.time()
        self._prune(now)
        return len(self._ips.get(ip, {}).get("fails", []))

    # -- atualizacao

    def failure(self, ip: str) -> FailureInfo:
        now = time.time()
        self._prune(now)

        entry = self._ips.setdefault(ip, {"fails": [], "blocked_until": 0.0})
        entry["fails"].append(now)
        self._global["fails"].append(now)

        tentativas = len(entry["fails"])
        if tentativas >= self.per_ip_max:
            entry["blocked_until"] = now + self.per_ip_block
        if len(self._global["fails"]) >= self.global_max:
            self._global["blocked_until"] = now + self.global_block

        # atraso progressivo: 1s, 2s, 4s, 8s... limitado por max_delay
        delay = min(float(2 ** max(0, tentativas - 1)), self.max_delay)
        self._save()

        bloqueado = max(
            0.0,
            entry["blocked_until"] - now,
            self._global.get("blocked_until", 0.0) - now,
        )
        return FailureInfo(delay=delay, attempts=tentativas, blocked_for=bloqueado)

    def success(self, ip: str) -> None:
        if ip in self._ips:
            del self._ips[ip]
            self._save()


# ------------------------------------------------------------------ TLS


def restrict_permissions(path: Path) -> None:
    """Deixa o arquivo legivel apenas para a conta do usuario."""
    try:
        if os.name != "nt":
            os.chmod(path, 0o600)
            return
        usuario = os.environ.get("USERNAME")
        dominio = os.environ.get("USERDOMAIN")
        if not usuario:
            return
        principal = f"{dominio}\\{usuario}" if dominio else usuario
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{principal}:(F)"],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        # sem permissao para ajustar ACL: o arquivo continua no perfil do usuario
        pass


def ensure_certificate(cert_path: Path, key_path: Path, days: int = 1825) -> bool:
    """Gera um certificado ECDSA P-256 autoassinado se ainda nao existir.

    Devolve True quando gerou um novo. O pinning do app e feito na chave
    publica (SPKI), entao renovar o certificado com a mesma chave nao exige
    re-parear.
    """
    if cert_path.exists() and key_path.exists():
        return False

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise RuntimeError(
            "a biblioteca 'cryptography' nao esta instalada. "
            "Rode: .venv\\Scripts\\python.exe -m pip install cryptography "
            "(ou use --no-tls apenas para diagnostico)"
        ) from exc

    chave = ec.generate_private_key(ec.SECP256R1())
    agora = datetime.now(timezone.utc)
    nome = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Local Control"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Local Control"),
        ]
    )

    san = [
        x509.DNSName("localcontrol"),
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    try:
        host = socket.gethostname()
        if host and host != "localhost":
            san.append(x509.DNSName(host))
    except OSError:
        pass

    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(chave, hashes.SHA256())
    )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(
        chave.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    restrict_permissions(key_path)
    return True


def spki_fingerprint(cert_path: Path) -> str:
    """SHA-256 (base64) da chave publica (SubjectPublicKeyInfo) do certificado."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    der = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return b64e(hashlib.sha256(der).digest())


def build_ssl_context(cert_path: Path, key_path: Path):
    """Contexto TLS 1.3 (minimo) para o asyncio.start_server."""
    import ssl

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(str(cert_path), str(key_path))
    return ctx
