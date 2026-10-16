# 01 · Arquitetura

## Visão geral

```
RSS / link no Telegram
        │
        ▼
 [app] ── extrai texto (trafilatura) ──► [Ollama] ◄── meu_contexto.md
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

| Parte | Tecnologia | Porta | Função |
|---|---|---|---|
| `app` (único container) | Python (FastAPI) + SQLite + Playwright | 8000 (só local) | Painel web, agendador, pipeline, Telegram, publicação |
| servidor de imagens | Starlette, dentro do app | 127.0.0.1:8081 | Serve apenas `data/public/` (JPEGs temporários) |
| túnel | `cloudflared` iniciado pelo app com o token do painel | — | hostname público → `http://localhost:8081` |
| LLM | **fora do app** (LM Studio, Ollama, Jan, API...) | — | Configurado na aba LLM |

Tudo exceto o túnel fica em `127.0.0.1`. O que sai para a internet é só a pasta de JPEGs, com nome aleatório (uuid), apagada após o publish. O PC fica ligado, então o túnel nomeado fica sempre de pé.

Decisão: app Python único no lugar do n8n (ver spec 06). Os cards ficam privados em `data/cards`; só são copiados para `data/public` durante o publish.

## Estrutura do repositório

```
ic-ap/
├── README.md
├── docs/specs/
├── docker-compose.yml
├── context/
│   └── meu_contexto.md       # ver spec 04
├── templates/
│   └── reacao.html           # Tailwind/CSS, variáveis {{manchete}} {{reacao}} {{fonte}}
├── services/
│   └── app/                  # painel, pipeline, testes
└── data/                     # gitignored: jpgs gerados, logs, histórico
```

## Provedor de LLM (configurável)

Conexão de LLM configurada no painel (tipo openai-compatível, ollama, gemini ou anthropic; modelos detectados automaticamente). A etapa de reação chama uma interface única (entrada: contexto + texto da notícia; saída: o JSON da spec 02). Padrão `ollama`. Cloud é reserva para quando o modelo local não segurar o tom ou o JSON. Só o texto da notícia e o contexto público vão para a nuvem.

## Segredos

Sem `.env`: tudo é configurado no painel e guardado criptografado no SQLite; a chave é gerada em `/data/secret.key` (volume Docker).

## Não-objetivos da v1

Reels/vídeo, DM automática, múltiplas contas, publicação sem aprovação, geração de imagem por difusão.
