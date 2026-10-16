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

## Perguntas em aberto

1. Qual GPU e quanta RAM/VRAM tem o PC que vai rodar isso? Define o modelo.
2. O PC fica ligado no horário de postagem?
3. Qual perfil do Instagram será usado (pessoal, IC TEAM)? Já é Profissional?
4. O app Meta atual usa Instagram Login ou Facebook Login?
5. URL pública: R2 ou Cloudflare Tunnel?
6. Quais feeds RSS de notícias, e em quais temas?
7. Frequência: quantos posts por dia?
