# 02 · Pipeline

## Gatilhos

1. **Automático:** cron lê feeds RSS configurados ou temas de pesquisa em alta e monta a pauta.
2. **Manual no Telegram:**
   - Ideia livre ou pedido em linguagem natural (ex.: *"Faz um story sobre a alta das taxas de frete"*).
   - Comandos estruturados: `/feed`, `/story`, `/carrossel`, `/reels`, `/blowup <link>`, `/planejar`, `/badge`.
   - Envio de mídia direta (fotos, vídeos, amostras de áudio para clonagem/narração).

Deduplicação: hash/URL de cada notícia processada na tabela `posts` do SQLite, única por perfil + URL/ideia.

## Etapas do Pipeline

```
[1. Captura / Recepção] ➔ [2. Extração] ➔ [3. Estúdio Criativo] ➔ [4. Render 6 Layouts]
                                                    │
[8. Publicação Multiplataforma] ◄─ [7. Aprovação] ◄─┴─ [5. Crítico Visual] ◄───┐
                                                            │ (se score < 8)    │
                                                            └─ 1 ciclo revisão ─┘
```

1. **Captura / Recepção:** intercepta URL, texto da ideia, mídia enviada ou notícia RSS.
2. **Extração:** `trafilatura` extrai texto limpo de links e notícias; `whisper` transcreve vídeos/áudios.
3. **Estúdio Criativo Multiagente (`agentes/estudio.py`):**
   - **Estrategista (`estrategista.py`):** Extrai fatos verificáveis puros, define formato e ângulo.
   - **Redator (`caption_writer.py`):** Hook inicial < 125 chars, blocos estruturados e 1 CTA estratégico.
   - **Humanizador (`humanizer.py`):** Elimina vícios de IA, termos clichês e tempestades de emojis.
   - **Diretor de Arte (`diretor_arte.py`):** Seleciona 1 dos 6 layouts, paleta hex contextual e prompt de imagem.
   - **Imagem do Tema:** Busca imagem contextual no Higgsfield AI / Unsplash ou gera ilustrações VectorCraft.
4. **Render Dinâmico (`render.py`):** Playwright Chromium injeta os dados no layout escolhido (`impacto_foto`, `editorial`, `lista`, `dado`, `alerta`, `citacao`) em 1080×1350 (Feed) ou 1080×1920 (Story com safe zones).
5. **Crítico Visual (`critico.py`):** Inspeciona o card gerado via LLM com visão ou heurísticas objetivas (estouro de texto, legibilidade, contraste). Se a nota for < 8, aciona 1 ciclo de revisão automática com o Diretor de Arte.
6. **Aprovação Telegram:** Envia o preview do card em alta qualidade, a legenda proposta e botões interativos:
   - `[✅ Postar]` ➔ publica imediatamente.
   - `[🕒 Agendar]` ➔ agenda no próximo slot livre do perfil.
   - `[🎨 Mudar Estilo]` ➔ cicla dinamicamente entre os 6 layouts.
   - `[🔄 Refazer]` ➔ reexecuta o estúdio com nova temperatura.
   - `[🗑 Descartar]` ➔ descarta o post.
7. **Publicação Multiplataforma (`distribuicao.py`):** Publica simultaneamente no Instagram e nos canais ativos configurados (Threads, YouTube Shorts, LinkedIn, TikTok).
8. **Registro e Aprendizado:** Registra métricas e lições na tabela `aprendizados` para retroalimentação futura.

## Estados de um Post

`capturado → extraido → gerado_agente → aguardando_aprovacao → aprovado → publicando → publicado`
Saídas laterais: `descartado`, `falhou` (com detalhe do erro e retry).

## Requisitos de Qualidade e Anti-Alucinação

- **Fidelidade Factual Estrita:** O Estrategista opera exclusivamente sobre fatos verificados da notícia ou do pedido do autor; alucinações de temas não solicitados (ex.: vazamento de termos de LGPD em matérias de infraestrutura) são expressamente bloqueadas.
- **Humanização Natural:** Zero clichês como *"no mundo dinâmico de hoje"*, *"mergulhe fundo"* ou pontuações teatrais.
- **Prevenção de Estouro de Texto:** O Playwright valida overflow diretamente no DOM. Textos que ultrapassam limites de altura forçam encurtamento imediato.

