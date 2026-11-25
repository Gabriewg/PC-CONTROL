# Poltergeist

**Português** · [English](README.en.md)

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

## Windows: o app (Poltergeist.exe)

O jeito recomendado de usar no PC é o **Poltergeist.exe**: uma janela única, no
estilo RustDesk/AnyDesk, com tudo em um lugar só — ligar o servidor, QR de
pareamento, PIN, aparelhos e sessões. Nada de abrir `.bat` nem console.

1. Baixe `Poltergeist.exe` na página de
   [Releases](https://github.com/Gabriewg/Poltergeist/releases).
2. Confira o SHA-256 (o arquivo `Poltergeist.exe.sha256` vai junto):

   ```powershell
   Get-FileHash .\Poltergeist.exe -Algorithm SHA256
   ```

   O hash precisa ser igual ao publicado na release.
3. Dê duplo clique. Na primeira execução a própria janela pede o PIN e cria o
   certificado TLS; o servidor já sobe ligado.

Fechar (X) minimiza para a bandeja, como no AnyDesk. Para encerrar de verdade,
use **Sair** no menu da bandeja ou no rodapé da janela.

### Onde ficam os dados

O executável **não carrega nenhum segredo**. PIN, certificado, aparelhos e log
são criados em `%LOCALAPPDATA%\Poltergeist` na primeira execução:

| Arquivo | Para que serve |
|---|---|
| `pin.txt` | chave derivada do PIN (PBKDF2; o PIN em si nunca é gravado) |
| `cert.pem` / `key.pem` | certificado ECDSA P-256 e chave privada do TLS |
| `devices.json` | credencial exclusiva de cada aparelho pareado |
| `auth_state.json` | bloqueios do limite de tentativas |
| `server.log` | log rotativo |

Para usar outra pasta (modo portátil ou testes), defina
`POLTERGEIST_DATA_DIR` antes de abrir o programa.

Se você já usava o nome antigo (**PocketDesk**), nada se perde: na primeira
execução o app copia `%LOCALAPPDATA%\PocketDesk` para a pasta nova (PIN,
certificado e aparelhos incluídos) e registra isso no log. A pasta antiga é
mantida como cópia de segurança; apague-a quando tiver certeza. A variável
`POCKETDESK_DATA_DIR` também continua sendo aceita.

Se você rodava pelo Python, os dados ficam em `server/` (PIN, certificado e
aparelhos) e são independentes da pasta do executável: ao passar a usar o
`Poltergeist.exe`, o app avisa que a chave mudou (**Possível interceptação**) e
oferece **Re-parear** — aceite só porque a troca foi sua.

Links de QR antigos (`localcontrol://...`) e o APK anterior continuam
funcionando: o app lê os dois esquemas e o servidor responde à descoberta UDP
antiga. Só o link novo, `poltergeist://`, é gerado daqui em diante.

## Recursos

- **Janela desktop (`Poltergeist.exe`)**: servidor, QR, PIN, aparelhos e sessões
  em uma tela só, com tema preto e vinho.

- Vídeo da tela em JPEG com qualidade, resolução e FPS ajustáveis em tempo real.
- Captura por **DXGI Desktop Duplication** (GPU, ~8 ms/quadro) com fallback
  automático para **GDI** (`mss`, ~33 ms).
- Mouse (absoluto e touchpad), teclado, rolagem, clique direito, arrastar e zoom.
- Suporte a **múltiplos monitores**.
- **Descoberta automática** do PC na rede local (UDP broadcast).
- **Pareamento por QR Code** com token de uso único (2–5 min): o app lê o QR,
  fixa a chave do PC e recebe uma credencial exclusiva do aparelho — sem digitar
  PIN e sem comparar impressão digital à mão.
- **Credencial por aparelho** (`devices.json`): as conexões seguintes não pedem
  PIN; cada aparelho pode ser revogado no PC.
- **TLS 1.3** com certificado ECDSA P-256 e *pinning* da chave pública no app.
- **PIN por desafio-resposta**: o PIN nunca trafega; o app assina um nonce com
  HMAC-SHA256 e o servidor guarda apenas a chave derivada (PBKDF2).
- **Aviso de conexão ativa no PC**: ícone de bandeja verde/vermelho, notificação
  e log `>>> CONEXAO ATIVA` quando alguém conecta.
- **Aviso de tela protegida**: detecta UAC, bloqueio, login e janelas elevadas e
  mostra um banner no app, sem derrubar a conexão.
- **Limite de tentativas** por IP e global, com atraso progressivo e bloqueio
  persistente entre reinícios.
- Controle de fluxo: em rede ruim o servidor **descarta quadros** em vez de
  acumular atraso.
- App praticamente sem dependências externas: ZXing (com o `androidx.core`) só
  para ler o QR Code; o resto usa APIs do Android.

## Estrutura do repositório

```
.
├── server/                     # servidor Python (Windows)
│   ├── app.py                  # janela desktop (Poltergeist.exe)
│   ├── desktop/                # tema, widgets, host, bandeja e diálogos
│   ├── server.py               # TCP/TLS, captura, protocolo, descoberta e pareamento
│   ├── security.py             # PIN (PBKDF2), desafio HMAC, tokens, aparelhos e TLS
│   ├── tray.py                 # ícone de bandeja do modo console
│   ├── wininput.py             # injeção de mouse/teclado via SendInput
│   ├── iniciar.bat             # abre a janela (--console para o modo antigo)
│   ├── definir-pin.bat         # define/troca o PIN no terminal (modo console)
│   ├── autostart.bat           # execução em segundo plano (usado pelo .vbs)
│   ├── iniciar-oculto.vbs      # sobe o servidor sem janela (legado)
│   ├── instalar-autostart.bat  # atalho na pasta Inicializar (legado)
│   ├── liberar-firewall.ps1    # libera as portas 8765/TCP e 8766/UDP
│   ├── build-exe.bat           # gera dist/Poltergeist.exe + SHA-256
│   ├── Poltergeist.spec        # receita do PyInstaller
│   ├── gerar_icone_exe.py      # gera .ico e brand.png a partir do icon.jpg
│   ├── test_client.py          # cliente de teste (sem celular)
│   ├── test_pair.py            # testes do pareamento por QR e da credencial
│   ├── bench*.py               # benchmarks de captura/codificação
│   └── requirements.txt
├── android/                    # app Android (Kotlin)
│   ├── app/src/main/java/io/github/gabriewg/poltergeist/
│   │   ├── MainActivity.kt     # interface, perfis e pareamento/MITM
│   │   ├── RemoteClient.kt     # TLS, handshake e recebimento do vídeo
│   │   ├── Pairing.kt          # parser do link poltergeist:// e token
│   │   ├── LocalCrypto.kt      # PBKDF2, HMAC e impressão digital SPKI
│   │   ├── PinningTrustManager.kt # confia só na chave pública pareada
│   │   ├── RemoteView.kt       # desenho do vídeo e gestos
│   │   └── Discovery.kt        # descoberta UDP do servidor
│   ├── gerar_icone.py          # gera os ícones a partir de icon.jpg
│   ├── build-apk.bat           # compila o APK debug
│   ├── instalar-apk.bat        # instala no celular via adb
│   └── gradlew(.bat)           # Gradle Wrapper (versão fixa do projeto)
├── .github/dependabot.yml      # atualizações automáticas de pip e Gradle
├── .github/workflows/build-exe.yml # gera o Poltergeist.exe e o SHA-256
├── icon.jpg                    # imagem de origem do ícone do app
├── conectar-usb.bat            # configura o túnel USB (adb reverse)
├── SECURITY.md                 # modelo de ameaça e canal de reporte
├── CONTRIBUTING.md
├── CHANGELOG.md
└── LICENSE
```

## Requisitos

| Parte | Requisitos |
|---|---|
| Servidor | Windows 10/11. O `Poltergeist.exe` já traz tudo; para rodar pelo Python, 3.10+ (as dependências são instaladas pelo `iniciar.bat`) |
| App | **Android 10+** (API 29) para o TLS 1.3; o APK instala no 7.0+, mas conexões TLS exigem o 10+ |
| Compilar o app | JDK 17 e Android SDK (API 34); o Gradle 8.7 é baixado pelo wrapper |

## 1. Rodar o servidor no PC

O caminho recomendado é o **`Poltergeist.exe`** (veja
[Windows: o app](#windows-o-app-poltergeistexe)): a janela liga o servidor,
mostra o QR, cria o PIN no primeiro uso e avisa quando alguém conecta.

Para desenvolver ou rodar pelo Python, dê duplo clique em
**`server/iniciar.bat`** (abre a mesma janela) ou use `iniciar.bat --console`
para o modo antigo, com terminal. Manualmente:

```powershell
cd server
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\pythonw.exe app.py                # janela
.venv\Scripts\python.exe server.py --set-pin    # PIN no terminal (modo console)
.venv\Scripts\python.exe server.py              # servidor no console
```

No modo console, o `--set-pin` pede o PIN duas vezes (não fica no histórico do
shell). O servidor mostra a versão, os IPs e a impressão digital da chave
pública:

```
[2026-01-01 12:00:00] versao 2.0
[2026-01-01 12:00:00] TLS 1.3 ativo (certificado ECDSA P-256).
[2026-01-01 12:00:00] impressao digital da chave publica (confira no app):
[2026-01-01 12:00:00]   nkIw NS/a dvHD L5Fg ipLe G0/t /KuQ B7Lm 7bgt TohR vYc=
[2026-01-01 12:00:00] ouvindo em 192.168.0.10:8765
[2026-01-01 12:00:00] pronto. Abra o app no celular e conecte.
```

No modo console também aparece o **QR de pareamento** (veja
[Pareamento por QR](#pareamento-por-qr-recomendado)). A impressão digital é da **chave
pública (SPKI)**, não do certificado inteiro. Se você renovar o certificado
mantendo o `key.pem`, o app não precisa re-parear.

### Opções

A janela aceita `--port`, `--discovery-port` e `--no-gpu`; todo o resto (PIN,
aparelhos, QR, autostart) é feito na própria tela. O `server.py` continua com as
opções de console:

| Opção | Padrão | Descrição |
|---|---|---|
| `--port` | `8765` | Porta TCP |
| `--discovery-port` | `8766` | Porta UDP da descoberta |
| `--bind` | `0.0.0.0` | Interface de escuta |
| `--monitor` | `1` | Monitor inicial (1 = principal) |
| `--set-pin` | — | Define/troca o PIN (pede no terminal) e sai |
| `--no-tls` | — | Desliga o TLS (**só diagnóstico**; exige PIN de 8+ caracteres) |
| `--cert` / `--key` | `cert.pem` / `key.pem` | Par certificado/chave alternativo |
| `--width` | `1600` | Largura inicial do vídeo |
| `--quality` | `70` | Qualidade JPEG inicial |
| `--fps` | `30` | FPS inicial |
| `--no-gpu` | — | Força captura GDI (`mss`) em vez de DXGI |
| `--pair-ttl` | `180` | Validade do QR em segundos (30 a 600) |
| `--no-qr` | — | Não mostra o QR ao iniciar (use `q` no console) |
| `--qr-open` | — | Abre `pair.png` no visualizador ao iniciar |
| `--no-tray` | — | Não usa ícone de bandeja (aviso só no console) |
| `--forget-devices` | — | Revoga todos os aparelhos pareados e sai |

```powershell
python server.py --port 8765 --width 1600 --quality 70 --fps 30
python server.py --monitor 2
python server.py --no-gpu
```

### PIN e arquivos locais

O PIN é uma configuração **local** e não deve ser passado por `--pin` (ficaria
no histórico do shell). Na janela, use o botão **Trocar** ao lado do PIN. No modo
console:

```powershell
server\definir-pin.bat
# ou:
cd server
.venv\Scripts\python.exe server.py --set-pin
```

No `Poltergeist.exe`, os arquivos ficam em `%LOCALAPPDATA%\Poltergeist`; rodando
pelo Python, em `server/` (tudo ignorado pelo Git):

| Arquivo | Conteúdo |
|---|---|
| `pin.txt` | salt + chave derivada do PIN (PBKDF2-HMAC-SHA256, 210 mil iterações). **Não contém o PIN.** |
| `cert.pem` | certificado autoassinado ECDSA P-256, validade de 5 anos |
| `key.pem` | chave privada (permissões restritas à sua conta) |
| `auth_state.json` | tentativas/bloqueios de PIN (persistem entre reinícios) |
| `devices.json` | credenciais dos aparelhos pareados (ID + chave de 32 bytes) |
| `pair.png` | último QR gerado no modo console (apague depois de usar) |
| `server.log` | log rotativo, com data/hora e IP de cada falha |

Política do PIN:

- **com TLS** (padrão): mínimo de 4 caracteres — um PIN de 4 dígitos só é aceito
  porque o transporte é criptografado e há rate limit;
- **sem TLS** (`--no-tls`): mínimo de **8 caracteres**. O servidor recusa subir
  com um PIN curto nesse modo.

No modo console, reinicie o servidor depois de trocar o PIN. Na janela a troca
vale na hora. Aparelhos já pareados continuam conectando pela credencial
própria; para uma conexão manual nova, use o mesmo PIN no app (o app pergunta a
digital do PC só no primeiro pareamento).

### Firewall

Na janela, use o botão **Liberar firewall** no rodapé (o Windows pede
confirmação de administrador uma vez). Se preferir o popup do Windows,
**permita o acesso em redes privadas**. Ou, no PowerShell como Administrador:

```powershell
powershell -ExecutionPolicy Bypass -File server/liberar-firewall.ps1
```

### Iniciar junto com o Windows

Na janela, ligue a chave **Iniciar com o Windows** no rodapé: ela cria (ou
remove) um atalho na pasta Inicializar do usuário, sem pedir senha.

O modo antigo continua disponível: **`server/instalar-autostart.bat`** cria um
atalho para `iniciar-oculto.vbs`, que sobe só o servidor, sem janela. O
autostart **não precisa de administrador**, mas só funciona com a sessão aberta
— a captura de tela depende da área de trabalho do usuário.

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

### Pareamento por QR (recomendado)

Na primeira conexão de cada aparelho, use o QR — ele resolve o problema de
"como confiar na chave do PC" sem comparar impressão digital à mão.

1. Com o servidor rodando, o QR aparece na janela (no modo console, também é
   salvo em `server/pair.png`).
2. No app, toque em **Parear com QR Code** e aponte a câmera. Se preferir, use
   **colar o link** no diálogo de ajuda. Se o link for aberto pela câmera do
   sistema (fora do app), o app mostra PC, porta e chave e pede confirmação
   antes de conectar.
3. O app confere a chave pública do PC, envia a prova do token e recebe uma
   **credencial exclusiva do aparelho**. A partir daí ele conecta sem PIN.

O QR vale por **180 segundos** (ajuste com `--pair-ttl`, de 30 a 600) e serve
**uma única vez**. O token não é o PIN: ele fica só na memória do servidor,
expira e é consumido no primeiro pareamento. O link tem o formato:

```
poltergeist://192.168.0.10:8765?v=1&fp=<SPKI base64url>&t=<token>&n=<PC>
```

No console do servidor:

| Tecla | Ação |
|---|---|
| `q` | Gera um novo QR (invalida o anterior) |
| `d` | Lista os aparelhos pareados |
| `x` | Encerra o servidor |

Para revogar aparelhos, use **Esquecer aparelhos** na bandeja ou rode o servidor
com `--forget-devices`. A revogação impede novas conexões; uma sessão que já
está aberta continua até ser encerrada no app (ou até o servidor parar).

Na bandeja, o menu tem as mesmas ações. O ícone fica **vermelho** com conexão
ativa (alerta de que alguém está controlando o PC) e **verde** sem conexão; ao
conectar, aparece uma notificação com o nome do aparelho e o IP.

> Trate o QR como uma senha temporária: não o mostre em prints, transmissões ou
> telas compartilhadas. Se ele vazar antes de você usar, gere outro com `q` e,
> por precaução, use **Esquecer aparelhos** no PC.

O pareamento por QR exige TLS (o padrão). Com `--no-tls` ele fica indisponível;
nesse caso use o PIN manualmente.

### USB (rápido e estável)

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
- o PIN (ou o pareamento por QR) é obrigatório: o app usa a credencial do
  aparelho ou o PIN, e o PIN nunca trafega pela rede;
- o Tailscale criptografa o caminho, e o **TLS 1.3** do projeto protege a
  conexão mesmo na rede local. Ainda assim, **não abra a porta 8765 no
  roteador**: o servidor foi feito para LAN/Tailscale, não para a internet.

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
| `0x02` SCREEN | servidor → app | JSON `{name, version, w, h, monitor, monitors, tls}` |
| `0x03` CURSOR | servidor → app | `[2 bytes cursorX][2 bytes cursorY]` (só o cursor) |
| `0x10` HELLO | app → servidor | JSON `{v:3, name, width, quality, fps, mac}` + `pid` (QR) ou `device` (aparelho) |
| `0x11` INPUT | app → servidor | JSON do evento |
| `0x12` INFO | servidor → app | JSON `{warn?, on?, error?}` (aviso não fatal ou erro fatal) |
| `0x13/0x14` PING/PONG | ambos | JSON `{ts}` (latência) |
| `0x15` CHALLENGE | servidor → app | JSON `{v, kdf, iter, salt, nonce, auth}` |
| `0x16` PAIR_OK | servidor → app | JSON `{v, id, key, name}` (credencial do aparelho, só no pareamento) |

O `INFO` com `{"warn":"secure_desktop","on":true}` (UAC/bloqueio/login) ou
`{"warn":"admin_window","on":true}` (janela elevada) é **não fatal**: o app
mostra um banner, mantém os gestos e a conexão, e esconde o banner quando chega
`{"warn":"","on":false}`. O aviso só é enviado quando o estado muda; servidores
antigos não mandam esse campo e apps antigos o ignoram. O campo `error`
continua sendo fatal, como antes.

### Handshake (PIN por desafio-resposta e credencial)

1. O app abre **TLS 1.3** e confere a chave pública (SPKI) do servidor com a que
   foi salva no pareamento.
2. O servidor envia `CHALLENGE` com um **nonce novo de 32 bytes**.
3. O app responde `HELLO` com um dos três modos:
   - **PIN**: `mac = HMAC-SHA256(PBKDF2(pin, salt, 210000, 32), nonce)`;
   - **QR**: `pid = SHA-256(token)[:32]` e `mac = HMAC-SHA256(token, nonce)`;
   - **aparelho**: `device = <id>` e `mac = HMAC-SHA256(device_key, nonce)`.
4. O servidor confere com `hmac.compare_digest`. O PIN **nunca sai do aparelho**
   e o MAC não pode ser reaproveitado, porque o nonce muda a cada conexão.
5. No modo QR, o servidor consome o token atomicamente, cria a credencial do
   aparelho e a envia em `PAIR_OK`. O app só a grava depois de conferir que o
   PC provou ter a chave do QR.

O `salt`, o `nonce` e o `pid` não são segredos: quem os vê não consegue derivar a
chave sem o PIN/token. Cada falha é registrada no log com data e IP, e tentativas
repetidas sofrem atraso progressivo e bloqueio por IP e global.

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

Testes do pareamento por QR (não tocam no servidor real):

```powershell
cd server
.venv\Scripts\python.exe test_pair.py
```

Cliente de vídeo, sem precisar do celular:

```powershell
.venv\Scripts\python.exe test_client.py 127.0.0.1 8765 40 SEU_PIN
```

O cliente faz o mesmo handshake do app (TLS 1.3 + desafio/HMAC). Para ver a
impressão digital do servidor sem autenticar:

```powershell
.venv\Scripts\python.exe test_client.py 127.0.0.1 8765 0 "" --show-fingerprint
```

Para exigir a digital exata (pinning):

```powershell
.venv\Scripts\python.exe test_client.py 127.0.0.1 8765 40 SEU_PIN --fingerprint BASE64_DA_SPKI
```

Se o servidor estiver com `--no-tls` (só diagnóstico), use `--no-tls` também:

```powershell
.venv\Scripts\python.exe test_client.py 127.0.0.1 8765 40 "senha-de-8-ou-mais" --no-tls
```

O cliente recebe 40 quadros, salva `frame.jpg` e move o cursor do PC para o
centro — se o cursor andar, a cadeia inteira (captura → rede → injeção) está
funcionando. Com a tela parada o keepalive manda 1 quadro por segundo, então o
teste pode levar ~40 s; mexendo em uma janela ele termina bem mais rápido.

## 7. Segurança

O projeto usa **TLS 1.3**, **PIN por desafio-resposta** e **pareamento por QR
com token de uso único** por padrão:

- **Transporte criptografado.** Certificado ECDSA P-256 autoassinado, gerado na
  primeira execução, com validade de 5 anos. O app confia na **chave pública
  (SPKI)**, não no certificado inteiro: renovar o certificado com o mesmo
  `key.pem` não exige re-parear.
- **PIN nunca trafega.** O servidor manda um nonce novo por conexão; o app
  responde `HMAC-SHA256(PBKDF2(pin), nonce)`. O `pin.txt` guarda apenas o
  resultado da KDF (salt + chave), nunca o PIN.
- **QR de uso único.** O token do QR vale 180 s (30–600 s), fica só na memória e
  é consumido no primeiro pareamento. O app envia `pid = SHA-256(token)[:32]` e
  `HMAC-SHA256(token, nonce)`; o token em si nunca trafega.
- **Credencial por aparelho.** Depois do pareamento, cada celular recebe um
  `device_id` e uma `device_key` de 32 bytes, guardados em `devices.json` e nas
  preferências do app. Revogue com `--forget-devices` ou no menu da bandeja; a
  revogação bloqueia novas conexões, mas não derruba uma sessão já aberta.
- **Sem MITM silencioso.** Se a chave do PC mudar, o app mostra as digitais
  antiga e nova, **bloqueia** a conexão e só permite re-parear por ação
  explícita do usuário. Não existe "continuar mesmo assim".
- **Aviso de conexão ativa.** A bandeja fica vermelha, mostra notificação e o
  log registra `>>> CONEXAO ATIVA` com nome do aparelho e IP.
- **Avisos de tela protegida são informativos.** O servidor detecta UAC,
  bloqueio, login e janelas elevadas, mas **não** contorna o isolamento do
  Windows. O banner não altera autenticação, TLS nem permissões: ele só evita
  que o usuário remoto pense que a conexão caiu.
- **Força bruta limitada.** Atraso progressivo (1 s, 2 s, 4 s…), bloqueio por IP
  e global (útil no Tailscale, onde cada aparelho tem um IP), persistente entre
  reinícios, e log de cada falha com data/IP.
- **Mensagens limitadas.** O servidor recusa qualquer mensagem do app acima de
  64 KB (o servidor é quem envia os JPEGs) e encerra conexões que não mandam o
  `HELLO` em 5 s.
- **Chaves protegidas.** `key.pem`, `pin.txt` e `devices.json` têm permissões
  restritas à sua conta e estão no `.gitignore`, junto com `pair.png`,
  `auth_state.json` e `*.log`. **Nunca comite** esses arquivos: vazar `key.pem`
  anula o TLS e vazar `devices.json` dá acesso aos aparelhos pareados.

O servidor dá **controle total** do PC a quem autenticar. Rode-o com uma conta de
usuário comum e não abra a porta 8765 no roteador — para acesso fora de casa use
**Tailscale** (ou outra VPN). O `--no-tls` existe só para diagnóstico e exige PIN
de 8+ caracteres; não use em rede não confiável.

O modelo de ameaça completo — o que o projeto protege, o que **não** protege e o
que está fora do escopo — está em [SECURITY.md](SECURITY.md). Para relatar uma
vulnerabilidade, use o
[Security Advisory privado](https://github.com/Gabriewg/Poltergeist/security/advisories/new);
não abra issue pública.

O APK das Releases é assinado com a chave de *debug* do Gradle (serve para
instalar por sideload, mas não para a Play Store). Para publicar oficialmente,
gere uma keystore própria e configure o `signingConfig` do build de release.

## 8. Problemas comuns

| Sintoma | Causa provável / solução |
|---|---|
| App não conecta por Wi-Fi | Firewall bloqueando (rode `liberar-firewall.ps1`); redes diferentes; IP errado |
| "Falha: conexão recusada" | O servidor não está rodando ou o firewall bloqueia. Veja `server/server.log` |
| App não conecta por USB | `adb devices` não mostra o aparelho → depuração USB/autorização; rode `conectar-usb.bat` de novo |
| Tela preta no app | Servidor sem monitor válido: teste `--monitor 1` e veja o log. Se aconteceu ao abrir UAC, bloqueio, login ou um programa elevado, veja [Limitações conhecidas](#limitações-conhecidas) |
| Cursor fora do lugar | Escala do Windows (DPI): o servidor já ativa DPI-awareness; reinicie-o |
| Muito lag | Use qualidade menor (`Q:` no app) ou USB; 30 fps a 1280 px é o ponto doce |
| Contador baixo com a tela parada | Normal com DXGI: só envia quando algo muda (keepalive de 1 s). O cursor continua fluido pelo pacote `0x03` |
| Setas não rolam a página | Setas são teclado. Para rolar use **dois dedos arrastando** |
| Teclado do app não digita | Toque em **Teclado** de novo (abre/fecha); o campo é invisível de propósito |
| Clique duplo não registra | Toque duas vezes rápido |
| Não conecta fora de casa | Use Tailscale e o IP `100.x.y.z`; o IP `192.168.x.x` só vale na mesma rede |
| "autenticacao falhou" | O PIN do app é diferente do PC. Rode `definir-pin.bat` e use o mesmo PIN |
| "muitas tentativas de PIN" | Bloqueio após falhas. Espere o tempo indicado; com o servidor parado, apague `server/auth_state.json` para zerar |
| "A chave do PC mudou" | O `cert.pem`/`key.pem` foi regenerado. Confira a digital no PC e só re-pareie se foi você |
| "QR inválido ou incompleto" | Link truncado, QR vencido ou de outra versão. Gere outro com `q` no console e leia de novo |
| "pareamento invalido ou expirado" | O token já foi usado ou passou do `--pair-ttl`. Gere um novo QR; se persistir, veja o relógio do PC |
| "aparelho nao reconhecido" | O aparelho foi revogado (`--forget-devices` ou bandeja) ou o `devices.json` foi apagado. Pareie de novo |
| Câmera não abre | Permissão de câmera negada ou aparelho sem câmera. Use **colar o link** no diálogo de pareamento |
| Bandeja não aparece | `pystray`/`Pillow` ausentes ou `--no-tray`. O aviso de conexão continua no console e no log |
| "TLS 1.3 exige Android 10+" | Aparelho antigo. O TLS 1.3 do app precisa de Android 10 (API 29) ou mais novo |
| "o PC nao aceitou TLS 1.3" | O servidor está com `--no-tls` ou é uma versão antiga. Rode o `server.py` atualizado, sem `--no-tls` |

## Limitações conhecidas

O servidor roda como um programa comum na sessão do usuário. Por segurança, o
Windows isola certas telas e janelas, e um processo sem privilégios não consegue
capturá-las nem controlá-las:

- **UAC, tela de bloqueio, tela de login e Ctrl+Alt+Del.** Essas telas rodam na
  "área de trabalho segura" (`Winlogon`). A imagem fica preta ou congelada e o
  app mostra o aviso *"Tela protegida pelo Windows (UAC, bloqueio ou login)…"*.
  O aviso some sozinho quando você volta para a área de trabalho normal.
- **Programas executados como administrador.** A imagem aparece, mas o Windows
  ignora cliques e teclas enviados por um processo não elevado (UIPI). O app
  mostra *"Janela de administrador: o Windows está ignorando seus cliques e
  teclas."* Para controlar essa janela, o servidor também precisaria estar
  elevado — e isso aumenta bastante o risco.
- **Ctrl+Alt+Del** não pode ser enviado por software. Use o teclado físico do PC
  ou o botão de segurança do Windows.
- **Tela toda preta por outros motivos** (proteção de conteúdo/DRM, monitor
  desligado ou driver de vídeo) também pode acionar o aviso. Ele é apenas um
  aviso: a conexão continua e o vídeo volta quando a tela volta ao normal.

Dicas para quem vai ficar fora de casa:

- deixe o PC **ligado, desbloqueado e sem dormir**. Isso reduz a segurança
  física: quem estiver perto do PC tem acesso à sessão;
- evite abrir remotamente instaladores e programas que peçam UAC;
- se precisar controlar um programa elevado, abra-o antes de sair ou use o
  teclado e o mouse físicos;
- o aviso é uma limitação conhecida do Windows, **não um bug** do Poltergeist.

A solução completa (veja o Roadmap) é um serviço do Windows rodando como
`SYSTEM`, que troca de área de trabalho para enxergar UAC/login e injeta entrada
nas janelas elevadas. É a mesma abordagem usada por outros apps de acesso
remoto.

## 9. Roadmap

- [ ] Vídeo com H.264/MediaCodec (menos banda, mais FPS)
- [ ] Áudio do PC → celular
- [ ] Transferência de arquivos (arrastar e soltar)
- [ ] Atalhos personalizados e macros
- [x] TLS 1.3 com certificado local e pinning da chave pública
- [x] PIN por desafio-resposta + rate limit persistente
- [x] Pareamento por QR Code com token de uso único e credencial por aparelho
- [ ] Servidor empacotado como `.exe` (PyInstaller), sem precisar de Python
- [ ] Conexão sem digitar IP (fallback entre últimos endereços, MagicDNS e LAN)
- [ ] Serviço do Windows (`SYSTEM`) com troca de área de trabalho para enxergar
      UAC/tela de login e permitir entrada em programas elevados. É a mesma
      abordagem de outros apps de acesso remoto; a implementação deve seguir a
      documentação da Microsoft (`WTSGetActiveConsoleSessionId`,
      `CreateProcessAsUser`, `OpenInputDesktop` e `SetThreadDesktop`).

### TLS, PIN e pareamento (implementado)

**Servidor (`server/security.py` + `server/server.py` + `server/tray.py`)**

- `pin.txt` guarda `{v, kdf, iterations, salt, key, requires_tls, created}`; a
  chave é PBKDF2-HMAC-SHA256 com 210 mil iterações e salt de 16 bytes. O PIN
  puro nunca é gravado.
- Cada conexão recebe um nonce de 32 bytes (`0x15 CHALLENGE`); o `HELLO` traz
  apenas `mac = HMAC-SHA256(chave, nonce)`, conferido com
  `hmac.compare_digest`.
- `PairingTokens` mantém tokens em memória (32 bytes, TTL padrão 180 s, faixa
  30–600 s, uso único). `verify_and_consume` confere o HMAC e apaga o token na
  mesma operação.
- `DeviceStore` grava `devices.json` com `device_id` (16 hex) e `device_key`
  (32 bytes) por aparelho, em escrita atômica e com ACL restrita.
- `cert.pem`/`key.pem` são gerados na primeira execução (ECDSA P-256, 5 anos) e
  `key.pem` recebe ACL restrita no Windows. A impressão digital exibida é a
  SHA-256 da **SPKI**.
- `ssl.SSLContext` com `minimum_version = TLSv1_3`, `ssl=` no
  `asyncio.start_server` e `ssl_handshake_timeout` de 5 s.
- `RateLimiter` persistente: 5 falhas/5 min por IP → 5 min de bloqueio;
  20 falhas/10 min globais → 5 min; atraso `2^(n-1)` limitado a 15 s; toda falha
  vai para o log com data e IP.
- Mensagens do app limitadas a 64 KB **antes** de ler o corpo; o `HELLO` tem
  5 s para chegar.
- QR desenhado no console com `qrcode`, salvo em `pair.png` e também acessível
  pela bandeja (`pystray` + Pillow), que mostra conexão ativa e notifica.

**App (`RemoteClient.kt`, `LocalCrypto.kt`, `PinningTrustManager.kt`, `Pairing.kt`)**

- `SSLSocket` com `TLSv1.3` e um `X509TrustManager` que compara a SPKI com a
  salva em `spki_casa`/`spki_fora`; a verificação de hostname não é desligada
  globalmente.
- `Pairing.kt` lê `poltergeist://host:porta?fp=...&t=...`, valida o token e
  converte a SPKI base64url. A câmera usa ZXing Android Embedded; sem câmera,
  o link pode ser colado.
- `HELLO v3` escolhe o modo: token de pareamento (`pid` + HMAC do token),
  credencial do aparelho (`device` + HMAC da device key) ou PIN.
- `PAIR_OK` só é gravado depois que o TLS já provou a chave do QR; o app salva
  SPKI + credencial juntos. Digital diferente → `PinningException` → diálogo de
  **possível interceptação**, conexão bloqueada e re-pareamento só por ação
  explícita.
- PBKDF2-HMAC-SHA256 implementado à mão (funciona na API 24) e conferido contra
  vetores públicos (`password`/`salt`, 1 e 4096 iterações) e contra o
  `hashlib` do Python.

Critérios de aceite verificados com `server/test_pair.py`,
`server/test_client.py` e testes de integração: PIN correto conecta; PIN errado,
replay de MAC e cabeçalho de 4 GB são recusados; `HELLO` pendurado cai em 5 s;
bloqueio por IP persiste após reiniciar; `--no-tls` recusa PIN curto e aceita PIN
de 8+; QR pareia uma vez, token expirado/reutilizado é recusado, MAC errado não
consome o token e a credencial do aparelho reconecta sem PIN.

## 10. Contribuindo

Contribuições são bem-vindas! Leia o [CONTRIBUTING.md](CONTRIBUTING.md) para
saber como abrir issues, propor mudanças e enviar pull requests.

## Licença

Distribuído sob a **GNU Affero General Public License v3.0 ou posterior**
(`AGPL-3.0-or-later`) — veja [LICENSE](LICENSE).

A AGPL exige que quem oferece o Poltergeist como serviço pela rede também
disponibilize o código-fonte correspondente. Os arquivos `.py` e `.kt` trazem o
cabeçalho `SPDX-License-Identifier: AGPL-3.0-or-later`.

O ícone do app é gerado a partir de `icon.jpg`; se você redistribuir o projeto
com outra identidade visual, troque essa imagem pelos seus próprios assets.
