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
| `n8n` | n8nio/n8n | 5678 | Orquestrador |
| `ollama` | ollama/ollama | 11434 | LLM local (GPU via NVIDIA runtime se houver) |
| `render` | Browserless ou serviço Playwright próprio | 3000 | Recebe HTML, devolve JPEG |
| `extractor` | Python + trafilatura (pequeno) | 8000 | URL → texto limpo da matéria |
| `cloudflared` | cloudflare/cloudflared | — | Só se escolher Tunnel |

Decisão em aberto: n8n (visual, rápido de montar, mas workflow em JSON é ruim de versionar) vs. serviço Python próprio (FastAPI + scheduler, mais fácil de testar e versionar). **Recomendação: n8n na v1** para chegar rápido; exportar o workflow JSON para `workflows/` a cada mudança.

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

## Segredos

`.env` fora do git: `IG_USER_ID`, `IG_ACCESS_TOKEN`, `META_APP_ID`, `META_APP_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, credenciais R2. Fornecer `.env.example` sem valores.

## Não-objetivos da v1

Reels/vídeo, DM automática, múltiplas contas, publicação sem aprovação, geração de imagem por difusão.
