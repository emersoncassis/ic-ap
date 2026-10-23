# 08 · Agentes Inteligentes e Especialistas de Conteúdo

## 1. Visão Geral e Arquitetura

Esta especificação define a arquitetura multiagente do **ic-ap**, transformando a esteira em um estúdio completo com **1 Agente Orquestrador Central**, **12 Agentes Especialistas** e o **Estúdio Criativo Multiagente** baseado em **Skills dinâmicas** como fonte única da verdade, complementados pelos motores de **Mídia, Áudio, Renderização e Distribuição Soberana**.

```
                      ┌────────────────────────────────────────┐
                      │          Usuário no Telegram           │
                      │  (Texto, Link, Imagem, Vídeo, Áudio)   │
                      └──────────────────┬─────────────────────┘
                                         │
                                         ▼
                      ┌────────────────────────────────────────┐
                      │          AGENTE ORQUESTRADOR           │
                      │     (Roteador de Intenções & Chat)     │
                      └──────────────────┬─────────────────────┘
                                         │
       ┌───────────────────┬─────────────┴───────────┬───────────────────┐
       ▼                   ▼                         ▼                   ▼
┌──────────────┐   ┌──────────────┐          ┌──────────────┐    ┌──────────────┐
│Content       │   │Profile       │          │Hook          │    │Audience      │
│Planner       │   │Optimizer     │          │Extractor     │    │Insights      │
└──────┬───────┘   └──────────────┘          └──────┬───────┘    └──────────────┘
       │                                            │
       ▼                                            ▼
┌──────────────┐   ┌──────────────┐          ┌──────────────────────────────────┐
│Repurposer    │   │Carousel      │          │ ESTÚDIO CRIATIVO AGÊNTICO        │
│              │   │Planner       │          │ (Estrategista ➔ Redator ➔        │
└──────┬───────┘   └──────┬───────┘          │  Humanizer ➔ Diretor de Arte ➔   │
       │                  │                  │  Render ➔ Crítico Visual)        │
       └──────────────────┴────────────┬─────┴──────────────────┬───────────────┘
                                       │                        │
                                       ▼                        ▼
                       ┌──────────────────────────────┐ ┌──────────────┐
                       │  SKILLS NO DISCO (/skills)   │ │VECTORCRAFT   │
                       │ (Fonte única da verdade)     │ │Badges / SVGs │
                       └───────────────┬──────────────┘ └───────┬──────┘
                                       │                        │
                                       └───────────┬────────────┘
                                                   ▼
                                   ┌──────────────────────────────┐
                                   │  GESTÃO DE MÍDIA & RENDER    │
                                   │ (6 Layouts: Foto, Editorial, │
                                   │  Lista, Dado, Alerta, Citação│
                                   │  ffmpeg, Voz Chatterbox/Qwen)│
                                   └───────────────┬──────────────┘
                                                   │
                                                   ▼
                                   ┌──────────────────────────────┐
                                   │     APROVAÇÃO TELEGRAM       │
                                   │ [Postar] [Refazer] [Mudar    │
                                   │  Estilo] [Agendar]           │
                                   └───────────────┬──────────────┘
                                                   │
                                                   ▼
                                   ┌──────────────────────────────┐
                                   │  DISTRIBUIÇÃO MULTIPLATAFORMA│
                                   │ (Instagram, Threads, Shorts, │
                                   │  LinkedIn, TikTok)           │
                                   └──────────────────────────────┘
```

---

## 2. Injeção de Contexto do Perfil (`meu_contexto.md`)

Todos os agentes operam com **isolamento por perfil** e **contexto dinâmico**. A cada invocação de um especialista, o Orquestrador monta o *System Prompt* injetando:
1. `contexto_md`: Quem é o autor, o que acredita, o que critica, seu nicho e tom de voz (definido em [04-contexto-pessoal](04-contexto-pessoal.md)).
2. `palavras_chave` e `horarios`: Temas centrais e janelas de postagem configuradas no painel.
3. Exemplos reais de posts anteriores do perfil (padrão de fraseado e assinatura).
4. Diretrizes culturais do **Português do Brasil (2026)**.

---

## 3. O Agente Orquestrador (Telegram Master Controller)

O Orquestrador é a entidade com quem o usuário conversa diretamente pelo bot do Telegram. Ele é responsável por:
- **Reconhecimento de Intenção (Intent Routing):** Identificar se a mensagem é um bate-papo, um comando explícito (`/planejar`, `/otimizar`, `/repurposar`), um link externo, um texto bruto ou uma mídia.
- **Delegação Especializada:** Acionar o especialista correto ou encadear múltiplos especialistas (exemplo: `Repurposer` → `Carousel Planner` → `Caption Writer` → `Hashtag Strategist` → `Humanizer` → `Render`).
- **Feedback Interativo:** Responder via Telegram de forma concisa, utilizando botões inline (`InlineKeyboardMarkup`) para escolhas rápidas.
- **Controle de Estado:** Persistir a conversa por perfil e chat ID no SQLite, permitindo iterações como *"gostei do slide 3, mas mude o hook do slide 1"*.

---

## 4. Catálogo dos 9 Agentes Especialistas

### 4.1. Caption Writer (Redator de Legendas 2026)
- **Função:** Redige legendas nativas de alta retenção no Instagram.
- **Regras 2026:**
  - **Hook inquebrável:** Os primeiros 125 caracteres (antes do botão *"mais..."*) contêm um gancho irresistível.
  - **Corpo escaneável:** Parágrafos curtos (1-3 linhas), quebras de linha limpas, sem paredes de texto.
  - **Um único CTA:** Chamada clara e única alinhada ao objetivo configurado: **Salvamentos** (ex.: *"Salve para consultar antes da reunião"*), **Compartilhamentos** (ex.: *"Mande para quem precisa ver isso hoje"*), **Comentários** (pergunta pontual que gera debate) ou **Seguidores** (promessa de valor contínuo).
  - **Voz do Autor:** Respeita rigorosamente a personalidade do `meu_contexto.md`.

### 4.2. Carousel Planner (Planejador de Carrossel)
- **Função:** Estrutura carrosséis slide a slide (de 4 a 10 slides).
- **Estrutura:**
  - **Slide 1 (Capa):** Gancho visual e textual com loop aberto (*curiosity gap*).
  - **Slides 2 a 8/9 (Valor Front-Loaded):** Entrega a parte mais valiosa logo nos primeiros slides para reter a rolagem (*swipe rate*), sem enrolação.
  - **Último Slide (Payoff & CTA):** Resolução do loop, recompensa do aprendizado e chamada para salvar e seguir o perfil.
- **Integração:** Devolve os textos estruturados que o [render.py](file:///c:/Users/emers/Desktop/REPO/icap%20-%20teste/services/app/app/render.py) transforma em cards JPEG 1080×1350 via Playwright.

### 4.3. Hook Extractor (Engenheiro Reverso de Ganchos Virais)
- **Função:** Analisa o texto, roteiro ou transcrição de qualquer Reel ou carrossel viral e mapeia o gancho para uma das 10 fórmulas comprovadas do Instagram:
  1. *Contraintuitivo / Choque de Paradigma* ("Pare de fazer X se você quer Y").
  2. *Erro Silencioso* ("O erro que 90% das pessoas cometem sem perceber").
  3. *Segredo / Curadoria* ("As 3 ferramentas que ninguém te conta").
  4. *História / Jornada* ("Como eu saí do ponto A para o B em X meses").
  5. *Comparação / Antes e Depois* ("Fazer X sozinho vs. com o método Y").
  6. *Pergunta Desafiadora* ("Você realmente sabe quanto custa X?").
  7. *Prova Inegável* ("Esse teste simples mostra se você...").
  8. *Risco Iminente / Alerta* ("Se você usa X, preste atenção nisso hoje").
  9. *Economia de Tempo / Atalho* ("Como economizar 10 horas semanais em...").
  10. *Identificação de Tribo* ("Se você também odeia ter que...").
- **Saída:** Devolve a estrutura desconstruída + template preenchível adaptado ao nicho do perfil.

### 4.4. Hashtag Strategist (Estrategista de Hashtags 2026)
- **Função:** Elimina o bloco arcaico de 30 hashtags genéricas e gera um conjunto estratégico de **3 a 5 hashtags indexáveis**:
  - 1-2 de **Nicho Ultraespecífico** (baixo volume, alta qualificação).
  - 1-2 de **Médio Volume** (relevantes para a categoria).
  - 1 de **Amplo Alcance** (âncora contextual).
- **Meta:** Indexação na busca semântica do algoritmo do Instagram (SEO de busca por palavras-chave).

### 4.5. Humanizer (Filtro Anti-IA e Auditor de Tom Natural PT-BR)
- **Função:** Remove qualquer traço que soe artificial ou gerado por máquina.
- **Detecção e Limpeza:**
  - **Vocabulário Proibido:** Bane termos clichês como *"no mundo dinâmico de hoje"*, *"mergulhe fundo"*, *"é crucial entender"*, *"game changer"*, *"divisor de águas"*, *"desvende"*, *"em suma"*, *"jornada transformadora"*.
  - **Estruturas Repetitivas:** Elimina pontes teatrais (*"Mas espere, tem mais..."*), triadas óbvias de adjetivos, estacatos de frases de uma palavra só e excesso de exclamações.
  - **Falsa Sinceridade & Tempestades de Emojis:** Limita emojis ao mínimo indispensável contextual (0 a 3 no post todo, nunca no início de cada linha como lista de supermercado).
  - **Controle de Travessão (Em-dash):** Limita travessões longos a no máximo 1 a cada 100 palavras.
  - **Modo `--audit`:** Gera um *score* de densidade de IA (0% a 100%) antes de liberar a publicação.

### 4.6. Content Planner (Planejador Semanal de Conteúdo)
- **Função:** Cria cronogramas semanais estratégicos (segunda a domingo).
- **Entregáveis:**
  - Mix balanceado: Reels, Carrosséis, Stories de aquecimento e posts de imagem/citação.
  - Horários sugeridos alinhados com o fuso e as preferências do perfil.
  - Ganchos específicos de cada dia.
  - Metas balanceadas (Posts de retenção/salvamento vs. Posts de atração/compartilhamento).

### 4.7. Repurposer (Reaproveitador Multiformato)
- **Função:** Converte posts de LinkedIn, artigos de blog, roteiros de YouTube ou threads do X/Twitter em publicações nativas do Instagram.
- **Ações:**
  - Remove vícios de outras redes (*"link nos comentários"*, *"RT por favor"*, *"arraste para cima"*, URLs expostas).
  - Reescreve o hook inicial nos primeiros 125 caracteres.
  - Adapta para carrossel (quando há estrutura de lista/passo a passo) ou post com imagem única + legenda densa.

### 4.8. Profile Optimizer (Otimizador de Perfil do Instagram)
- **Função:** Auditoria e reestruturação do perfil para conversão de visitantes em seguidores:
  - **Foto de perfil:** Enquadramento, contraste e leitura visual no mobile.
  - **Campo NOME (SEO):** Nome de exibição pesquisável incluindo palavras-chave estratégicas (ex.: *"Emerson | IA & Tech"*).
  - **Bio (150 caracteres):** Proposta de valor clara em 3 linhas: Quem ajudo + Como ajudo + Prova/CTA.
  - **Link da Bio:** Alinhamento estratégico com o objetivo atual.
  - **Destaques:** Sugestão de 4-5 capas, nomes curtos (sem reticências) e ordem lógica (Comece Aqui, Serviços/Quem Sou, Depoimentos/Cases, Bastidores).
  - **Grid dos Primeiros 9:** Análise visual de alternância de formatos e sugestão dos **3 posts fixados**.

### 4.9. Audience Insights (Inteligência de Audiência e Concorrentes)
- **Função:** Identificação de tendências e padrões do nicho.
- **Implementação Híbrida e Resiliente:**
  - **Modo Padrão (Sem Custo):** Consulta RSS, Google Trends, notícias de referência do setor e extração pública via `trafilatura`.
  - **Modo Avançado (Apify / Scraper API):** Quando o usuário configura uma chave opcional do Apify no painel web, o agente realiza:
    - Varredura de hashtags em alta no Brasil (likes, comentários médios, formatos dominantes).
    - Métricas públicas de perfis de referência (frequência, formatos que mais engajam).

### 4.10. Estrategista (Estrategista de Pauta & Fatos)
- **Skill:** `skills/estrategista/SKILL.md`
- **Função:** Analisa o tema/pedido do autor ou notícia capturada e define o enquadramento factual com fidelidade cirúrgica.
- **Regras:**
  - Extrai fatos verificáveis do pedido e proíbe terminantemente alucinações de dados ou de nichos não mencionados.
  - Define o formato ideal (feed vs. story), ângulo de abordagem, público-alvo e meta primária (autoridade, retenção, debate).

### 4.11. Diretor de Arte (Direção Visual & Identidade de Card)
- **Skill:** `skills/diretor-de-arte/SKILL.md`
- **Função:** Transforma a estratégia e o copy em decisões estéticas contextualizadas e dinâmicas.
- **Decisões:**
  - **Seleção de Layout:** Escolhe 1 entre os 6 layouts disponíveis (`impacto_foto`, `editorial`, `lista`, `dado`, `alerta`, `citacao`) de acordo com a natureza do conteúdo.
  - **Paleta Hexadecimal Contextual:** Combina o tom do tema com as cores da marca do perfil, gerando contrastes modernos (`#00f0ff`, `#f59e0b`, `#10b981`, `#ef4444`, `#38bdf8`, etc.).
  - **Destaques Tipográficos:** Define de 1 a 3 palavras-chave para receber estilização luminosa no título (`<span class="highlight-word">`).
  - **Pesquisa de Imagem Temática:** Elabora termo de busca limpo em inglês para Higgsfield AI ou Unsplash (sempre contextualizado ao assunto real).

### 4.12. Crítico Visual (Auditor de Qualidade e Legibilidade)
- **Skill:** `skills/critico-visual/SKILL.md`
- **Função:** Atua como controle de qualidade inspecionando o card renderizado antes do envio ao Telegram.
- **Modos de Operação:**
  - **Multimodal (LLM com Visão):** Inspeciona a imagem JPEG real para aferir contraste texto/fundo, hierarquia visual, espaçamento de margens e ausência de ruído.
  - **Heurística Objetiva:** Valida estouro de texto do Playwright, proporção de caracteres por layout, safe zones e fidelidade factual ao pedido original.
- **Loop de Refinamento:** Atribui pontuação de 1 a 10. Se a nota for inferior a 8, devolve parecer detalhado para que o Diretor de Arte execute 1 rodada de refinamento automático.

---

## 5. Módulos de Apoio Já Integrados

Os agentes não trabalham no vácuo: eles utilizam diretamente os recursos de infraestrutura já construídos no `ic-ap`:
- **[midia.py](file:///c:/Users/emers/Desktop/REPO/icap%20-%20teste/services/app/app/midia.py):** Conversão ffmpeg, enquadramento automático para 4:5 (feed) ou 9:16 (stories/reels), fundos borrados para vídeos verticais e mixagem de trilhas sonoras.
- **[render.py](file:///c:/Users/emers/Desktop/REPO/icap%20-%20teste/services/app/app/render.py):** Renderização de templates HTML/CSS para JPEG 1080×1350 e 1080×1920 via Playwright headless.
- **[vozes.py](file:///c:/Users/emers/Desktop/REPO/icap%20-%20teste/services/app/app/vozes.py) & [voz.py](file:///c:/Users/emers/Desktop/REPO/icap%20-%20teste/services/app/app/voz.py):** Clonagem de voz local com Chatterbox Multilingual, faster-whisper e Qwen3-TTS para narrações e vídeos falados com a voz do autor.
- **[ig.py](file:///c:/Users/emers/Desktop/REPO/icap%20-%20teste/services/app/app/ig.py) & [tunnel.py](file:///c:/Users/emers/Desktop/REPO/icap%20-%20teste/services/app/app/tunnel.py):** Publicação oficial via Instagram Graph API através do Cloudflare Tunnel.

### 5.1. Corte Inteligente de Vídeo Multimodal (Padrão AutoShorts)
- **Whisper como Relógio de Precisão:** O faster-whisper local transcreve o vídeo com timestamps no nível de palavra (*word-level timestamps*).
- **LLM Multimodal como Editor:** Analisa o vídeo e seleciona os trechos mais dinâmicos, cômicos ou informativos, **ancorando (snapping) obrigatoriamente** o início e fim do corte nos limites de palavras da transcrição do Whisper.
- **Corte + Hook Overlay:** O `ffmpeg` extrai o clipe exato em 9:16 e renderiza um gancho textual no topo do vídeo antes de enviar para aprovação no Telegram.

### 5.2. Loop de Aprendizado Contínuo (Padrão Viraloop)
- **Tabela `aprendizados` / `learnings.json`:** O sistema registra o desempenho de cada postagem e gancho gerado ao longo dos dias (Dia 1 → Posta → Analisa → Aprende; Dia 30 → Estratégia hiper-calibrada).
- **Retroalimentação Automática:** O `Content Planner` e o `Caption Writer` consultam o histórico de aprendizados do perfil antes de propor novos conteúdos, priorizando os ângulos e horários que historicamente geraram maior taxa de salvamentos e comentários.

### 5.3. Safe Zones Mobile & Estrutura de Slides (Padrão Larry Marketing)
- **Safe Zones 1080×1350 e 1080×1920:** Respeito absoluto às áreas livres de interferência da interface do Instagram (evitando que botões laterais de like/compartilhar ou a legenda inferior cubram os títulos dos slides).
- **Framework de Carrossel de Alta Retenção:**
  1. *Hook*: Quebra de padrão / pergunta imediata.
  2. *Problema*: Agitação da dor real do público.
  3. *Agitação*: Custo de oportunidade de não resolver.
  4. *Solução*: Revelação do método / insight prático.
  5. *Aplicação*: Passo a passo direto ao ponto.
  6. *CTA*: Chamada única para salvar ou comentar.

### 5.4. Distribuição Multiplataforma Local Soberana (Motor Próprio, Sem Upload-Post)
- Publicação nativa direta no **Instagram Graph API** como canal principal.
- **Motor Próprio Local ([`distribuicao.py`](file:///c:/Users/emers/Desktop/REPO/icap%20-%20teste/services/app/app/distribuicao.py)):** Elimina completamente a dependência de serviços pagos ou intermediários terceiros (como Upload-Post), permitindo postagem simultânea e soberana para:
  1. **Threads (Meta Threads API oficial):** Publicação de texto, fotos, vídeos/reels e carrosséis nativos de até 10 itens via endpoints `graph.threads.net`.
  2. **YouTube Shorts (Google YouTube Data API v3):** Upload direto de vídeos verticais MP4 com adição automática da tag `#Shorts`, título e descrição parametrizada.
  3. **LinkedIn (LinkedIn Posts API v2):** Publicação corporativa com suporte a texto, upload binário de imagens e vídeos MP4 via URNs nativas da Microsoft.
  4. **TikTok (TikTok Content Posting API v2):** Disparo de vídeos verticais com privacidade configurável (`PUBLIC_TO_EVERYONE`, `MUTUAL_FOLLOW_FRIENDS`, `SELF_ONLY`).
- **Isolamento de Falhas:** Caso uma rede secundária falhe (ex.: token expirado), a publicação no Instagram é preservada e o status individual é reportado com clareza no Telegram e no SQLite (`publicacoes_canais`).
- **Gerenciamento no Painel & Telegram:** Gestão e teste de credenciais em `/conexoes` e visualização de canais ativos pelo comando `/canais`.

---

## 6. Adaptação Cultural Brasil (Português do Brasil 2026)

Diferente de ferramentas internacionais que apenas traduzem prompts do inglês, os agentes foram desenhados para o comportamento de consumo de redes no Brasil:
- **Naturalidade:** Conversação direta, inteligente, sem formalismo excessivo de "redação publicitária de agência" nem infantilização.
- **Padrão de Consumo:** No Brasil, o consumo de carrosséis e Reels com áudio/legenda é predominante. O gancho inicial precisa conectar com problemas reais e cotidianos do público brasileiro.
- **Horários Reais:** Alinhamento com os horários de pico do público brasileiro (07:30–08:30 no deslocamento, 12:00–13:30 no almoço, 18:30–21:00 no fim da tarde/noite).

---

## 7. Estrutura de Código Proposta

Para manter o código modular e manutenível, organizamos os agentes em um novo subpacote em `services/app/app/agentes/`:

```
services/app/app/
├── agentes/
│   ├── __init__.py
│   ├── orquestrador.py        # Central de inteligência e roteamento
│   ├── caption_writer.py      # Redação de legendas focadas em meta
│   ├── carousel_planner.py    # Planejamento slide a slide
│   ├── hook_extractor.py      # Engenharia reversa de hooks
│   ├── hashtag_strategist.py  # Estratégia de 3-5 tags SEO
│   ├── humanizer.py           # Filtro anti-IA determinístico + LLM
│   ├── content_planner.py     # Calendário semanal de conteúdo
│   ├── repurposer.py          # Reaproveitamento de textos/links
│   ├── profile_optimizer.py   # Auditoria e otimização de bio/grid
│   └── audience_insights.py   # Dados e tendências (local + Apify)
├── pipeline.py                # Integração com banco e fila de posts
├── telegram.py                # Bot do Telegram
└── llm.py                     # Chamadas às APIs (Gemini, Claude, Ollama...)
```

---

## 8. Contratos JSON dos Agentes

Cada agente possui schema estrito e tipado:

```json
// Exemplo: Caption Writer
{
  "hook_125": "Se você usa IA apenas para criar textos, está jogando 80% do seu tempo fora. Veja o que mudou em 2026:",
  "corpo": "A maioria dos profissionais continua usando prompts genéricos e recebendo respostas que todo mundo reconhece de longe.\n\nO segredo agora não é gerar do zero, mas orquestrar especialistas com contextos fechados.",
  "cta": "Salve esse post para estruturar seu primeiro agente ainda esta semana.",
  "objetivo": "saves",
  "hashtags": ["#inteligenciaartificial", "#automacao", "#produtividade"]
}
```

```json
// Exemplo: Carousel Planner
{
  "titulo_carrossel": "Como orquestrar agentes inteligentes locais",
  "total_slides": 6,
  "slides": [
    {
      "slide_n": 1,
      "tipo": "capa",
      "titulo": "Pare de usar IA como estagiário.",
      "subtitulo": "Como montar um time de especialistas locais que trabalham juntos por você."
    },
    {
      "slide_n": 6,
      "tipo": "cta",
      "titulo": "O próximo passo:",
      "subtitulo": "Salve este carrossel e comente 'AGENTE' para receber a arquitetura completa."
    }
  ]
}
```

---

---

## 8.5. Técnica Blow Up (Meta AI no Navegador)

A **Técnica Blow Up** consiste em submeter um post ou Reel de alto engajamento do Instagram diretamente ao **Meta AI** (`https://www.meta.ai`) autenticado no navegador, aproveitando que a IA proprietária da Meta possui indexação privilegiada e acesso direto aos metadados do ecossistema Instagram/Facebook.

### Fluxo Operacional:
1. **Detecção Automática:** Ao enviar qualquer link do Instagram (`instagram.com/p/...` ou `instagram.com/reel/...`) no Telegram (ou pelo comando `/blowup <link>`), o pipeline intercepta a URL.
2. **Navegador Headless (Playwright):** O robô abre o Chromium com a sessão persistente e cookies injetados (configurados no menu Conexões).
3. **Dissecção em 4 Etapas:**
   - *1. Raio-X do Gancho (Hook):* Mecanismo psicológico e visual dos primeiros 3 segundos.
   - *2. Análise de Viralização:* Padrão de retenção, quebra de expectativa e gatilhos de compartilhamento/salvamento.
   - *3. Estrutura Cena a Cena:* Ritmo, transições e cortes.
   - *4. Versão Adaptada para o Autor:* Novo hook (< 125 chars), roteiro completo e legenda com 1 CTA no tom de voz de `meu_contexto.md`.
4. **Fallback Resiliente:** Caso os cookies expirem ou o navegador falhe, o sistema ativa automaticamente o LLM configurado do perfil para gerar a adaptação sem interrupção.

---

## 9. Plano de Desenvolvimento (Roadmap Multiagente)

### Fase A · Estrutura Base e Orquestrador
- [x] Criar o pacote `app/agentes/` e a classe base `BaseAgente`.
- [x] Implementar `orquestrador.py` com classificação de intenções e preservação de contexto do perfil.
- [x] Conectar os comandos e conversas do Telegram ao Orquestrador em `telegram.py` e `pipeline.py`.

### Fase B · Agentes de Redação & Polimento
- [x] Implementar `caption_writer.py` (fórmulas 2026, gancho de 125 caracteres, meta única).
- [x] Implementar `humanizer.py` (auditoria com regras regex + polimento LLM).
- [x] Implementar `hashtag_strategist.py` (3-5 tags calibradas).
- [x] Adicionar testes unitários automatizados em `tests/test_agentes.py`.

### Fase C · Agentes Visuais & Estruturais
- [x] Implementar `carousel_planner.py` integrado com o `render.py` existente.
- [x] Implementar `hook_extractor.py` (mapeamento das 10 fórmulas e geração de templates).
- [x] Implementar `repurposer.py` (conversão de LinkedIn/X/Blog para Instagram).

### Fase D · Agentes Estratégicos & Insights
- [x] Implementar `content_planner.py` (geração de calendário semanal exportável para a agenda).
- [x] Implementar `profile_optimizer.py` (auditoria de bio, nome SEO, destaques e grid).
- [x] Implementar `audience_insights.py` (varredura local e mapeamento de dores).

### Fase E · Técnica Blow Up com Meta AI via Navegador
- [x] Implementar `meta_ai.py` com Playwright persistente, injeção de cookies e fallback LLM.
- [x] Integrar detecção de links no Telegram e comando `/blowup` em `pipeline.py`.
- [x] Adicionar gerenciamento de cookies e teste de sessão no painel web (`main.py` e `conexoes.html`).
- [x] Testes unitários de extração, normalização e fallback em `test_meta_ai.py`.
- [x] 100% de compatibilidade entre Claude Code e Antigravity IDE preservada.

### Fase F · Distribuição Multiplataforma Soberana (Motor Próprio Local)
- [x] Implementar `distribuicao.py` com conectores diretos para Threads, YouTube Shorts, LinkedIn e TikTok sem intermediários ou custos.
- [x] Tabelas `canais_distribuicao` e `publicacoes_canais` no SQLite com criptografia de tokens.
- [x] Disparo automático ao aprovar post no Instagram em `pipeline.aprovar` com isolamento de falhas.
- [x] Interface de configuração, credenciais e testes individuais no painel web (`conexoes.html` e `main.py`).
- [x] Comando `/canais` no bot do Telegram para consulta em tempo real.
- [x] Testes unitários automatizados em `tests/test_distribuicao.py` (24 testes passando).

### Fase G · Estúdio Agêntico e Skills como Fonte Única da Verdade
- [x] Desacoplamento de templates fixos: criação de 6 layouts modulares (`impacto_foto`, `editorial`, `lista`, `dado`, `alerta`, `citacao`) em `templates/layouts/*.html`.
- [x] Implementação de `skills.py` com carregador dinâmico de `SKILL.md` (YAML frontmatter + Markdown) e invalidação de cache por `mtime`.
- [x] Injeção de instruções de skills no `BaseAgente` via `obter_prompt_skill(self.nome)`.
- [x] Novas skills no disco: `skills/estrategista/SKILL.md`, `skills/diretor-de-arte/SKILL.md` e `skills/critico-visual/SKILL.md`.
- [x] Implementação do `EstudioCriativo` em `agentes/estudio.py` com pipeline encadeado e loop de refinamento pelo Crítico Visual.
- [x] Suporte multimodal e heurístico no `CriticoAgente` (`agentes/critico.py`).
- [x] Atualização de `render.render_design` eliminando `tech_art_cyber.jpg` como default universal.
- [x] Eliminação de textos rígidos herdados de LGPD/cibersegurança nos cards.
- [x] Integração completa no Telegram (`pipeline.py`): o botão `🎨 Mudar Estilo` cicla dinamicamente entre os 6 designs.
- [x] Correção do bug silencioso `db.um` -> `db.one` no comando "Story com base no feed".

---

## 10. Estúdio Criativo Multiagente e Motor de Skills

### 10.1. Princípio Fundamental: Skills como Código
Antes desta fase, os agentes usavam prompts fixos hardcoded em Python e o container não incluía os arquivos de skills. A nova arquitetura estabelece que **os arquivos `skills/*/SKILL.md` são a fonte única de verdade**:
1. Qualquer edição em um arquivo `SKILL.md` no disco é detectada imediatamente via verificação de `mtime` pelo módulo `agentes/skills.py`.
2. O `Dockerfile` copia formalmente a pasta `skills` para `/srv/skills` e define `ENV SKILLS_DIR=/srv/skills`.
3. Em desenvolvimento local ou testes fora do container, o `config.py` resolve automaticamente a pasta `skills/` na raiz do repositório.

### 10.2. Os 6 Novos Layouts de Design

| Layout | Descrição | Casos de Uso Ideais | Imagem de Fundo? |
|---|---|---|---|
| `impacto_foto` | Foto sangrada de ponta a ponta com gradiente suave e manchete imponente | Notícias bombásticas, bastidores, fatos marcantes | Sim (Higgsfield ou Unsplash) |
| `editorial` | Foco em tipografia rica (Serif + Sans), badge sutil e parágrafos bem espaçados | Ensaios, reflexões, opiniões de liderança, análises densas | Não (layout 100% tipográfico) |
| `lista` | Tópicos numerados (01, 02, 03...) com caixas em glassmorphism | Passo a passo, frameworks, ferramentas, dicas | Opcional |
| `dado` | Estatística, percentual ou número gigante com legenda de contexto | Pesquisas de mercado, métricas, dados financeiros | Opcional |
| `alerta` | Moldura de urgência com cores quentes (vermelho/âmbar) e badge chamativo | Mudanças urgentes, alertas de mercado, breaking news | Não |
| `citacao` | Aspas decorativas estilizadas, texto destacado e assinatura do autor | Frases memoráveis, pensamentos de especialistas | Opcional |

Todos os 6 layouts compartilham as mesmas variáveis CSS (`--fundo-base`, `--cor-texto`, `--cor-destaque`, `--cor-acento`, `--cor-borda`) e adaptam-se automaticamente a **Feed (1080×1350)** e **Story (1080×1920)** respeitando rigorosamente as safe zones de interfaces móveis.

### 10.3. Ciclo de Vida do Post no Estúdio Agêntico

```
1. Pedido do Usuário (Texto/Notícia/Comando /feed ou /story)
      │
      ▼
2. Estrategista (Extrai fatos puros, define formato e ângulo)
      │
      ▼
3. Redator (Gera manchete de alta retenção, blocos de texto e 1 CTA)
      │
      ▼
4. Humanizador (Limpa clichês robóticos, pontuações teatrais e tempestades de emojis)
      │
      ▼
5. Diretor de Arte (Seleciona 1 dos 6 layouts, paleta hex, palavras-chave e imagem)
      │
      ▼
6. Renderizador (Chromium headless Playwright renderiza o JPEG final em alta resolução)
      │
      ▼
7. Crítico Visual (Inspeciona contraste, safe zones, texto estourado e harmonia)
      ├─► [Score < 8 e rodada < 2]: Envia feedback e volta ao Diretor de Arte
      └─► [Score >= 8 ou limite atingido]: Aprova o card
      │
      ▼
8. Disparo no Telegram (Card preview + nota do crítico + teclado de botões interativos)
```
