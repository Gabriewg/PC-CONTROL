# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
O histórico detalhado de cada mudança fica no `git log`.

## [2.0.2] - 2026-11-25

### Mudado

- O app Android agora exige **Android 10+ (API 29)**, a versão mínima com TLS
  1.3. Em aparelhos com Android 7–9 o Android recusa a instalação, em vez de
  instalar um app que não conseguiria conectar.
- Build Android: Gradle `9.9.2` e plugin do Android (AGP) `9.5.3`, com o Kotlin
  embutido do AGP 9 (o plugin `org.jetbrains.kotlin.android` saiu). `compileSdk`
  e build-tools `36`; `targetSdk` continua `34`.
- Dependências do servidor: `cryptography` 50, `qrcode` 8.2, `Pillow` 13,
  `pystray` 0.19.5 e `opencv-python-headless` 5.1.
- README/README.en: aviso do SmartScreen/antivírus para o `.exe` sem assinatura
  digital, com a conferência do SHA-256.
- Roadmap: o servidor empacotado em `.exe` foi marcado como feito e entraram as
  próximas ideias (área de transferência, teclas especiais, reconexão
  automática, qualidade adaptativa e derrubar a sessão ao revogar um aparelho).
- Versões: servidor `2.0.2`, app `2.0.2` (versionCode 10).

## [2.0.1] - 2026-11-25

### Segurança

- A chave de assinatura do APK saiu do repositório. A 2.0.0 foi assinada com
  uma chave de debug que ficou pública; a partir da 2.0.1 o CI assina com uma
  chave de release privada, guardada nos GitHub Secrets. Quem instalou a 2.0.0
  precisa desinstalar uma vez (a assinatura mudou), o que apaga o pareamento
  salvo no app.
- Versões: servidor `2.0.1`, app `2.0.1` (versionCode 9).

## [2.0.0] - 2026-11-25

### Adicionado

- A release do CI agora publica o **APK Android** junto do `Poltergeist.exe`
  (cada um com o seu `.sha256`). O APK é compilado em `assembleRelease` e
  assinado com a chave fixa do projeto, para atualizar por cima da versão
  anterior.

### Mudado

- **O projeto passou a se chamar Poltergeist.** Os nomes antigos (Local Control,
  PC-CONTROL e PocketDesk) saíram do executável, do app Android, dos scripts,
  dos workflows e da documentação.
- Executável do Windows: `PocketDesk.exe` → **`Poltergeist.exe`** (título da
  janela, bandeja, tooltips, regras de firewall, atalho de inicialização e
  propriedades do arquivo).
- App Android: `app_name` "Poltergeist", `applicationId` e `namespace`
  `io.github.gabriewg.poltergeist` (pacotes movidos para
  `io/github/gabriewg/poltergeist`) e nome do projeto Gradle.
- Esquema do QR/deep link: `localcontrol://` → **`poltergeist://`**. O app
  continua lendo o esquema antigo e o servidor continua respondendo à descoberta
  UDP antiga (`LOCALCONTROL_DISCOVER`), então links e APKs já existentes seguem
  funcionando.
- Pasta de dados: `%LOCALAPPDATA%\PocketDesk` → **`%LOCALAPPDATA%\Poltergeist`**.
  Na primeira execução os dados antigos são copiados (PIN, certificado e
  aparelhos) e a pasta original é preservada. `POLTERGEIST_DATA_DIR` é a nova
  variável; `POCKETDESK_DATA_DIR` ainda é aceita.
- Certificado TLS: organização e CN agora são "Poltergeist" e o SAN inclui
  `poltergeist`. Certificados já existentes continuam válidos — o pinning é
  feito pela chave pública (SPKI), não pelo nome.
- Novo ícone (fantasma com cursor), gerado a partir de `icon.jpg` para o `.exe`,
  a janela, a bandeja e o app Android.
- Versões: servidor `2.0`, executável `2.0.0`, Android `2.0.0` (versionCode 8).

### Corrigido

- A chave pública na janela mostrava "indisponível" para sempre se o servidor
  subisse depois da janela; agora o valor aparece assim que o TLS está pronto.

### Compatibilidade

- Aparelhos pareados antes da renomeação continuam válidos: o certificado e a
  chave privada são preservados na migração.
- O app antigo (`com.localcontrol`) pode ficar instalado ao lado do novo; o
  novo é um pacote separado.

## [1.6.0]

- Janela desktop única (`PocketDesk.exe`) com servidor, QR, PIN, aparelhos e
  sessões; empacotamento via PyInstaller e release com SHA-256.
- Layout compacto para telas de 768p, rolagem discreta e cartão de sessões
  que cresce com as linhas.
