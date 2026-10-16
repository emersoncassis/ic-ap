# 01 · Arquitetura

## Visão geral

```
RSS / link no Telegram
        │
        ▼
 [n8n] ── extrai texto (trafilatura) ──► [Ollama] ◄── meu_contexto.md
        │                                   │ JSON
        │                                   ▼
        │                         [render: HTML → JPEG 1080×1350]
        │                                   │
        ▼                                   ▼
   [Telegram: Aprovar / Refazer / Descartar]
        │ aprovado
        ▼
 [R2 ou Tunnel: URL pública] ──► [Instagram Graph API] ──► post publicado
```

## Componentes

| Serviço | Imagem/tecnologia | Porta | Função |
|---|---|---|---|
| `n8n` | n8nio/n8n | 5678 (local) | Orquestrador |
| `ollama` | ollama/ollama, GPU NVIDIA | 11434 (local) | LLM local |
| `tools` | Python (FastAPI) + trafilatura + Playwright | 8000 (local) | `/extract` URL→texto, `/render` JSON→JPEG, `DELETE /public/{arquivo}` |
| `public` | nginx | só via túnel | Serve apenas `data/public/` (JPEGs temporários) |
| `cloudflared` | cloudflare/cloudflared | — | Túnel nomeado: hostname público → `http://public:80` |

Tudo exceto o túnel fica em `127.0.0.1`. O que sai para a internet é só a pasta de JPEGs, com nome aleatório (uuid), apagada após o publish. O PC fica ligado, então o túnel nomeado fica sempre de pé.

Decisão tomada: n8n como orquestrador, com a lógica pesada (extrair, renderizar) no serviço `tools`, que é testável sem n8n. Alternativa descartada por ora: tudo em Python. (n8n (visual, rápido de montar, mas workflow em JSON é ruim de versionar) vs. serviço Python próprio (FastAPI + scheduler, mais fácil de testar e versionar). **Recomendação: n8n na v1** para chegar rápido; exportar o workflow JSON para `workflows/` a cada mudança.)

## Estrutura do repositório

```
ic-ap/
├── README.md
├── docs/specs/
├── docker-compose.yml
├── .env.example              # tokens, IDs, nunca commitar .env
├── context/
│   └── meu_contexto.md       # ver spec 04
├── templates/
│   └── reacao.html           # Tailwind/CSS, variáveis {{manchete}} {{reacao}} {{fonte}}
├── services/
│   └── extractor/            # URL → texto
├── workflows/
│   └── post-reacao.json      # export do n8n
└── data/                     # gitignored: jpgs gerados, logs, histórico
```

## Provedor de LLM (configurável)

`LLM_PROVIDER=ollama|gemini|anthropic` no `.env`. A etapa de reação chama uma interface única (entrada: contexto + texto da notícia; saída: o JSON da spec 02). Padrão `ollama`. Cloud é reserva para quando o modelo local não segurar o tom ou o JSON. Só o texto da notícia e o contexto público vão para a nuvem.

## Segredos

`.env` fora do git: `LLM_PROVIDER`, `GEMINI_API_KEY`/`ANTHROPIC_API_KEY` (só se usar nuvem), `IG_USER_ID`, `IG_ACCESS_TOKEN`, `META_APP_ID`, `META_APP_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, credenciais R2. Fornecer `.env.example` sem valores.

## Não-objetivos da v1

Reels/vídeo, DM automática, múltiplas contas, publicação sem aprovação, geração de imagem por difusão.
