# Local Control

Controle remoto do seu PC Windows pelo celular — **sem nuvem, sem conta e sem
internet**. O servidor roda no PC, captura a tela e envia por TCP; o app Android
mostra a imagem e transforma toques e teclas em eventos de mouse e teclado.

Funciona por **Wi-Fi** (mesma rede) e por **USB** (mais rápido e estável, usando
`adb reverse`). Para acessar de qualquer lugar, o caminho recomendado é o
[Tailscale](https://tailscale.com/), que cria uma VPN privada entre os aparelhos.

```
 celular (APK)                       notebook (server.py)
 ┌────────────────┐   TCP 8765      ┌──────────────────────┐
 │ tela + toques  │ ──────────────▶ │ eventos → SendInput  │
 │ RemoteView     │ ◀────────────── │ JPEG → tela capturada│
 └────────────────┘                 └──────────────────────┘
        ▲                                     ▲
        └──────── UDP 8766 (descoberta) ──────┘
```

## Recursos

- Vídeo da tela em JPEG com qualidade, resolução e FPS ajustáveis em tempo real.
- Captura por **DXGI Desktop Duplication** (GPU, ~8 ms/quadro) com fallback
  automático para **GDI** (`mss`, ~33 ms).
- Mouse (absoluto e touchpad), teclado, rolagem, clique direito, arrastar e zoom.
- Suporte a **múltiplos monitores**.
- **Descoberta automática** do PC na rede local (UDP broadcast).
- **PIN** opcional para autenticar a conexão.
- Controle de fluxo: em rede ruim o servidor **descarta quadros** em vez de
  acumular atraso.
- App sem dependências externas (usa apenas APIs do Android).

## Estrutura do repositório

```
.
├── server/                     # servidor Python (Windows)
│   ├── server.py               # TCP, captura, protocolo e descoberta UDP
│   ├── wininput.py             # injeção de mouse/teclado via SendInput
│   ├── iniciar.bat             # cria a venv, instala deps e roda o servidor
│   ├── autostart.bat           # execução em segundo plano (usado pelo .vbs)
│   ├── iniciar-oculto.vbs      # sobe o servidor sem janela de console
│   ├── instalar-autostart.bat  # atalho na pasta Inicializar do Windows
│   ├── liberar-firewall.ps1    # libera as portas 8765/TCP e 8766/UDP
│   ├── test_client.py          # cliente de teste (sem celular)
│   ├── bench*.py               # benchmarks de captura/codificação
│   └── requirements.txt
├── android/                    # app Android (Kotlin)
│   ├── app/src/main/java/com/localcontrol/
│   │   ├── MainActivity.kt     # interface e perfis de conexão
│   │   ├── RemoteClient.kt     # socket, handshake e recebimento do vídeo
│   │   ├── RemoteView.kt       # desenho do vídeo e gestos
│   │   └── Discovery.kt        # descoberta UDP do servidor
│   ├── gerar_icone.py          # gera os ícones a partir de icon.jpg
│   ├── build-apk.bat           # compila o APK debug
│   ├── instalar-apk.bat        # instala no celular via adb
│   └── gradlew(.bat)           # Gradle Wrapper (versão fixa do projeto)
├── icon.jpg                     # imagem de origem do ícone do app
├── conectar-usb.bat            # configura o túnel USB (adb reverse)
├── CONTRIBUTING.md
└── LICENSE
```

## Requisitos

| Parte | Requisitos |
|---|---|
| Servidor | Windows 10/11, Python 3.10+ |
| App | Android 7.0+ (API 24) |
| Compilar o app | JDK 17 e Android SDK (API 34); o Gradle 8.7 é baixado pelo wrapper |

## 1. Rodar o servidor no PC

Na primeira vez, dê duplo clique em **`server/iniciar.bat`**: ele cria a venv,
instala as dependências e inicia o servidor. Ou faça manualmente:

```powershell
cd server
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe server.py
```

O servidor mostra a versão, os IPs da máquina e o PIN (quando configurado):

```
[2026-01-01 12:00:00] versao 1.2
[2026-01-01 12:00:00] ouvindo em 192.168.0.10:8765
[2026-01-01 12:00:00] pronto. Abra o app no celular e conecte.
[2026-01-01 12:00:00] PIN ativo: ****
```

### Opções

| Opção | Padrão | Descrição |
|---|---|---|
| `--port` | `8765` | Porta TCP |
| `--bind` | `0.0.0.0` | Interface de escuta |
| `--monitor` | `1` | Monitor inicial (1 = principal) |
| `--pin` | *(vazio)* | Exige PIN de 4+ dígitos |
| `--width` | `1600` | Largura inicial do vídeo |
| `--quality` | `70` | Qualidade JPEG inicial |
| `--fps` | `30` | FPS inicial |
| `--no-gpu` | — | Força captura GDI (`mss`) em vez de DXGI |

```powershell
python server.py --port 8765 --width 1600 --quality 70 --fps 30
python server.py --monitor 2
python server.py --pin 1234
python server.py --no-gpu
```

### PIN sem expor no repositório

O PIN é uma configuração **local**. Use uma das formas:

```powershell
# na linha de comando
server\iniciar.bat --pin 1234

# ou em um arquivo server/pin.txt (já ignorado pelo Git)
echo 1234> server\pin.txt
```

### Firewall

Se o Windows perguntar, **permita o acesso em redes privadas**. Para liberar sem
o popup (PowerShell como Administrador):

```powershell
powershell -ExecutionPolicy Bypass -File server/liberar-firewall.ps1
```

### Iniciar junto com o Windows

Rode **`server/instalar-autostart.bat`**: ele cria um atalho para
`iniciar-oculto.vbs` na pasta Inicializar do usuário. O servidor sobe no login
**sem janela de console**, grava o log em `server/server.log` (rotativo, até 4
arquivos de 1 MB) e erros fatais em `server/server.err.log`.

O autostart **não precisa de administrador**, mas só funciona com a sessão
aberta — a captura de tela depende da área de trabalho do usuário. Para remover,
apague o atalho `LocalControl Servidor` da pasta Inicializar.

Se o servidor já estiver rodando, uma segunda instância apenas falha ao abrir a
porta e sai. Para reiniciar, feche o processo `python.exe` antes.

## 2. Compilar o app Android

```powershell
cd android
.\build-apk.bat
```

O script localiza o JDK 17 e o Android SDK, cria o `local.properties` se
necessário e chama o Gradle. A saída fica em:

```
android/app/build/outputs/apk/debug/app-debug.apk
```

Para compilar manualmente, use o wrapper (na primeira vez ele baixa o Gradle
8.7, então precisa de internet):

```powershell
cd android
$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.21.9-hotspot"
.\gradlew.bat assembleDebug
```

Também é possível abrir a pasta `android/` no Android Studio e usar
**Build → Build APK(s)**.

Instalar no celular conectado:

```powershell
adb install -r android\app\build\outputs\apk\debug\app-debug.apk
```

> O `local.properties` (que aponta o SDK) é gerado automaticamente e **não** vai
> para o Git. O mesmo vale para o APK compilado.

### Ícone do app

O ícone é gerado a partir de **`icon.jpg`** (raiz do projeto). Se trocar a imagem,
rode de novo e recompile:

```powershell
server\.venv\Scripts\python.exe android\gerar_icone.py
```

O script cria `mipmap-mdpi…xxxhdpi/ic_launcher.png` (Android antigo) e
`ic_launcher_foreground.png` (ícone adaptativo do Android 8+), além de
`android/preview_icone.png` para conferência.

## 3. Conectar

### USB (recomendado para começar)

1. No celular: **Opções do desenvolvedor → Depuração USB** ligada.
2. Conecte o cabo e aceite a autorização que aparece na tela do celular.
3. No PC, rode **`conectar-usb.bat`** (executa `adb reverse tcp:8765 tcp:8765`).
4. No app, conecte em **`127.0.0.1`** porta `8765`.

O `adb reverse` precisa ser refeito sempre que reconectar o cabo. Ele é um
comando do PC e é o único passo manual do modo USB.

### Wi-Fi

1. Celular e PC na **mesma rede**.
2. Toque em **Procurar na rede** no app (descoberta UDP automática) ou digite o
   IP mostrado pelo servidor.

### Perfis Casa / Fora

O app guarda **dois endereços** separados (IP + porta):

- **Casa** — IP local do PC, ex.: `192.168.0.10` (no USB, use `127.0.0.1`);
- **Fora** — IP do Tailscale, ex.: `100.x.y.z` (qualquer rede ou 4G).

Toque no perfil antes de conectar. O que estiver nos campos é salvo
automaticamente naquele perfil, inclusive a porta.

### Acessar de fora de casa (outro Wi-Fi ou 4G)

O servidor só fala direto na rede local. Para acessar de qualquer lugar sem
abrir porta no roteador e sem sofrer com CGNAT, use o **Tailscale** — uma VPN
WireGuard que dá um IP fixo `100.x.y.z` para cada aparelho.

1. Instale o Tailscale no **PC** (`winget install Tailscale.Tailscale`) e no
   **celular** (Play Store).
2. Entre nos dois com a **mesma conta** e ligue a VPN.
3. No PC, veja o IP com `tailscale ip -4`.
4. No app, use o perfil **Fora** com esse IP na porta `8765` (a descoberta UDP
   não passa pela VPN).

Dicas:

- o PC precisa estar **ligado e sem dormir** (Painel de Controle → Energia);
- o upload da sua internet limita o FPS (10 Mbps ≈ 10–15 fps no preset Médio);
- rode o servidor com **`--pin`**;
- o Tailscale criptografa o caminho, mas **não abra a porta 8765 no roteador**:
  o protocolo deste projeto não tem TLS.

## 4. Gestos

| Gesto | Ação |
|---|---|
| Toque curto | Clique esquerdo |
| Tocar e arrastar (modo **Toque**, sem zoom) | Cursor vai direto ao ponto |
| Pinça com dois dedos | Zoom de 1x a 5x na imagem |
| Um dedo arrastando (com zoom) | Move a visão (pan); toque curto continua clicando |
| Arrastar (modo **Touchpad**, sem zoom) | Move o cursor |
| Toque longo | Segura o botão (arrastar/janela) |
| Dois dedos arrastando | Rolagem (roda do mouse) |
| Toque com dois dedos | Clique direito |
| Botões **Ctrl/Alt/Shift** | Ficam ativos para a próxima tecla |
| **Teclado** | Abre o teclado do celular; o texto vai para o PC |
| **Q: Média** | Alterna qualidade/tamanho/FPS do vídeo |
| **MON n** | Alterna entre monitores (se houver mais de um) |

O modo de controle é alternado pelo botão **Toque / Touchpad** e fica salvo.

## 5. Protocolo

Toda mensagem nos dois sentidos:

```
[4 bytes: tamanho big-endian][1 byte: tipo][payload]
```

| Tipo | Direção | Payload |
|---|---|---|
| `0x01` VIDEO | servidor → app | `[2 bytes cursorX][2 bytes cursorY][JPEG]` |
| `0x02` SCREEN | servidor → app | JSON `{name, version, w, h, monitor, monitors}` |
| `0x03` CURSOR | servidor → app | `[2 bytes cursorX][2 bytes cursorY]` (só o cursor) |
| `0x10` HELLO | app → servidor | JSON `{v, name, width, quality, fps, pin}` |
| `0x11` INPUT | app → servidor | JSON do evento |
| `0x12` INFO | servidor → app | JSON `{error}` |
| `0x13/0x14` PING/PONG | ambos | JSON `{ts}` (latência) |

Eventos de entrada:

```json
{"t":"m","x":0.5,"y":0.5}           // cursor absoluto (0..1)
{"t":"mr","dx":12,"dy":-3}          // cursor relativo (pixels)
{"t":"b","btn":"left","down":true}  // botão pressionado/solto
{"t":"c","btn":"left","count":1}    // clique
{"t":"s","dy":-120,"dx":0}          // rolagem
{"t":"k","key":"c","mods":["ctrl"]} // tecla + modificadores
{"t":"kt","text":"ola mundo"}       // texto digitado
{"t":"r","width":1600,"quality":72,"fps":30}
{"t":"mon","i":2}
```

O cursor é desenhado no app (o Windows não captura o cursor na imagem), por isso
a posição vai junto de cada quadro — e também no pacote `0x03` quando a tela não
mudou, para o cursor não engasgar. Ao conectar, o app força **paisagem**; ao
desconectar volta para a rotação normal.

## 6. Testar sem o celular

```powershell
cd server
.venv\Scripts\python.exe test_client.py 127.0.0.1 8765
```

O cliente recebe 40 quadros, salva `frame.jpg` e move o cursor do PC para o
centro — se o cursor andar, a cadeia inteira (captura → rede → injeção) está
funcionando. Com a tela parada o keepalive manda 1 quadro por segundo, então o
teste pode levar ~40 s; mexendo em uma janela ele termina bem mais rápido.

## 7. Segurança

Este projeto foi feito para uso pessoal em rede confiável:

- **Sempre use `--pin`**, principalmente com o servidor exposto na rede local.
- O protocolo **não tem TLS**: a imagem e as teclas trafegam sem criptografia.
  Em rede local isso é aceitável; fora de casa, use **Tailscale** (ou outra VPN)
  em vez de abrir portas no roteador.
- O servidor dá **controle total** do PC a quem conectar. Rode-o apenas com uma
  conta de usuário comum e nunca o deixe exposto na internet.
- O PIN fica em `server/pin.txt` (ignorado pelo Git) ou na linha de comando —
  nunca comite o seu.
- O APK das Releases é assinado com a chave de *debug* do Gradle (serve para
  instalar por sideload, mas não para a Play Store). Para publicar oficialmente,
  gere uma keystore própria e configure o `signingConfig` do build de release.

## 8. Problemas comuns

| Sintoma | Causa provável / solução |
|---|---|
| App não conecta por Wi-Fi | Firewall bloqueando (rode `liberar-firewall.ps1`); redes diferentes; IP errado |
| "Falha: conexão recusada" | O servidor não está rodando ou o firewall bloqueia. Veja `server/server.log` |
| App não conecta por USB | `adb devices` não mostra o aparelho → depuração USB/autorização; rode `conectar-usb.bat` de novo |
| Tela preta no app | Servidor sem monitor válido: teste `--monitor 1` e veja o log |
| Cursor fora do lugar | Escala do Windows (DPI): o servidor já ativa DPI-awareness; reinicie-o |
| Muito lag | Use qualidade menor (`Q:` no app) ou USB; 30 fps a 1280 px é o ponto doce |
| Contador baixo com a tela parada | Normal com DXGI: só envia quando algo muda (keepalive de 1 s). O cursor continua fluido pelo pacote `0x03` |
| Setas não rolam a página | Setas são teclado. Para rolar use **dois dedos arrastando** |
| Teclado do app não digita | Toque em **Teclado** de novo (abre/fecha); o campo é invisível de propósito |
| Clique duplo não registra | Toque duas vezes rápido |
| Não conecta fora de casa | Use Tailscale e o IP `100.x.y.z`; o IP `192.168.x.x` só vale na mesma rede |

## 9. Roadmap

- [ ] Vídeo com H.264/MediaCodec (menos banda, mais FPS)
- [ ] Áudio do PC → celular
- [ ] Transferência de arquivos (arrastar e soltar)
- [ ] Atalhos personalizados e macros
- [ ] TLS com certificado local
- [ ] Servidor empacotado como `.exe` (PyInstaller), sem precisar de Python
- [ ] Conexão sem digitar IP (fallback entre últimos endereços, MagicDNS e LAN)
- [ ] Pareamento por QR Code (`localcontrol://host:porta?pin=...`)

## 10. Contribuindo

Contribuições são bem-vindas! Leia o [CONTRIBUTING.md](CONTRIBUTING.md) para
saber como abrir issues, propor mudanças e enviar pull requests.

## Licença

Distribuído sob a licença **MIT** — veja [LICENSE](LICENSE).

O ícone do app é gerado a partir de `icon.jpg`; se você redistribuir o projeto
com outra identidade visual, troque essa imagem pelos seus próprios assets.
