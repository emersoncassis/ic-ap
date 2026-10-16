# 06 · Dashboard web e multi-perfil

## Status (v1 implementada)

Implementado em `services/app`: login, fila (aprovar/refazer/descartar/editar legenda), perfis (token criptografado, contexto, horários, LLM), feeds globais e por perfil, aba LLM (conexões nomeadas: detectar modelos, aplicar e testar), conexões com túnel Cloudflare, Telegram, fuso e senha editáveis, testes de Meta/LLM/Telegram/URL pública, histórico, agendador por horário, bot do Telegram. O n8n foi removido.
Diferenças em relação ao texto abaixo: os horários (`horarios`, ex.: `09:00,18:00`) substituem `posts_por_dia`.
Ainda **não** implementado: importar contexto a partir do site, métricas de alcance, Cloudflare Access para acesso externo, limpeza automática de cards antigos.

## Objetivo

Painel web para gerenciar a esteira sem editar arquivos: trocar o perfil que posta (Emerson, Iago, Igor), ver a fila de posts, aprovar/descartar, ajustar contexto, feeds e frequência. A aplicação deixa de ser "do Emerson" e passa a servir várias pessoas.

## Decisão de arquitetura (aprovada e implementada)

Com várias contas e configuração editável na web, o n8n deixa de compensar: o estado (perfis, fila, histórico) precisa de banco e de uma interface própria. **App Python único** (FastAPI + Jinja2 + HTMX, SQLite) que concentra:

- dashboard web
- agendador (cron por perfil)
- pipeline: feed → extração → LLM → render → aprovação → publish
- bot do Telegram (aprovação pelo celular)

Sem etapa de build de frontend. O n8n saiu do compose.

## Modelo de dados

- `perfis`: id, nome, handle, ativo, ig_user_id, ig_token (criptografado), telegram_chat_id, llm_provider, llm_model, contexto_md, template, posts_por_dia, horarios, filtros, criado_em
- `feeds`: id, perfil_id (nulo = global), nome, url, tema, ativo
- `posts`: id, perfil_id, estado, noticia_url, noticia_titulo, json_llm, arquivo, legenda, media_id, erro, criado_em, atualizado_em
- `eventos`: log de ações (quem aprovou, falhas, publicações)

Estados do post: `capturado → extraido → gerado → aguardando_aprovacao → aprovado → publicando → publicado`; laterais `descartado` e `falhou`.

## Telas

1. **Fila:** posts por estado, preview do card, legenda editável, botões Aprovar / Refazer / Descartar, link do post publicado.
2. **Perfis:** lista com liga/desliga; editar nome, handle, frequência, horários, template, provedor/modelo de LLM.
3. **Contexto:** editor do `meu_contexto.md` do perfil, com botão "importar do site" (gera rascunho) e botão "testar" que gera uma reação de exemplo.
4. **Feeds:** feeds globais e por perfil, palavras-chave, idade máxima.
5. **Conexões:** testar token da Meta (conta, limite de publicação), Telegram, Ollama e o túnel público, cada um com status verde/vermelho.
6. **Histórico:** posts publicados, falhas, contagem por perfil.
7. **Geral:** timezone, retenção de arquivos, provedor de LLM padrão.

## Segurança (obrigatório, o painel guarda tokens de várias pessoas)

- Login com senha (hash forte) e sessão com CSRF.
- Escuta só em `127.0.0.1`. Para acesso de fora, usar um **segundo** hostname protegido por Cloudflare Access, nunca o hostname de imagens.
- Tokens e chaves criptografados no banco com chave gerada no primeiro uso (`data/secret.key`, 0600); a tela nunca mostra o token inteiro.
- Cada perfil só publica com o próprio token e o próprio `ig_user_id`.
- Todo publish passa por aprovação (Telegram ou painel) na v1.

## Pontos de atenção do multi-perfil

- **Permissão no app da Meta:** em Standard Access o app só age em contas de pessoas com função no app (administrador, desenvolvedor, testador). Para Iago e Igor, adicioná-los ao app. Se um dia o painel servir terceiros (clientes), será preciso App Review e Business Verification; conferir na documentação da Meta antes.
- Cada pessoa precisa de **seu próprio token de Página**, **seu próprio chat do Telegram** e **seu próprio contexto**. Postar na conta de alguém exige autorização dessa pessoa.
- Um contexto por perfil evita que o tom de um vaze para o outro.

## Critérios de aceite

- Criar um perfil novo (Iago) pelo painel, com contexto próprio, e gerar um post de teste sem editar arquivo nenhum.
- Desligar um perfil interrompe o agendamento dele sem afetar os outros.
- Token inválido aparece em vermelho em "Conexões" antes de falhar um post.
- Sem login, nenhuma tela nem endpoint responde.
