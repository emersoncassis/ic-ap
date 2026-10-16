# 05 · Roadmap

## Fase 0 · Fundação
- Docker Compose com `ollama`, `n8n`, `render`, `extractor`.
- Teste de saúde de cada serviço.
- **Aceite:** `docker compose up` sobe tudo; Ollama responde um JSON válido.

## Fase 1 · Geração sem publicar
- Template HTML do card de reação.
- Fluxo: link → texto → JSON → JPEG.
- **Aceite:** 10 notícias reais geram 10 JPEGs legíveis, sem texto cortado, JSON válido em ≥ 9.

## Fase 2 · Aprovação
- Bot Telegram com Postar / Refazer / Descartar.
- **Aceite:** Refazer gera versão diferente; Descartar registra e encerra.

## Fase 3 · Publicação
- Upload do JPEG (R2 ou Tunnel), container, publish, limpeza.
- Refresh automático do token.
- **Aceite:** um post real aparece no feed com legenda e crédito; falhas geram aviso no Telegram.

## Fase 4 · Automação diária
- Cron + RSS + deduplicação.
- **Aceite:** 7 dias seguidos sem intervenção além do "Postar".

## Fase 5 · Dashboard e multi-perfil
- Ver spec 06. Depende de confirmar a troca do n8n por um app Python único.
- **Aceite:** criar o perfil do Iago pelo painel e gerar um post de teste.

## Fase 6 · Extras (opcionais)
Carrossel; imagem de fundo com ComfyUI; Reels; métricas de alcance.

## Decisões já tomadas

- Hardware: RTX 5070 8 GB de VRAM + Core Ultra 7. LLM local ~7–8B, com provedor de nuvem configurável como reserva.
- Perfil: pessoal. Contexto vem do site pessoal (emerson.ysafe.com.br); rascunho em `context/meu_contexto.md`.
- URL pública: Cloudflare Tunnel, máquina sempre ligada.
- RAM: 32 GB (DDR5).
- Feeds: tecnologia, empresa/negócios, IA e saúde tech (`config/feeds.yml`, a validar).
- Meta: Login do Facebook (`instagram_basic`, `instagram_content_publish`), conta ligada a uma Página.
- Credenciais Meta: app, ID da conta e token já existem.

## Perguntas em aberto

1. Colar 3 a 5 textos/legendas seus para o contexto.
2. Gerar o token da Página com `scripts/meta_token.py` (ver spec 03) e preencher o `.env`.
3. Qual subdomínio usar para as imagens (ex.: `img.seudominio.com`)? Ver `docs/cloudflare-tunnel.md`.
4. Posts por dia (padrão no `.env.example`: 2).
5. Iago e Igor serão adicionados como função no app da Meta? Cada um terá seu Telegram e contexto?
6. Confirmar a troca do n8n por app Python único (spec 06).
