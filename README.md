# ic-ap

Esteira local de conteúdo para Instagram: lê notícias, reage com a minha voz e contexto usando um LLM (local ou API, à sua escolha), renderiza o post (HTML → JPEG), manda para aprovação no Telegram e publica pela Instagram Graph API oficial.

> Status: app Python com painel web, pipeline completo (RSS → extração → LLM → card → aprovação → publicação), Telegram e agendador. Toda a configuração é feita no painel web (sem `.env`). **Testado ponta a ponta com serviços simulados (31 testes), ainda não contra a Meta, o Telegram, um LLM real e o Docker.**

![exemplo do card](docs/exemplo-card.jpg)

## Subir

```bash
docker compose up -d --build
```

Abra http://localhost:8000. No primeiro acesso o app pede para **criar a senha** (e gera sozinho a chave de criptografia em `data/secret.key`; faça backup da pasta `data/`). Depois, tudo no painel:

1. **LLM:** rode seu LLM fora do app (LM Studio, Ollama, Jan, Gemini, Claude...). Informe tipo e endereço, clique **Detectar modelos**, escolha um e **Aplicar e testar**. Do container, use `host.docker.internal` no lugar de `localhost`.
2. **Conexões e acesso:** token do túnel Cloudflare (`docs/cloudflare-tunnel.md`), URL pública, token do bot do Telegram, fuso horário.
3. **Perfis:** dados do perfil, Telegram chat id, horários, contexto, conexão de LLM e o assistente de token da Meta. O perfil do Emerson nasce **desligado**; ligue só depois de testar tudo em **Conexões**.

Esqueceu a senha: `docker compose exec app python -m app.reset_senha`.

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
