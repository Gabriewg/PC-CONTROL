# Contribuindo

Obrigado pelo interesse em contribuir com o Local Control! Este documento
explica como reportar problemas, propor melhorias e enviar código.

## Antes de começar

- Verifique se já existe uma [issue](../../issues) aberta sobre o mesmo assunto.
- Para dúvidas de uso, descreva o cenário: sistema operacional, versão do app,
  como está conectando (Wi-Fi, USB ou Tailscale) e trechos relevantes de
  `server/server.log`.

## Reportando bugs

Abra uma issue com:

1. **O que você esperava** que acontecesse;
2. **O que aconteceu** de fato (mensagem de erro, print da tela do app);
3. **Como reproduzir**, passo a passo;
4. Ambiente: versão do Windows, versão do Android, versão do Python e se usa
   DXGI ou GDI (`--no-gpu`);
5. O trecho do log do servidor em volta do erro.

> Remova do log IPs, nomes de máquina e qualquer dado pessoal antes de colar.

## Enviando código

1. Faça um **fork** do repositório.
2. Crie uma branch com um nome descritivo:

   ```bash
   git checkout -b feat/transferencia-de-arquivos
   ```

3. Faça as mudanças seguindo o estilo do código existente.
4. Teste localmente (veja abaixo).
5. Abra um **pull request** explicando o problema e a solução. Se possível,
   relacione a issue correspondente.

### Estilo

- **Python**: siga o PEP 8, mantenha as docstrings e os comentários em
  português, como no restante do projeto. Prefira `asyncio` no servidor e evite
  bloquear o loop de eventos.
- **Kotlin**: 4 espaços de indentação, nomes de classes em `PascalCase` e
  funções/variáveis em `camelCase`. Sem dependências externas no app, se
  possível.
- **Commits**: mensagens curtas e no imperativo (`corrige cursor no monitor 2`,
  `adiciona opcao --bind`).
- Não reformate arquivos inteiros junto com uma correção funcional.

### Testando

Servidor, sem precisar do celular:

```powershell
cd server
.venv\Scripts\python.exe test_client.py 127.0.0.1 8765
```

App:

```powershell
cd android
.\build-apk.bat
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

Se a mudança afetar o protocolo, atualize a seção **Protocolo** do `README.md`.

## O que não commitar

O repositório é público e não deve conter dados de quem desenvolve. O
`.gitignore` já cobre os principais casos, mas confira antes de abrir o PR:

- `server/pin.txt`, PINs e senhas;
- logs (`server/server.log*`, `server/server.err.log`);
- IPs reais, nomes de máquina e caminhos com seu usuário;
- `android/local.properties`, APKs, keystores e certificados;
- capturas de tela do seu desktop (`server/pc*.png`, `Screenshot_*.png`).

Se algum dado sensível for commitado por engano, avise o mantenedor — ele
precisa ser removido do histórico, não apenas do commit mais recente.

## Segurança

Não abra uma issue pública para relatar vulnerabilidades. Descreva o problema
em particular para o mantenedor pelo perfil do GitHub e dê um prazo razoável
para a correção antes de divulgar.

## Licença

Ao contribuir, você concorda que sua contribuição será distribuída sob a
licença [MIT](LICENSE) do projeto.
