# Segurança do Poltergeist

O Poltergeist dá **controle total do PC** a quem se autenticar: ele captura a
tela e injeta mouse e teclado. Por isso, segurança aqui não é um extra — é parte
do funcionamento. Este documento descreve o que o projeto protege, o que ele
**não** protege e como relatar uma vulnerabilidade.

## Versões suportadas

| Componente | Versão | Suporte de segurança |
|---|---|---|
| Servidor (`server/`) | 2.0 | Sim |
| App Android | 2.0.0 | Sim |
| Versões anteriores | ≤ 1.6 / ≤ 1.3.3 | Não |

Correções de segurança são aplicadas na versão atual. Se você usa uma versão
antiga, atualize antes de relatar um problema de segurança.

## Como relatar uma vulnerabilidade

**Não abra uma issue pública.** Issues públicas expõem o problema antes de
existir correção e podem colocar outros usuários em risco.

Use o canal privado de **GitHub Security Advisories**:

> https://github.com/Gabriewg/Poltergeist/security/advisories/new

Inclua, se possível:

- versão do servidor e do app;
- sistema operacional e versão do Android;
- como o servidor está exposto (LAN, USB/`adb reverse`, Tailscale);
- passos para reproduzir, impacto e uma prova de conceito;
- trechos de log **sem** IPs, nomes de máquina, PIN, chaves ou dados pessoais.

O mantenedor confirma o recebimento e combina um prazo de correção antes de
qualquer divulgação. Não há programa de recompensas; o crédito pelo relato é
dado no aviso de segurança, se você quiser.

## Modelo de ameaça

### Ativos protegidos

- **Controle do PC** (mouse, teclado, tela).
- **Conteúdo da tela**, que pode conter dados pessoais e profissionais.
- **PIN** e a chave derivada dele (`pin.txt`).
- **Chave privada TLS** (`key.pem`).
- **Credencial de cada aparelho pareado** (`devices.json`).

### Limites de confiança

- A **rede local e o Tailscale são tratados como não confiáveis**. Alguém na
  mesma rede (Wi-Fi de hotel, escritório, visitantes) pode tentar escutar,
  interceptar ou se passar pelo PC.
- O **QR de pareamento** é tratado como um canal físico razoavelmente privado:
  ele é exibido na tela do PC e lido pela câmera do celular.
- A **conta de usuário do Windows** e o **aparelho Android** são confiáveis. Se
  um deles estiver comprometido, o modelo não se aplica.
- O servidor **não é feito para a internet aberta**. Não abra a porta 8765 no
  roteador; use Tailscale ou outra VPN.

## O que o projeto protege

### Transporte

- **TLS 1.3 obrigatório** por padrão, com certificado ECDSA P-256 autoassinado.
- O app fixa a **chave pública (SPKI)**, não o certificado inteiro. Renovar o
  certificado mantendo o `key.pem` não exige novo pareamento.
- Chave pública diferente da esperada → conexão **bloqueada** com aviso de
  possível interceptação. Não existe opção de "continuar mesmo assim"; o
  re-pareamento é uma ação explícita do usuário.
- `key.pem` recebe permissões restritas à conta do usuário e nunca vai para o
  Git.

### Autenticação

- **O PIN nunca trafega.** O servidor envia um nonce novo de 32 bytes por
  conexão; o app responde com `HMAC-SHA256(PBKDF2-HMAC-SHA256(PIN), nonce)`.
  Um MAC capturado não pode ser reaproveitado porque o nonce muda.
- `pin.txt` guarda apenas **salt + chave derivada** (210 mil iterações de
  PBKDF2-HMAC-SHA256), nunca o PIN em texto claro.
- **Pareamento por QR com token de uso único.** O QR contém um token aleatório
  de 32 bytes, válido por **180 s** por padrão (faixa de 30 a 600 s). O token
  fica só na memória do servidor e é consumido atomicamente no primeiro uso.
  O app prova posse do token com `HMAC-SHA256(token, nonce)` e envia apenas o
  identificador `pid = SHA-256(token)[:32]` — o token em si não trafega.
- **Credencial por aparelho.** Depois do pareamento, o servidor cria um
  `device_id` e uma `device_key` exclusivos. As conexões seguintes usam
  `HMAC-SHA256(device_key, nonce)`, sem PIN e sem token. A credencial pode ser
  revogada no PC (`--forget-devices` ou menu da bandeja); a revogação vale para
  novas conexões — uma sessão já aberta só termina no app ou reiniciando o
  servidor. No app, a credencial fica na área privada do aplicativo e o backup
  do Android está desativado (`allowBackup="false"`) para não copiar a chave
  para a nuvem.
- **PIN como alternativa manual.** Quem preferir não usar QR pode digitar o PIN;
  nesse caso o app mostra a impressão digital do PC para confirmação no primeiro
  uso.
- **Links externos pedem confirmação.** Um `poltergeist://` aberto por outro
  app ou navegador mostra PC, porta e chave e só conecta depois do usuário
  confirmar. O QR lido dentro do app continua automático.

### Abuso e disponibilidade

- **Rate limit por IP e global**, com atraso progressivo (1 s, 2 s, 4 s…) e
  bloqueio persistente entre reinícios. O limite global cobre o Tailscale, onde
  cada aparelho tem um IP diferente.
- **Teto de 64 KB** para mensagens vindas do app, verificado **antes** de ler o
  corpo.
- **Timeout de 5 s** para o `HELLO`; conexões penduradas são encerradas.
- Toda falha de autenticação é registrada no log com data e IP.
- O servidor avisa no PC quando há conexão ativa: ícone de bandeja vermelho
  (alerta), notificação e log `>>> CONEXAO ATIVA`.

### Chaves e arquivos locais

| Arquivo | Conteúdo | Proteção |
|---|---|---|
| `pin.txt` | salt + chave derivada do PIN | ACL do usuário; ignorado pelo Git |
| `cert.pem` | certificado público | pode ser público |
| `key.pem` | chave privada TLS | ACL do usuário; ignorado pelo Git |
| `auth_state.json` | tentativas e bloqueios | ignorado pelo Git |
| `devices.json` | IDs e chaves dos aparelhos | ACL do usuário; ignorado pelo Git |
| `pair.png` | QR de pareamento | ignorado pelo Git; apague após usar |
| `server.log` | log rotativo | ignorado pelo Git |

Esses arquivos **não fazem parte do `Poltergeist.exe`**: o executável é publicado
sem PIN, sem chave privada e sem aparelhos. Eles são criados na primeira execução
em `%LOCALAPPDATA%\Poltergeist` (ou em `server/` quando o servidor roda pelo
Python). Cada release publica também `Poltergeist.exe.sha256` e o APK Android
com o `.sha256`; confira com
`Get-FileHash .\Poltergeist.exe -Algorithm SHA256` antes de abrir.

Quem já usava o nome antigo não fica sem os dados: na primeira execução a pasta
`%LOCALAPPDATA%\PocketDesk` é **copiada** (nunca movida nem apagada) para a pasta
nova, incluindo `pin.txt`, `cert.pem` e `devices.json`. A cópia é registrada no
log; a pasta antiga continua lá até você apagá-la de propósito.

## O que o projeto NÃO protege

Seja explícito sobre os limites:

- **PC comprometido.** Malware, keylogger ou outro usuário com acesso à sua
  conta podem ler `key.pem`, `pin.txt`, `devices.json`, capturar a tela ou
  injetar eventos diretamente. Nenhum protocolo resolve isso.
- **Celular comprometido ou com root.** Quem controla o aparelho pareado tem a
  `device_key` e pode controlar o PC.
- **Quem fotografa o QR dentro da validade.** O token é de uso único e expira,
  mas um atacante que veja o QR antes de você pode parear primeiro. Trate o QR
  como uma senha temporária: não o mostre em transmissões, prints ou telas
  compartilhadas. Se suspeitar, gere outro e use **Esquecer aparelhos** no PC.
- **Negação de serviço.** Um atacante na rede pode derrubar a conexão, inundar o
  servidor ou consumir CPU/rede. O rate limit reduz força bruta, não garante
  disponibilidade.
- **Metadados e tráfego.** O TLS esconde o conteúdo, mas um observador ainda vê
  que há conexão entre os IPs, volumes e horários. O Tailscale também vê
  metadados da VPN.
- **Comprometimento do Tailscale, do sistema operacional ou da cadeia de
  suprimentos.** Dependências e atualizações do Android/Windows estão fora do
  escopo do projeto.
- **Engenharia social.** Alguém convencer você a parear o aparelho dele, instalar
  um APK modificado ou rodar um comando é um ataque que o código não impede.
- **Tela e dados exibidos.** O conteúdo capturado pode conter segredos; o
  projeto não faz borrão, filtro ou bloqueio de janelas específicas.
- **`--no-tls`.** Modo apenas para diagnóstico. Sem TLS não há confidencialidade
  nem pinning; o PIN precisa ter 8+ caracteres, mas o tráfego ainda pode ser
  lido e alterado por quem estiver no caminho.
- **APK de release assinado com chave de debug.** Serve para sideload, não para
  distribuição oficial. Verifique a origem do APK que você instala.

## Boas práticas para quem usa

1. Rode o servidor com uma conta de usuário comum, não como Administrador.
2. Não abra a porta 8765 no roteador. Para acesso remoto, use Tailscale.
3. Use PIN de 4+ dígitos apenas com TLS (padrão). Sem TLS, use 8+ caracteres.
4. Gere o QR só quando for parear; não deixe `pair.png` aberto ou compartilhado.
5. Revogue aparelhos perdidos: `--forget-devices` no PC e **Esquecer este PC**
   no app.
6. Se a chave do PC mudar sem você ter trocado o certificado, **bloqueie** a
   conexão e investigue.
7. Mantenha Windows, Android, Python e as dependências atualizados. O
   Dependabot abre PRs para `requirements.txt` e Gradle.
8. Leia o `server.log` de vez em quando: falhas repetidas de autenticação e
   conexões inesperadas são sinal de alerta.

## Escopo de divulgação responsável

Relatos bem-vindos incluem, por exemplo:

- falhas no handshake, no pinning ou na verificação de MAC;
- bypass de autenticação, replay de token/MAC ou consumo indevido de token;
- vazamento de PIN, chave privada ou credencial de aparelho;
- estouro de buffer, DoS trivial ou execução de código pelo protocolo;
- problemas no QR que permitam pareamento sem a posse do token.

Fora do escopo: ataques que exigem PC ou celular já comprometido, acesso físico
desbloqueado, engenharia social, DoS volumétrico de rede e relatos sem impacto
prático comprovável.
