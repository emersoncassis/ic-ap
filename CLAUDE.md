# ic-ap · instruções para o Claude Code

Automação local de conteúdo para Instagram (FastAPI + Jinja2, SQLite, Playwright/Chromium, ffmpeg, bot do Telegram). Responda e comente o código em **português do Brasil**.

## Ambiente (Windows nativo, sem Docker)

- Instalar: `powershell -ExecutionPolicy Bypass -File .\scripts\instalar.ps1`
- Subir o painel: `.\scripts\iniciar.ps1` → http://localhost:8000
- Testes: `.\scripts\testar.ps1` (completo, ≈7 min) ou `.\scripts\testar.ps1 -Rapido`
- Variáveis de ambiente de caminho ficam em `scripts\_ambiente.ps1`. **Não existe `.env`**: toda configuração do usuário vive no SQLite e é editada pelo painel.
- O LLM do usuário roda fora do app (Ollama `http://localhost:11434` ou LM Studio `http://localhost:1234/v1`) em GPU NVIDIA (RTX 5070, 8 GB). Não suba LLM em container.
- O Docker (`docker-compose.yml`) é opção de deploy futuro, não o fluxo de desenvolvimento.

## Mapa

Leia `docs/ARQUITETURA_E_MODULOS.md` antes de mexer. Código em `services/app/app/`; agentes em `agentes/` com instruções em `skills/*/SKILL.md` (fonte única, recarregadas por `mtime`); testes em `services/app/tests/`; estado do trabalho e dívida em `docs/REVISAO_2026-10-22.md`.

## Regras do projeto

- Rode a suíte antes de dizer que terminou. Todos os serviços externos (Meta, Telegram, Gemini, Higgsfield, Unsplash, Anthropic) são simulados em `tests/fake_services.py`; nenhum teste fala com a internet nem com LLM real.
- `tests/test_fluxo.py` depende da ordem: rode o arquivo inteiro, nunca com `-k`.
- Nunca crie um segundo `TestClient(app)`; use as fixtures `api_client` e `estado_isolado` de `conftest.py`.
- Tarefas em segundo plano: use `tarefas.disparar(...)`, nunca `asyncio.create_task` solto.
- Segurança: não recrie rota de reset de senha sem login; POSTs JSON são protegidos pelo bloqueio de `Origin`; segredos só criptografados (`crypto.py`).
- O plano B de imagens (`bancos_abertos`) usa fotos de terceiros; não ligue por padrão em perfil profissional.
- Antes de commitar: `python -m ruff check --select F,E9 services/app`. Mensagens de commit em português.

## Pendências conhecidas (prioridade)

1. ~~Windows nunca testado~~ **Resolvido:** a suíte completa passa no Windows (201 testes). O `cloudflared` falso agora é um script Python com wrapper `.bat`/`sh`. Detalhes em `docs/OPERACAO.md` ("Particularidades do Windows").
2. `.venv\` e `bin\` não vão para o git (já no `.gitignore`).
3. ~~Repositório sem commit~~ **Resolvido.**
4. Loop de aprendizado inerte (`aprendizados.registrar()` nunca é chamado; falta coletar métricas da Insights API).
5. Dividir `main.py` (≈1.700 linhas) em `APIRouter`s e `pipeline.py` (≈2.100) em submódulos, só com a suíte verde.
6. Arquivos obsoletos aguardando autorização para apagar: veja a seção 4 de `docs/REVISAO_2026-10-22.md`.
7. Saída estruturada por JSON schema nos agentes e crítico com rubrica objetiva **já feitos**; falta a memória de voz do perfil.
8. `context/meu_contexto.md` traz uma frase de fecho literal que o Qwen copia (veja `docs/RESULTADOS.md`); aguarda decisão do Emerson.
