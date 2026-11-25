# Poltergeist

**English** · [Português](README.md)

[![License: AGPL v3+](https://img.shields.io/badge/license-AGPL--3.0--or--later-7E1836.svg)](LICENSE)
[![Server: Python 3.10+](https://img.shields.io/badge/server-Python%203.10%2B-3776AB.svg)](#requirements)
[![Client: Android 10+](https://img.shields.io/badge/client-Android%2010%2B-3DDC84.svg)](#requirements)
[![Platform: Windows 10/11](https://img.shields.io/badge/server-Windows%2010%2F11-0078D4.svg)](#requirements)

Remote control of a Windows PC from an Android phone — **no cloud, no account, no
internet required**. A Python server on the PC captures the screen and streams it
over TCP/TLS; a native Android app renders the video and turns touches and keys
into real mouse and keyboard input.

Works over **Wi-Fi** (same network) or **USB** (faster and more stable, using
`adb reverse`). For access from anywhere, the recommended path is
[Tailscale](https://tailscale.com/), which creates a private WireGuard VPN
between the devices.

```
 phone (APK)                         PC (server.py)
 ┌────────────────┐   TCP 8765      ┌──────────────────────┐
 │ video + touch  │ ──────────────▶ │ events → SendInput   │
 │ RemoteView     │ ◀────────────── │ JPEG ← screen capture│
 └────────────────┘                 └──────────────────────┘
        ▲                                     ▲
        └──────── UDP 8766 (discovery) ───────┘
```

## Windows app (Poltergeist.exe)

The recommended way to run it on the PC is the **Poltergeist.exe** desktop app: a
single dark window (black + wine) with the server switch, pairing QR, PIN, paired
devices and live sessions — no `.bat` files and no console.

1. Download `Poltergeist.exe` from
   [Releases](https://github.com/Gabriewg/Poltergeist/releases).
2. Verify the SHA-256 (the release also ships `Poltergeist.exe.sha256`):

   ```powershell
   Get-FileHash .\Poltergeist.exe -Algorithm SHA256
   ```

3. Double-click it. On first run the window asks for a PIN and creates the TLS
   certificate; the server starts enabled.

Closing the window minimizes it to the tray; use **Sair (Quit)** in the tray menu
or the window footer to stop the server.

### Where the data lives

The executable bundles **no secrets**. PIN, certificate, devices and logs are
created in `%LOCALAPPDATA%\Poltergeist` on first run. Set `POLTERGEIST_DATA_DIR`
to use another folder (portable mode or tests).

If you already used the old name (**PocketDesk**), nothing is lost: on first run
the app copies `%LOCALAPPDATA%\PocketDesk` into the new folder (PIN, certificate
and paired devices included) and logs it. The old folder is kept as a backup;
delete it once you are sure. `POCKETDESK_DATA_DIR` is still accepted too.

Old QR links (`localcontrol://...`) and the previous APK keep working: the app
accepts both schemes and the server still answers the old UDP discovery magic.
Only the new link, `poltergeist://`, is generated from now on.

## What this project demonstrates

This is a self-contained, end-to-end systems project: two codebases, a custom
wire protocol, applied cryptography, Windows internals and a custom Android
rendering/gesture layer. No remote-desktop framework (VNC, RDP, WebRTC) is used.

| Area | What was built |
|---|---|
| **Windows internals (Python/ctypes)** | `SendInput` injection with absolute/relative mouse and Unicode keys; DXGI Desktop Duplication capture via `dxcam`; GDI fallback via `mss`; DPI awareness; `OpenInputDesktop` + token-elevation checks to detect secure desktop and UIPI-protected windows |
| **Concurrent networking** | `asyncio` TCP server, per-client streaming tasks, explicit backpressure (frame dropping instead of latency growth), keepalive and PING/PONG latency measurement |
| **Applied cryptography** | TLS 1.3 with ECDSA P-256, SPKI pinning, PBKDF2-HMAC-SHA256 PIN storage, HMAC challenge-response (the PIN never travels), single-use QR pairing tokens, per-device 32-byte credentials, constant-time comparison |
| **Protocol design** | Length-prefixed binary framing with a type byte, JSON control messages, binary video payloads, strict 64 KB inbound limit, 5 s handshake timeout, forward-compatible optional fields |
| **Android / Kotlin** | Custom `View` for video rendering and gestures (pinch zoom, pan, absolute/touchpad modes), `SSLSocket` with a custom `X509TrustManager` that pins the SPKI, hand-written PBKDF2 for API 24 compatibility, QR scanning with ZXing |
| **Reliability** | Automatic GPU→GDI fallback and DXGI re-creation, connection survival through UAC/lock/login, hysteresis-based state detection, graceful degradation on capture failure |
| **Testing** | 18 automated pairing tests, an integration suite (TLS, replay, oversized frames, handshake timeout, persistent IP blocking, no-TLS policy) and a headless client that exercises the full pipeline without a phone |

## Features

- **Desktop app (`Poltergeist.exe`)**: server switch, pairing QR, PIN, paired
  devices and live sessions in one dark window.
- JPEG screen streaming with quality, resolution and FPS adjustable in real time.
- **DXGI Desktop Duplication** capture (GPU, ~8 ms/frame) with automatic fallback
  to **GDI** (`mss`, ~33 ms).
- Mouse (absolute and touchpad), keyboard, scrolling, right click, drag and zoom.
- **Multi-monitor** support.
- **Automatic discovery** of the PC on the local network (UDP broadcast).
- **QR pairing** with a single-use token (2–5 min): the app scans the QR, pins the
  PC's public key and receives a device credential — no PIN typing, no manual
  fingerprint comparison.
- **Per-device credential** (`devices.json`): later connections skip the PIN, and
  each device can be revoked on the PC.
- **TLS 1.3** with an ECDSA P-256 certificate and public-key pinning in the app.
- **Challenge-response PIN**: the PIN never crosses the wire; the app signs a
  nonce with HMAC-SHA256 and the server stores only the derived key (PBKDF2).
- **Active-connection warning on the PC**: tray icon turns red, a notification
  appears and the log records `>>> CONEXAO ATIVA` when someone connects.
- **Protected-screen warning**: detects UAC, lock screen, login screen and
  elevated windows and shows a banner in the app without dropping the session.
- **Rate limiting** per IP and globally, with progressive delay and blocking that
  survives restarts.
- Flow control: on a slow network the server **drops frames** instead of
  accumulating latency.
- The app is almost dependency-free: ZXing (plus `androidx.core`) only for QR
  scanning; everything else uses Android APIs.

## Design decisions and trade-offs

- **Custom protocol instead of VNC/RDP.** The goal was to learn and control the
  whole pipeline: capture, encode, transport, input injection. A ~10-message
  protocol keeps the server small and the latency predictable.
- **JPEG over TCP, not H.264 over UDP.** JPEG is stateless and cheap to encode;
  TCP gives ordering and reliability on LAN/USB without a jitter buffer. The cost
  is bandwidth, which is acceptable at 30 fps / 1280 px. H.264 is on the roadmap.
- **Frame dropping under backpressure.** Reading the transport buffer size lets
  the server skip frames when the client cannot keep up, keeping latency flat
  instead of growing a queue.
- **Pin the SPKI, not the certificate.** Renewing the certificate with the same
  `key.pem` does not require re-pairing, while a real key change still triggers a
  visible MITM warning and blocks the connection.
- **Challenge-response instead of sending the PIN.** Even inside TLS, the PIN is
  never transmitted. The server stores a PBKDF2 hash, so a leaked `pin.txt` does
  not reveal the PIN.
- **Fail visible, never silent.** UAC/lock/elevated-window states are detected and
  surfaced as a non-fatal banner, so the user knows the session is alive but
  Windows is blocking input.

## Repository layout

```
.
├── server/                     # Python server (Windows)
│   ├── app.py                  # desktop window (Poltergeist.exe)
│   ├── desktop/                # theme, widgets, host, tray and dialogs
│   ├── server.py               # TCP/TLS, capture, protocol, discovery, pairing
│   ├── security.py             # PIN (PBKDF2), HMAC challenge, tokens, devices, TLS
│   ├── tray.py                 # console-mode system tray icon
│   ├── wininput.py             # mouse/keyboard injection via SendInput
│   ├── iniciar.bat             # opens the window (--console for the old mode)
│   ├── definir-pin.bat         # sets/changes the PIN in the terminal (console mode)
│   ├── autostart.bat           # background execution (used by the .vbs)
│   ├── iniciar-oculto.vbs      # starts the server without a window (legacy)
│   ├── instalar-autostart.bat  # shortcut in the Windows Startup folder (legacy)
│   ├── liberar-firewall.ps1    # opens ports 8765/TCP and 8766/UDP
│   ├── build-exe.bat           # builds dist/Poltergeist.exe + SHA-256
│   ├── Poltergeist.spec         # PyInstaller recipe
│   ├── gerar_icone_exe.py      # builds .ico and brand.png from icon.jpg
│   ├── test_client.py          # headless test client (no phone needed)
│   ├── test_pair.py            # QR pairing and device-credential tests
│   ├── bench*.py               # capture/encoding benchmarks
│   └── requirements.txt
├── android/                    # Android app (Kotlin)
│   ├── app/src/main/java/io/github/gabriewg/poltergeist/
│   │   ├── MainActivity.kt     # UI, profiles, pairing/MITM handling
│   │   ├── RemoteClient.kt     # TLS, handshake, video receiving
│   │   ├── Pairing.kt          # poltergeist:// link and token parser
│   │   ├── LocalCrypto.kt      # PBKDF2, HMAC, SPKI fingerprint
│   │   ├── PinningTrustManager.kt # trusts only the paired public key
│   │   ├── RemoteView.kt       # video drawing and gestures
│   │   └── Discovery.kt        # UDP server discovery
│   ├── gerar_icone.py          # generates icons from icon.jpg
│   ├── build-apk.bat           # builds the debug APK
│   ├── instalar-apk.bat        # installs on the phone via adb
│   └── gradlew(.bat)           # Gradle Wrapper (pinned version)
├── .github/dependabot.yml      # automated pip and Gradle updates
├── .github/workflows/build-exe.yml # builds Poltergeist.exe and the SHA-256
├── icon.jpg                    # source image for the app icon
├── conectar-usb.bat            # sets up the USB tunnel (adb reverse)
├── SECURITY.md                 # threat model and reporting channel
├── CONTRIBUTING.md
├── CHANGELOG.md
└── LICENSE
```

## Requirements

| Part | Requirements |
|---|---|
| Server | Windows 10/11. `Poltergeist.exe` bundles everything; to run from Python, 3.10+ (dependencies are installed by `iniciar.bat`) |
| App | **Android 10+** (API 29) for TLS 1.3; the APK installs on 7.0+, but TLS connections require 10+ |
| Building the app | JDK 17 and Android SDK (API 34); Gradle 8.7 is downloaded by the wrapper |

## Quick start

### 1. Run the server on the PC

The recommended path is **`Poltergeist.exe`** (see
[Windows app](#windows-app-poltergeistexe)): the window starts the server, shows
the QR, creates the PIN on first run and warns you when someone connects.

For development, double-click **`server/iniciar.bat`** (opens the same window) or
use `iniciar.bat --console` for the old terminal mode. Manually:

```powershell
cd server
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\pythonw.exe app.py                # desktop window
.venv\Scripts\python.exe server.py --set-pin    # PIN in the terminal (console mode)
.venv\Scripts\python.exe server.py              # console server
```

In console mode `--set-pin` asks for the PIN twice (it never goes into shell
history). The server prints its version, IP addresses, the public-key
fingerprint and the pairing QR:

```
[2026-01-01 12:00:00] versao 1.6
[2026-01-01 12:00:00] TLS 1.3 ativo (certificado ECDSA P-256).
[2026-01-01 12:00:00] impressao digital da chave publica (confira no app):
[2026-01-01 12:00:00]   nkIw NS/a dvHD L5Fg ipLe G0/t /KuQ B7Lm 7bgt TohR vYc=
[2026-01-01 12:00:00] ouvindo em 192.168.0.10:8765
[2026-01-01 12:00:00] pronto. Abra o app no celular e conecte.
```

The fingerprint is that of the **public key (SPKI)**, not the whole certificate.
If you renew the certificate while keeping `key.pem`, the app does not need to
re-pair.

#### Options

The desktop window accepts `--port`, `--discovery-port` and `--no-gpu`; everything
else (PIN, devices, QR, autostart) is done in the window. `server.py` keeps the
console options:

| Option | Default | Description |
|---|---|---|
| `--port` | `8765` | TCP port |
| `--discovery-port` | `8766` | UDP discovery port |
| `--bind` | `0.0.0.0` | Listen interface |
| `--monitor` | `1` | Initial monitor (1 = primary) |
| `--set-pin` | — | Sets/changes the PIN and exits |
| `--no-tls` | — | Disables TLS (**diagnostics only**; requires an 8+ character PIN) |
| `--cert` / `--key` | `cert.pem` / `key.pem` | Alternative certificate/key pair |
| `--width` | `1600` | Initial video width |
| `--quality` | `70` | Initial JPEG quality |
| `--fps` | `30` | Initial FPS |
| `--no-gpu` | — | Forces GDI (`mss`) capture instead of DXGI |
| `--pair-ttl` | `180` | QR validity in seconds (30–600) |
| `--no-qr` | — | Does not show the QR at startup (press `q` in the console) |
| `--qr-open` | — | Opens `pair.png` in the image viewer at startup |
| `--no-tray` | — | No tray icon (warnings only in the console) |
| `--forget-devices` | — | Revokes all paired devices and exits |

#### Local files (all git-ignored)

With `Poltergeist.exe` these files live in `%LOCALAPPDATA%\Poltergeist`; when run
from Python they stay in `server/`:

| File | Contents |
|---|---|
| `pin.txt` | salt + derived PIN key (PBKDF2-HMAC-SHA256, 210k iterations). **Does not contain the PIN.** |
| `cert.pem` | self-signed ECDSA P-256 certificate, 5-year validity |
| `key.pem` | private key (permissions restricted to your account) |
| `auth_state.json` | PIN attempts/blocks (persist across restarts) |
| `devices.json` | paired-device credentials (ID + 32-byte key) |
| `pair.png` | last pairing QR from console mode (delete it after use) |
| `server.log` | rotating log with date/time and IP of every failure |

PIN policy: **with TLS** (default) the minimum is 4 characters; **without TLS**
(`--no-tls`) it is **8 characters**, and the server refuses to start otherwise.

### 2. Build the Android app

```powershell
cd android
.\build-apk.bat
```

Output: `android/app/build/outputs/apk/debug/app-debug.apk`.

```powershell
adb install -r android\app\build\outputs\apk\debug\app-debug.apk
```

You can also open `android/` in Android Studio and use **Build → Build APK(s)**.

### 3. Connect

**QR pairing (recommended).** With the server running, the QR appears in the
console and is saved as `server/pair.png` (the tray menu can regenerate it). In
the app, tap **Pair with QR Code** and point the camera — or paste the link. The
app verifies the PC's public key, proves the token and receives a device
credential; from then on it connects without a PIN.

The QR is valid for **180 seconds** (adjustable with `--pair-ttl`, 30–600) and can
be used **once**. The link format is:

```
poltergeist://192.168.0.10:8765?v=1&fp=<SPKI base64url>&t=<token>&n=<PC>
```

**USB.** Enable USB debugging, connect the cable, run `conectar-usb.bat` on the
PC (`adb reverse tcp:8765 tcp:8765`) and connect to `127.0.0.1:8765` in the app.

**Wi-Fi.** Same network; tap **Scan network** (UDP discovery) or type the IP shown
by the server.

**From anywhere.** Use Tailscale on both devices and the PC's `100.x.y.z` address
with the **Away** profile. Never expose port 8765 on the router.

## Wire protocol

Every message in both directions:

```
[4 bytes: big-endian length][1 byte: type][payload]
```

| Type | Direction | Payload |
|---|---|---|
| `0x01` VIDEO | server → app | `[2 bytes cursorX][2 bytes cursorY][JPEG]` |
| `0x02` SCREEN | server → app | JSON `{name, version, w, h, monitor, monitors, tls}` |
| `0x03` CURSOR | server → app | `[2 bytes cursorX][2 bytes cursorY]` (cursor only) |
| `0x10` HELLO | app → server | JSON `{v:3, name, width, quality, fps, mac}` + `pid` (QR) or `device` |
| `0x11` INPUT | app → server | Event JSON |
| `0x12` INFO | server → app | JSON `{warn?, on?, error?}` (non-fatal warning or fatal error) |
| `0x13/0x14` PING/PONG | both | JSON `{ts}` (latency) |
| `0x15` CHALLENGE | server → app | JSON `{v, kdf, iter, salt, nonce, auth}` |
| `0x16` PAIR_OK | server → app | JSON `{v, id, key, name}` (device credential, pairing only) |

`INFO` with `{"warn":"secure_desktop","on":true}` (UAC/lock/login) or
`{"warn":"admin_window","on":true}` (elevated window) is **non-fatal**: the app
shows a banner, keeps gestures and the session, and hides the banner on
`{"warn":"","on":false}`. Warnings are sent only on state changes; older servers
omit the field and older apps ignore it. `error` remains fatal.

### Handshake

1. The app opens **TLS 1.3** and compares the server's public key (SPKI) with the
   one stored during pairing.
2. The server sends `CHALLENGE` with a **fresh 32-byte nonce**.
3. The app replies `HELLO` in one of three modes:
   - **PIN**: `mac = HMAC-SHA256(PBKDF2(pin, salt, 210000, 32), nonce)`;
   - **QR**: `pid = SHA-256(token)[:32]` and `mac = HMAC-SHA256(token, nonce)`;
   - **device**: `device = <id>` and `mac = HMAC-SHA256(device_key, nonce)`.
4. The server compares with `hmac.compare_digest`. The PIN **never leaves the
   phone**, and the MAC cannot be replayed because the nonce changes per
   connection.
5. In QR mode the server consumes the token atomically, creates the device
   credential and returns it in `PAIR_OK`. The app stores it only after the PC has
   proven it owns the QR key.

Input events:

```json
{"t":"m","x":0.5,"y":0.5}           // absolute cursor (0..1)
{"t":"mr","dx":12,"dy":-3}          // relative cursor (pixels)
{"t":"b","btn":"left","down":true}  // button press/release
{"t":"c","btn":"left","count":1}    // click
{"t":"s","dy":-120,"dx":0}          // scroll
{"t":"k","key":"c","mods":["ctrl"]} // key + modifiers
{"t":"kt","text":"hello world"}     // typed text
{"t":"r","width":1600,"quality":72,"fps":30}
{"t":"mon","i":2}
```

The cursor is drawn by the app (Windows does not capture it in the frame), so its
position travels with every frame — and in a tiny `0x03` packet when the screen
did not change, keeping the cursor smooth while idle.

## Security design

- **Encrypted transport.** Self-signed ECDSA P-256 certificate generated on first
  run, valid for 5 years, with `minimum_version = TLSv1_3` and a 5 s handshake
  timeout.
- **PIN never travels.** Per-connection nonce + HMAC; `pin.txt` stores only the
  KDF output (salt + derived key).
- **Single-use QR.** 32-byte token, 180 s TTL, memory-only, consumed on first use;
  only its hash and an HMAC are sent.
- **Per-device credentials.** 32-byte keys stored in `devices.json` (atomic
  writes, restricted ACL) and in the app's preferences; revocable at any time.
- **No silent MITM.** A changed PC key shows both fingerprints, blocks the
  connection and only allows re-pairing through explicit user action.
- **Brute-force protection.** Progressive delay `2^(n-1)` capped at 15 s, per-IP
  and global blocks (persistent across restarts), every failure logged with date
  and IP.
- **Strict parsing.** Inbound messages are capped at 64 KB *before* reading the
  body; the `HELLO` must arrive within 5 s.
- **Least surprise.** Active-connection tray warning, rotating logs, and secrets
  excluded from Git (`key.pem`, `pin.txt`, `devices.json`, `pair.png`,
  `auth_state.json`, `*.log`).

The full threat model — what the project protects, what it does **not** protect
and what is out of scope — is in [SECURITY.md](SECURITY.md). To report a
vulnerability, use the
[private Security Advisory](https://github.com/Gabriewg/Poltergeist/security/advisories/new);
please do not open a public issue.

> The server grants **full control** of the PC to anyone who authenticates. Run it
> as a standard user and never expose port 8765 to the internet. `--no-tls` exists
> for diagnostics only.

## Testing and validation

Everything below runs without a phone:

```powershell
cd server
.venv\Scripts\python.exe test_pair.py                      # 18 pairing tests
.venv\Scripts\python.exe test_client.py 127.0.0.1 8765 40 SEU_PIN
.venv\Scripts\python.exe test_client.py 127.0.0.1 8765 0 "" --show-fingerprint
```

The headless client performs the same handshake as the app (TLS 1.3 +
challenge/HMAC), saves `frame.jpg` and moves the PC cursor to the center — if the
cursor moves, the whole chain (capture → network → injection) works.

Verified scenarios:

- correct PIN connects; wrong PIN, MAC replay and a 4 GB length header are
  rejected;
- a stalled `HELLO` is dropped after 5 s;
- the IP block persists across restarts;
- `--no-tls` rejects short PINs and accepts 8+ characters;
- QR pairs once; expired/reused tokens are rejected; a wrong MAC does not consume
  the token; the device credential reconnects without a PIN;
- protected-screen banner appears and disappears on the real device;
- DXGI failure falls back to GDI and recovers without dropping the session.

## Known limitations

The server runs as a regular program inside the user session. Windows isolates
certain screens and windows, and an unelevated process cannot capture or control
them:

- **UAC, lock screen, login screen and Ctrl+Alt+Del** run on the secure desktop
  (`Winlogon`). The image is black or frozen and the app shows *"Tela protegida
  pelo Windows…"*. The banner clears automatically when you return to the normal
  desktop.
- **Programs running as administrator** are visible, but Windows ignores input
  from a non-elevated process (UIPI). The app shows a warning; controlling that
  window would require an elevated server, which greatly increases risk.
- **Ctrl+Alt+Del** cannot be sent by software.
- **Fully black screens for other reasons** (DRM/content protection, monitor off,
  video driver) may also trigger the banner. It is only a warning: the session
  stays alive and video returns when the screen does.

The complete fix (see Roadmap) is a Windows service running as `SYSTEM` that
switches desktops to see UAC/login and injects input into elevated windows — the
same approach used by mainstream remote-access tools.

## Roadmap

- [ ] H.264/MediaCodec video (less bandwidth, more FPS)
- [ ] PC audio → phone
- [ ] File transfer (drag and drop)
- [ ] Custom shortcuts and macros
- [x] TLS 1.3 with local certificate and public-key pinning
- [x] Challenge-response PIN + persistent rate limiting
- [x] QR pairing with single-use token and per-device credential
- [ ] Server packaged as a `.exe` (PyInstaller), no Python required
- [ ] Connect without typing an IP (last-address fallback, MagicDNS, LAN)
- [ ] Windows service (`SYSTEM`) with desktop switching for UAC/login and input
      into elevated windows (`WTSGetActiveConsoleSessionId`, `CreateProcessAsUser`,
      `OpenInputDesktop`, `SetThreadDesktop`)

## Contributing

Contributions are welcome! Read [CONTRIBUTING.md](CONTRIBUTING.md) (in Portuguese)
for how to open issues, propose changes and send pull requests.

## License

Distributed under the **GNU Affero General Public License v3.0 or later**
(`AGPL-3.0-or-later`) — see [LICENSE](LICENSE).

The AGPL requires that anyone offering Poltergeist as a network service also makes
the corresponding source code available. Every `.py` and `.kt` file carries the
`SPDX-License-Identifier: AGPL-3.0-or-later` header.

The app icon is generated from `icon.jpg`; if you redistribute the project under
another visual identity, replace that image with your own assets.
