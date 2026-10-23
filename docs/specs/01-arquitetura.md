# 01 · Arquitetura

## Visão geral

```
Pedido no Telegram / RSS / Link Externo
        │
        ▼
   [Orquestrador] ── carrega contexto + skills (/srv/skills)
        │
        ▼
[Estúdio Criativo Multiagente]
  1. Estrategista (fatos verificados, enquadramento)
  2. Redator + Humanizer (manchete, blocos, 1 CTA)
  3. Diretor de Arte (layout, paleta hex, destaques, prompt)
  4. Imagem do Tema (Higgsfield AI / Unsplash / VectorCraft)
        │
        ▼
 [render: Playwright Chromium 1080×1350 ou 1080×1920]
  6 Layouts: impacto_foto, editorial, lista, dado, alerta, citação
        │
        ▼
 [Crítico Visual (Multimodal / Heurístico)]
  Nota >= 8 (ou 1 ciclo de revisão com o Diretor de Arte)
        │
        ▼
[Telegram: Postar / Refazer / Mudar Estilo / Agendar]
        │ aprovado
        ▼
 [Cloudflare Tunnel: URL pública temporária]
        │
        ├────────────────────────┬─────────────────────────┐
        ▼                        ▼                         ▼
 [Instagram Graph API]     [Threads API]             [YouTube Shorts]
        │                        │                         │
        ▼                        ▼                         ▼
 [LinkedIn API]            [TikTok Content API]     (Publicação Simultânea)
```

## Componentes

| Parte | Tecnologia | Porta | Função |
|---|---|---|---|
| `app` (único container) | Python (FastAPI) + SQLite + Playwright | 8000 (só local) | Painel web, agendador, pipeline, Telegram, publicação |
| `skills` (/srv/skills) | Markdown + YAML frontmatter | — | Fonte única da verdade das instruções dos agentes com auto-reload |
| `estudio` | Pipeline multiagente Python assíncrono | — | Estrategista ➔ Redator ➔ Humanizador ➔ Diretor de Arte ➔ Crítico |
| `templates` (/srv/card-templates) | Jinja2 + HTML5 + CSS Variables | — | 6 layouts responsivos (Feed 4:5 e Story 9:16) sem textos hardcoded |
| servidor de imagens | Starlette, dentro do app | 127.0.0.1:8081 | Serve apenas `data/public/` (JPEGs temporários) |
| túnel | `cloudflared` iniciado pelo app com token do painel | — | hostname público → `http://localhost:8081` |
| LLM | Local ou Nuvem (Ollama, LM Studio, Gemini, Claude, OpenAI) | — | Raciocínio, escrita e inspeção de visão do Crítico |
| distribuição | Motor próprio multiplataforma Python | — | Publicação direta no Instagram, Threads, Shorts, LinkedIn e TikTok |

Tudo exceto o túnel fica em `127.0.0.1`. O que sai para a internet é apenas a pasta temporária de JPEGs durante a chamada de publicação das APIs parceiras, sendo limpa imediatamente após o término.

## Estrutura do repositório

```
ic-ap/
├── README.md
├── docs/specs/               # Especificações arquiteturais e de agentes
├── docker-compose.yml
├── context/
│   └── meu_contexto.md       # Perfil inicial e regras de voz do autor
├── skills/                   # Fonte única de verdade das diretrizes agênticas
│   ├── estrategista/SKILL.md
│   ├── diretor-de-arte/SKILL.md
│   ├── critico-visual/SKILL.md
│   ├── caption-writer/SKILL.md
│   └── humanizer/SKILL.md
├── templates/
│   └── layouts/              # 6 layouts dinâmicos em CSS puro
│       ├── impacto_foto.html
│       ├── editorial.html
│       ├── lista.html
│       ├── dado.html
│       ├── alerta.html
│       └── citacao.html
├── services/
│   └── app/                  # Painel web, agentes, pipeline, renderizador, testes
└── data/                     # Volume persistente (banco SQLite, cards privados, logs)
```

## Provedores de LLM e Visão

Conexão de LLM configurada no painel web (OpenAI-compatível, Ollama, Gemini, OpenRouter ou Anthropic). O sistema detecta automaticamente se o modelo possui suporte multimodal (visão) para que o Crítico Visual inspecione o card renderizado de fato; se o modelo for exclusivamente textual, o Crítico aciona verificações heurísticas objetivas (estouro de texto, contraste e limites de densidade).

## Segredos

Sem `.env`: tudo é configurado no painel web e guardado criptografado no SQLite; a chave mestra de criptografia é gerada em `/data/secret.key` (volume Docker).

