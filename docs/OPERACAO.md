# ic-ap · Guia de operação

Para instalar (Windows ou Docker), atualizar, fazer backup, recuperar a senha, rodar os testes e resolver os problemas mais comuns.

## 1. Subir e atualizar

### Windows (caminho principal)

Requisitos: Windows 10/11, Python 3.12 ou 3.13 (`winget install Python.Python.3.13`) e ffmpeg (`winget install Gyan.FFmpeg`). GPU NVIDIA só importa para o LLM local e para o servidor de voz, que são programas à parte.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\instalar.ps1   # uma vez: .venv, dependências, Chromium, cloudflared
.\scripts\iniciar.ps1                                              # painel em http://localhost:8000 (somente local)
.\scripts\iniciar.ps1 -AoLigarWindows                              # opcional: sobe sozinho quando você entra no Windows
.\scripts\iniciar.ps1 -RemoverTarefa                               # desfaz o anterior
```

Os dados ficam em `data\` (banco `app.db`, `secret.key`, cards, músicas). Atualizar o código: `git pull` e rodar `instalar.ps1` de novo se o `requirements.txt` mudou; o banco migra sozinho no start.

Com o app no Windows, o seu LLM local (Ollama/LM Studio) é `localhost`: `http://localhost:11434` (Ollama) ou `http://localhost:1234/v1` (LM Studio).

### Docker (opcional)

Requisitos: Docker Desktop (Windows/macOS) ou Docker Engine (Linux). GPU NVIDIA só é necessária para o perfil `gpu` (voz) e para o Ollama embutido.

```bash
docker compose up -d --build          # painel em http://localhost:8000 (somente local)
docker compose logs -f app            # acompanhar o que o app está fazendo
docker compose down                   # parar (os dados ficam no volume)
```

Serviços opcionais do compose:

| Comando | O que sobe |
|---|---|
| `docker compose --profile gpu up -d --build` | Servidor de voz (Whisper + clonagem Chatterbox) em `http://voz:8001` |
| `docker compose stop voz && docker compose --profile qwen up -d --build` | Troca para o motor Qwen3-TTS (rode um motor por vez) |
| `docker compose up -d llm` | Ollama embutido em `127.0.0.1:11434` (exige GPU NVIDIA no compose atual) |

> O serviço `llm` está no `docker-compose.yml` sem `profile`, então sobe junto com o `app` e exige o runtime NVIDIA. Em máquina sem GPU NVIDIA use `docker compose up -d app`. Dentro do container, o seu computador é `host.docker.internal`, **não** `localhost`.

## 2. Primeiro acesso e configuração

1. Abra `http://localhost:8000` e crie a senha mestre (8+ caracteres). A chave de criptografia nasce em `data/secret.key`.
2. **LLM** → conecte Ollama/LM Studio/Gemini/Claude/OpenRouter, use *Detectar modelos* e *Aplicar e testar*. No Windows nativo use `localhost`; dentro do Docker, `host.docker.internal`.
3. **Conexões** → token do túnel Cloudflare (`docs/cloudflare-tunnel.md`), URL pública, bot do Telegram, chaves de imagem/voz.
4. **Perfis** → `@handle`, contexto/tom (`meu_contexto.md` é só a semente), horários, vínculo do Telegram, token e ID do Instagram.

5. **Imagens** (em **Conexões**): chave do Higgsfield e/ou Unsplash. Sem chave, existe um *plano B* (Bing, Wikimedia, Wallhaven, Picsum, Pollinations) que vem **ligado** por padrão; como são imagens de terceiros com possíveis direitos autorais, desligue-o no cartão "Plano B de imagens" se o perfil for profissional.

Toda configuração é feita no painel. Não há `.env`. Variáveis de ambiente existem só para caminhos e testes (`DATA_DIR`, `TEMPLATES_DIR`, `SKILLS_DIR`, `CONTEXT_FILE`, `FEEDS_FILE`, `CHROMIUM_PATH`, `CLOUDFLARED_BIN`, `PUBLIC_PORT`, `SCHEDULER_TICK`, endpoints `*_API_BASE`).

## 3. Senha esquecida

Somente pela linha de comando, na máquina onde o ic-ap roda:

```powershell
cd services\app
..\..\.venv\Scripts\python.exe -m app.reset_senha     # Windows (defina DATA_DIR=..\..\data antes, ou use scripts\_ambiente.ps1)
```
```bash
docker compose exec app python -m app.reset_senha        # Docker
```

(Antes existia um botão "redefinir senha" na tela de login que não exigia autenticação; foi removido por segurança.)

## 4. Backup e restauração

**Windows:** feche o painel e copie a pasta `data\` inteira (banco, `secret.key`, mídia). Para restaurar, copie de volta com o app parado.

**Docker:** tudo o que importa está no volume `icap_data` (banco `app.db`, `secret.key`, cards, músicas, vozes, logotipos). **Sem o `secret.key` os tokens salvos ficam ilegíveis**; faça backup dos dois juntos.

```bash
# backup
docker run --rm -v icap_data:/data -v "$PWD":/backup alpine tar czf /backup/icap-backup.tgz -C /data .
# restauração (com o app parado)
docker run --rm -v icap_data:/data -v "$PWD":/backup alpine sh -c "cd /data && tar xzf /backup/icap-backup.tgz"
```

O nome do volume segue o nome da pasta do projeto (`<pasta>_data`); confira com `docker volume ls`.

## 5. Testes

```powershell
.\scripts\testar.ps1                  # suíte completa (158 testes; ≈7 min com Chromium e ffmpeg reais)
.\scripts\testar.ps1 -Rapido          # só agentes e wizard
```
```bash
cd services/app && pip install -r requirements-dev.txt && python -m pytest    # Linux/macOS/Docker
```

> A suíte foi validada em Linux. No Windows, o teste do túnel usa um `cloudflared` de mentira em shell script (`tests/conftest.py`) e deve falhar até ser adaptado; veja `CLAUDE.md`.

- Requisitos locais: `ffmpeg` no PATH e Chromium do Playwright (`playwright install chromium`). No Windows o `config.py` também procura o Chrome/Edge instalado.
- **Os testes de `test_fluxo.py` dependem da ordem** (fixtures de módulo criam a senha e as conexões de LLM usadas pelos seguintes). Rode o arquivo inteiro; filtrar com `-k` isola testes que dependem de estado criado antes.
- Todos os serviços externos (Meta, Telegram, Gemini, Higgsfield, Unsplash, Anthropic) são simulados por `tests/fake_services.py`; nenhum teste fala com a internet.
- Os testes que precisam trocar a senha do painel usam a fixture `api_client` (restaura a senha ao final). **Não crie um segundo `TestClient(app)`** dentro da suíte: ele derruba o cliente compartilhado e trava o SQLite.
- `python scratch/test_studio.py` valida os 6 layouts, o carregador de skills e o crítico visual de ponta a ponta.

## 6. Solução de problemas

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| "Erro de conexão" ao testar o LLM | Usou `localhost` dentro do container | Use `host.docker.internal` e confirme que o servidor de LLM aceita conexões externas |
| Card não é gerado / erro de render | Chromium indisponível | No Docker já vem na imagem; no Windows rode `instalar.ps1` (ou `playwright install chromium`) ou defina `CHROMIUM_PATH` |
| Instagram recusa a imagem | URL pública do túnel fora do ar | Verifique o token do túnel em **Conexões** e o log do app (`cloudflared`); no Windows confirme que existe `bin\cloudflared.exe` |
| `ImportError: lxml.html.clean` | Faltava `lxml_html_clean` no `requirements.txt` | Já incluído; reconstrua a imagem (`--build`) |
| "database is locked" | Duas conexões abertas ao mesmo arquivo | `db.init()` agora reaproveita a conexão e o SQLite roda em WAL com `busy_timeout` |
| Bot do Telegram não responde | Token errado ou `telegram_chat_id` do perfil vazio | Corrija em **Conexões**/**Perfis**; só o dono vinculado consegue usar os botões |
| Post "falhou" depois de 3 tentativas | LLM devolveu JSON inválido 3 vezes | Veja o motivo em **Histórico**; troque de modelo ou reduza o tamanho do contexto |
| Vídeo sem legenda/transcrição | Sem servidor Whisper | Aba **Voz** → "Usar o servidor embutido" (faster-whisper em CPU) ou suba o perfil `gpu` |

## 7. Segurança em produção

- O painel escuta só em `127.0.0.1` (`iniciar.ps1`; no Docker, `ports: ["127.0.0.1:8000:8000"]`). Se um dia expuser o painel (túnel/domínio), ele passa a ser alvo de força bruta: use senha longa, e considere uma camada extra (Cloudflare Access).
- O túnel deve apontar **somente** para a porta pública (`8081`), que serve apenas `data/public/` (imagens temporárias).
- Trate `data/secret.key` e o backup como segredos.
