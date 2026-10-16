# ic-ap

Esteira local de conteúdo para Instagram: lê notícias, reage com a minha voz e contexto usando um LLM local, renderiza o post (HTML → JPEG), manda para aprovação no Telegram e publica pela Instagram Graph API oficial.

> Status: app Python com painel web, pipeline completo (RSS → extração → LLM → card → aprovação → publicação), Telegram e agendador. **Testado ponta a ponta com serviços simulados (16 testes), ainda não contra a Meta, o Telegram e o Ollama reais.**

![exemplo do card](docs/exemplo-card.jpg)

## Subir

```bash
cp .env.example .env      # preencher (APP_SECRET_KEY, ADMIN_PASSWORD, túnel, tokens)
docker compose up -d --build
docker compose exec ollama ollama pull qwen2.5:7b-instruct
```

Abra http://localhost:8000, entre com a senha, vá em **Conexões** e teste Meta, Ollama, Telegram e URL pública. Só então ligue o perfil em **Perfis**. O perfil do Emerson nasce **desligado** de propósito.

Pré-requisitos: Docker Desktop com WSL2 e GPU NVIDIA; túnel nomeado na Cloudflare apontando para `http://public:80` (veja `docs/cloudflare-tunnel.md`).

## Testes

```bash
cd services/app && pip install -r requirements-dev.txt && python -m pytest
```

## Specs

| Doc | Assunto |
|---|---|
| [00-viabilidade](docs/specs/00-viabilidade.md) | Veredito: o que é local, o que não é, correções ao plano original |
| [01-arquitetura](docs/specs/01-arquitetura.md) | Componentes, fluxo, estrutura de pastas, docker-compose alvo |
| [02-pipeline](docs/specs/02-pipeline.md) | Passo a passo do workflow, contrato JSON do LLM, estados do post |
| [03-instagram-publicacao](docs/specs/03-instagram-publicacao.md) | Auth, tokens, URL pública, container → publish, limites |
| [04-contexto-pessoal](docs/specs/04-contexto-pessoal.md) | Template do `meu_contexto.md` e regras de tom |
| [05-roadmap](docs/specs/05-roadmap.md) | Fases, critérios de aceite, perguntas em aberto |
| [06-dashboard-multiperfil](docs/specs/06-dashboard-multiperfil.md) | Painel web e vários perfis (Emerson, Iago, Igor) |
| [cloudflare-tunnel](docs/cloudflare-tunnel.md) | Passo a passo do túnel para a URL pública das imagens |
