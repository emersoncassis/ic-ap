# ic-ap

Esteira local de conteúdo para Instagram: lê notícias, reage com a minha voz e contexto usando um LLM local, renderiza o post (HTML → JPEG), manda para aprovação no Telegram e publica pela Instagram Graph API oficial.

> Status: specs prontas; serviço `tools` (extrair + renderizar card) implementado e testado; compose pronto. `/publish` implementado e testado contra um Graph API simulado (não contra a Meta real). Falta o workflow n8n e a ligação com o Telegram.

![exemplo do card](docs/exemplo-card.jpg)

## Subir (quando o `.env` estiver preenchido)

```bash
cp .env.example .env      # preencher
docker compose up -d --build
docker exec -it $(docker compose ps -q ollama) ollama pull qwen2.5:7b-instruct
curl localhost:8000/health
```

Pré-requisitos: Docker Desktop com WSL2 e GPU NVIDIA habilitada; um túnel nomeado na Cloudflare apontando para `http://public:80`.

## Specs

| Doc | Assunto |
|---|---|
| [00-viabilidade](docs/specs/00-viabilidade.md) | Veredito: o que é local, o que não é, correções ao plano original |
| [01-arquitetura](docs/specs/01-arquitetura.md) | Componentes, fluxo, estrutura de pastas, docker-compose alvo |
| [02-pipeline](docs/specs/02-pipeline.md) | Passo a passo do workflow, contrato JSON do LLM, estados do post |
| [03-instagram-publicacao](docs/specs/03-instagram-publicacao.md) | Auth, tokens, URL pública, container → publish, limites |
| [04-contexto-pessoal](docs/specs/04-contexto-pessoal.md) | Template do `meu_contexto.md` e regras de tom |
| [05-roadmap](docs/specs/05-roadmap.md) | Fases, critérios de aceite, perguntas em aberto |
