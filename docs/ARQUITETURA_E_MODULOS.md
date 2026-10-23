# ic-ap · Arquitetura e mapa de módulos

Este documento descreve **o código como ele está hoje** (gerado a partir da leitura do repositório em 22/10/2026).
As especificações de intenção/produto estão em `docs/specs/`; aqui está o mapa técnico para quem vai mexer no código.

## 1. Visão em uma figura

```
 Telegram (bot)  ──┐                    ┌── Painel web (FastAPI + Jinja2, 127.0.0.1:8000)
 Feeds RSS       ──┼─►  pipeline.py ◄───┤     login por senha mestre, CSRF, sessão assinada
 Agenda (30 s)   ──┘        │           └── Escritório virtual (SPA pixel-art em /assets)
                            ▼
        ┌───────────── agentes/ (Estúdio Criativo) ─────────────┐
        │ Estrategista → Redator → Humanizer → Diretor de Arte  │
        │              → render (Chromium) → Crítico Visual     │
        └───────────────────────────────────────────────────────┘
                            │ cards/vídeos em /data/cards
                            ▼
        aprovação (Telegram/painel) ──► distribuicao.py ──► Instagram · Threads · Shorts · LinkedIn · TikTok
                                          └─ imagens públicas temporárias: publico.py (:8081) ◄── túnel Cloudflare
```

Um único container (`app`) roda tudo. Dois serviços opcionais: `voz` (GPU NVIDIA: Whisper + clonagem de voz) e `llm` (Ollama).
Toda configuração do usuário vive no SQLite e é editada pelo painel — **não existe `.env`**; as variáveis de ambiente
(`config.py`) são só caminhos e endereços de serviços (usadas principalmente pelos testes).

## 2. Núcleo (`services/app/app/`)

| Módulo | Responsabilidade |
|---|---|
| `main.py` | Todas as rotas do painel (≈80), ciclo de vida (`lifespan`), sessão, CSRF, bloqueio de POST de outra origem |
| `pipeline.py` | Fluxo de um post: capturar → extrair → reagir → renderizar → aprovar → publicar; esteira de fotos/vídeos do Telegram; agendamento; carrossel; adaptação feed↔story |
| `db.py` | SQLite com lock global (uso pessoal, baixo volume). Esquema + migrações leves. `init()` é idempotente (WAL + `busy_timeout`) |
| `crypto.py` | Fernet para tokens em repouso (chave em `data/secret.key`, modo 600) e `scrypt` para a senha mestre |
| `settings.py` | Configuração global editável (fuso, conexões de voz/imagem etc.); segredos criptografados |
| `config.py` | Caminhos (`DATA_DIR`, templates, skills) e endereços de APIs de terceiros |
| `tarefas.py` | `disparar(coro)`: tarefas em segundo plano com referência forte e log de exceção |
| `scheduler.py` | A cada `SCHEDULER_TICK` (30 s) publica agendados vencidos e dispara a geração dos horários do perfil |
| `supervisor.py` | Mantém o bot do Telegram e o túnel Cloudflare alinhados com o que está salvo no painel |
| `tunnel.py` / `publico.py` | Processo `cloudflared` e servidor estático que só expõe `data/public/` |
| `telegram.py` | Long-polling do bot, botões inline, envio de cards |
| `ig.py` | Instagram Graph API (publicar imagem/carrossel/reel/story, checar conta) |
| `distribuicao.py` | Motor de publicação multiplataforma (Threads, Shorts, LinkedIn, TikTok) e registro em `publicacoes_canais` |
| `llm.py` / `llm_local.py` | Conexões de LLM (Ollama, LM Studio, OpenAI-compat., Gemini, Claude, OpenRouter) e JSON estruturado; instalação de modelos locais |
| `hardware.py` | Detecta GPU/NPU/CPU e sugere roteamento de IA por módulo (economia de tokens) |
| `render.py` | HTML → JPEG/PNG 1080×1350 (feed) ou 1080×1920 (story) via Playwright/Chromium |
| `marca.py` | Kit de marca por perfil (cores, fonte, logotipo) aplicado aos cards |
| `banco.py` | Fontes de imagem para citações/memes/fundos: Higgsfield → Unsplash → plano B aberto (`bancos_abertos`, desligável em Conexões) |
| `midia.py` | ffmpeg: ajuste de formato, trilha, corte de silêncio, legenda animada |
| `voz.py` / `vozes.py` | Cliente Whisper/TTS (API compatível OpenAI) e biblioteca de vozes para clonagem |
| `meta_ai.py` | Pesquisa/técnica *Blow Up* no Instagram via navegador (Playwright) |
| `wizard.py` | Onboarding: contexto/tom do perfil por entrevista ou relatório Meta AI; pacotes de feeds |
| `aprendizados.py` | Loop de aprendizado (métricas → lições por perfil) |
| `escritorio.py` | Estado do "escritório virtual" e diagnóstico de gargalos do fluxo |
| `vectorcraft.py` | Selos/overlays vetoriais (SVG → PNG) |
| `reset_senha.py` | CLI de recuperação de senha |

### Agentes (`agentes/`)

`orquestrador.py` identifica a intenção da mensagem (legenda, carrossel, reels, repurpose, humanização…) e aciona os
especialistas. As instruções de cada agente vivem em `skills/<nome>/SKILL.md` (fonte única da verdade, recarregadas por `mtime`).

| Agente | Papel |
|---|---|
| `estrategista`, `diretor_arte`, `critico` | Etapas do Estúdio Criativo (fatos → layout/paleta → nota 0–10 com 1 ciclo de refino) |
| `caption_writer`, `humanizer`, `hashtag_strategist`, `hook_extractor` | Texto |
| `carousel_planner`, `content_planner`, `repurposer`, `audience_insights`, `profile_optimizer` | Planejamento |
| `vector_art` | Selos e overlays vetoriais |
| `estudio` | Orquestra o pipeline completo de criação |

## 3. Banco de dados (SQLite em `/data/app.db`)

`perfis` · `feeds` · `posts` (estado, formato, `agendado_para`, mídia) · `eventos` (log) · `settings` (chave/valor; inclui
marcas `slot:*` do agendador) · `conversas` (histórico do Telegram) · `llm_conexoes` · `canais_distribuicao` ·
`publicacoes_canais` · `aprendizados`.

Estados do post: `rascunho` / `extraido` (em geração) → `aguardando_aprovacao` → `agendado` → `publicando` → `publicado` (ou `falhou` / `descartado`).
A transição é protegida por `pipeline._claim` (UPDATE condicional), o que impede publicar duas vezes ao clicar duas vezes.

## 4. Segurança (resumo)

- Painel escuta só em `127.0.0.1:8000`; apenas a pasta `data/public/` sai pelo túnel.
- Senha mestre com `scrypt`; sessão assinada (`SameSite=Lax`, 7 dias); CSRF em todo formulário; POST com cabeçalho `Origin` de outro site é recusado (cobre as rotas JSON).
- Limite de 10 tentativas de login por 5 min por IP **(vale também para localhost)**.
- Tokens (Instagram, LLM, Telegram, canais) criptografados com Fernet; a chave (`data/secret.key`) deve entrar no backup junto com o banco.
- Recuperação de senha **somente** pela linha de comando: `docker compose exec app python -m app.reset_senha`.

## 5. Rotas do painel (por área)

Autenticação `/setup /login /logout` · Perfis `/perfis…` (marca, logo, feeds, Meta AI) · Wizard `/wizard…` · Fila `/`, `/gerar`,
`/posts/{id}/{acao}` · Pauta `/pauta…` · Agenda `/agenda` · Agentes `/agentes`, `/api/agentes/executar` · Escritório `/escritorio`,
`/api/escritorio/*` · LLM `/llm…` · Conexões `/conexoes`, `/config/{secao}` · Voz `/voz…` · Músicas `/musicas…` ·
Histórico `/historico` · Saúde `/saude` · Mídia privada `/cards/{nome}`.

## 6. Serviço de voz (`services/voz/`)

API compatível com OpenAI: `POST /v1/audio/transcriptions` (faster-whisper), `POST /v1/audio/speech` (Chatterbox ou Qwen3-TTS via
`ENGINE`), `GET /health`, `POST /descarregar`. Sobe com `docker compose --profile gpu up -d --build`.

## 7. Pontos de atenção conhecidos

- `pipeline.py` (~2.100 linhas) e `main.py` (~1.700) concentram responsabilidades; o próximo passo natural de refatoração é dividir
  `main.py` em `APIRouter`s por área (`rotas/perfis.py`, `rotas/llm.py`, `rotas/voz.py`…) e `pipeline.py` em `geracao`, `midia_telegram`, `agenda`, `publicacao`.
- Os bundles de `app/web/assets/index-*.js` são build de uma SPA cujo código-fonte **não está neste repositório**; mantenha o fonte
  em outro lugar (ou traga-o para cá) antes de precisar alterar o escritório.
- `old/` guarda código legado (backend antigo e VectorCraft em Rust) fora do build do Docker.
