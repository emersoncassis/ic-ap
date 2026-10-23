# ic-ap

Estúdio agêntico e esteira local de criação de conteúdo para Instagram e redes sociais.

Orquestra um time de especialistas autônomos (**Estrategista**, **Redator**, **Humanizador**, **Diretor de Arte** e **Crítico Visual**), utiliza **Skills dinâmicas** em Markdown (`skills/`) como fonte única de verdade, renderiza **6 layouts modulares de design** em alta resolução (Feed 4:5 e Story 9:16) sem textos repetitivos de nicho, audita a qualidade visual antes da entrega e publica de forma soberana e simultânea no **Instagram**, **Threads**, **YouTube Shorts**, **LinkedIn** e **TikTok**.

> **Status:** Sistema 100% autônomo com painel web moderno, Estúdio Criativo Multiagente integrado, Playwright Chromium headless, Telegram Bot bidirecional com botões interativos e distribuição multiplataforma direta (sem intermediários pagos ou SaaS de terceiros).

![exemplo do card](docs/exemplo-card.jpg)

## Como Subir

**Windows (recomendado, sem Docker):**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\instalar.ps1   # uma vez
.\scripts\iniciar.ps1
```

**Docker (opcional):** `docker compose up -d --build`. Detalhes em [`docs/OPERACAO.md`](docs/OPERACAO.md).

Abra [http://localhost:8000](http://localhost:8000). No primeiro acesso, crie a sua senha mestre (o sistema gera automaticamente a chave de criptografia em `data/secret.key`; no Docker os dados ficam no volume `icap_data`).

### Configuração em 3 passos pelo painel web:
1. **LLM:** Conecte o modelo de sua preferência (Ollama, LM Studio, Jan, Gemini, Claude, OpenRouter ou OpenAI). Use o botão **Detectar Modelos** e **Aplicar e Testar**. Para modelos locais, use `localhost` no Windows (ou `host.docker.internal` se o app estiver no Docker). O Crítico Visual detecta automaticamente se o modelo possui suporte multimodal (visão) ou aciona heurísticas objetivas de controle de qualidade.
2. **Conexões:** Informe o token do Cloudflare Tunnel (`docs/cloudflare-tunnel.md`), URL pública e token do bot do Telegram. Configure também os canais opcionais de distribuição (Threads, Shorts, LinkedIn, TikTok).
3. **Perfis:** Configure o `@handle`, tom de voz em `meu_contexto.md`, horários preferidos de postagem e vincule seu Telegram Chat ID.

Em caso de esquecimento da senha (somente pela linha de comando, na máquina que roda o app):
```bash
docker compose exec app python -m app.reset_senha     # Docker; no Windows, veja docs/OPERACAO.md
```
Sem GPU NVIDIA, suba só o painel: `docker compose up -d --build app` (o serviço `llm` do compose exige o runtime NVIDIA).

## O que o Estúdio Faz

### 🎨 Estúdio Criativo Multiagente
- **Skills como Fonte Única da Verdade (`skills/`):** As diretrizes dos agentes vivem em arquivos `SKILL.md` (YAML frontmatter + Markdown). Edições no disco têm efeito imediato com auto-reload via `mtime`.
- **Pipeline em Cadeia:**
  $$\text{Estrategista} \longrightarrow \text{Redator} \longrightarrow \text{Humanizador} \longrightarrow \text{Diretor de Arte} \longrightarrow \text{Render} \longrightarrow \text{Crítico Visual}$$
- **Fidelidade Factual Estrita:** O Estrategista extrai apenas fatos confirmados do pedido ou notícia, impedindo qualquer vazamento de textos rígidos ou temas não solicitados.
- **Crítico Visual com Revisão Automática:** Inspeciona o card gerado (visão multimodal ou heurística objetiva). Se a nota for menor que 8/10, aciona automaticamente 1 ciclo de refinamento com o Diretor de Arte antes de enviar para aprovação.
- **6 Layouts Modulares de Alto Impacto:**
  1. `impacto_foto`: Foto de ponta a ponta com gradiente escuro e manchete imponente.
  2. `editorial`: Tipografia marcante (Serif/Sans) para reflexões densas (100% tipográfico).
  3. `lista`: Tópicos numerados (01, 02, 03...) em caixas de vidro para salvar.
  4. `dado`: Métrica ou estatística central gigante com legenda explicativa.
  5. `alerta`: Borda viva e badge de urgência/breaking news.
  6. `citacao`: Aspas decorativas grandes e assinatura de autoridade.
- **Botão "🎨 Mudar Estilo":** Permite alternar instantaneamente entre os 6 designs pelo próprio Telegram.

### 📱 Criação Conversacional no Telegram
- **Criação Livre:** Envie qualquer ideia ou tema (ex.: *"Faz um story sobre nova regra portuária"* ou *"Carrossel de 6 slides sobre automação"*).
- **Comandos Diretos:**
  - `/feed <ideia>`: Cria post 4:5 com manchete e copy no seu tom.
  - `/story <ideia>`: Gera story vertical 9:16 com safe zones.
  - `/reels <ideia>`: Roteiro cena a cena, gancho 0-3s e overlay 9:16.
  - `/carrossel <ideia>`: Sequência estruturada (capa, curiosidade, valor e CTA).
  - `/badge <texto> [estilo]`: Gera selos vetoriais VectorCraft (`neon_ciano`, `neon_ouro`, `alerta_vermelho`, `pill_clean`).
  - `/blowup <link>`: Executa a técnica Blow Up via Meta AI no navegador para dissecar posts e reels virais.
  - `/planejar`: Cria cronograma estratégico semanal.
  - `/auditar <texto>`: Analisa score de robô/IA e clichês.
  - `/humanizar <texto>`: Limpa vícios de escrita de IA.
  - `/hashtags <tema>`: Seleciona 3 a 5 tags indexáveis para SEO 2026.
  - `/canais`: Exibe os canais ativos de publicação simultânea.

### 📡 Distribuição Multiplataforma Soberana
- Publicação direta sem mensalidades em ferramentas como Buffer ou Hootsuite.
- Ao aprovar o post no Telegram ou no painel, ele pode ser postado simultaneamente no **Instagram**, **Threads**, **YouTube Shorts**, **LinkedIn** e **TikTok**.

### 🎙️ Voz e Mídia Local
- **Clonagem de Voz Local:** Suporte a Chatterbox Multilingual, faster-whisper e Qwen3-TTS via GPU NVIDIA (`--profile gpu`).
- **Mixagem de Áudio:** Sincronização e ajuste de volume de trilhas livres de direitos sob a voz original ou narração.

## Testes Automatizados

Para rodar a suíte completa de testes unitários e de integração (precisa de `ffmpeg` e do Chromium do Playwright; leva alguns minutos):

```bash
cd services/app && pip install -r requirements-dev.txt && playwright install chromium && python -m pytest
```
Os serviços externos são simulados (`tests/fake_services.py`). Detalhes e armadilhas em [docs/OPERACAO.md](docs/OPERACAO.md#5-testes).

Para validar os 6 layouts de design, o carregador de skills e o crítico visual:
```bash
python scratch/test_studio.py
```

## Especificações Técnicas (Docs)

| Especificação | Assunto |
|---|---|
| [00-viabilidade](docs/specs/00-viabilidade.md) | Veredito de viabilidade técnica, infraestrutura local e limites de APIs |
| [01-arquitetura](docs/specs/01-arquitetura.md) | Diagrama do sistema, componentes, docker-compose e provedores de LLM/Visão |
| [02-pipeline](docs/specs/02-pipeline.md) | Ciclo de vida agêntico, etapas do Estúdio Criativo e estados do post |
| [03-instagram-publicacao](docs/specs/03-instagram-publicacao.md) | Autenticação Meta Graph API, tokens de longa duração e publicação |
| [04-contexto-pessoal](docs/specs/04-contexto-pessoal.md) | Estrutura de `meu_contexto.md`, personalidade e regras de tom |
| [05-roadmap](docs/specs/05-roadmap.md) | Fases de desenvolvimento, marcos de entrega e validações |
| [06-dashboard-multiperfil](docs/specs/06-dashboard-multiperfil.md) | Painel web multiperfil (isolamento de contas, marca e estatísticas) |
| [07-midia-agenda](docs/specs/07-midia-agenda.md) | Pauta do dia, agendador local, enquadramento de vídeo e trilhas |
| [08-agentes-inteligentes](docs/specs/08-agentes-inteligentes.md) | Catálogo dos 12 agentes especialistas, Estúdio Criativo e Skills dinâmicas |
| [ARQUITETURA_E_MODULOS](docs/ARQUITETURA_E_MODULOS.md) | Mapa técnico do código atual: módulos, banco, estados do post, rotas, segurança |
| [OPERACAO](docs/OPERACAO.md) | Subir/atualizar, backup, senha, testes e solução de problemas |
| [REVISAO_2026-10-22](docs/REVISAO_2026-10-22.md) | Relatório da revisão geral: o que estava quebrado, o que foi corrigido e o que falta |
| [cloudflare-tunnel](docs/cloudflare-tunnel.md) | Guia prático para configuração do túnel Cloudflare sem portas abertas |
