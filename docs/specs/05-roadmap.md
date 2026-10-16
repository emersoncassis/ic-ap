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

## Fase 5 · Extras (opcionais)
Carrossel; imagem de fundo com ComfyUI; Reels; métricas de alcance.

## Decisões já tomadas

- Hardware: RTX 5070 8 GB de VRAM + Core Ultra 7. LLM local ~7–8B, com provedor de nuvem configurável como reserva.
- Perfil: pessoal. Contexto vem do site pessoal (emerson.ysafe.com.br); rascunho em `context/meu_contexto.md`.
- Credenciais Meta: app, ID da conta e token já existem.

## Perguntas em aberto

1. Quanta RAM tem o notebook?
2. Colar 3 a 5 textos/legendas seus para o contexto.
3. O app Meta usa Instagram Login ou Facebook Login? O token é curto ou longo?
4. URL pública: R2 ou Cloudflare Tunnel?
5. Quais temas e feeds RSS de notícias?
6. Frequência: quantos posts por dia?
7. O PC fica ligado no horário de postagem?
