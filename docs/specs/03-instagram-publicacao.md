# 03 · Publicação no Instagram

## Pré-requisitos

- Conta Instagram **Profissional** (Criador ou Empresa).
- App criado no Meta for Developers; você já tem credenciais e o ID da conta.
- Standard Access basta, porque o app só publica na sua própria conta. App Review não é exigido.

## Fluxo de login: decidido (Facebook Login)

O app usa **API do Instagram com Login do Facebook**: permissões `instagram_basic` e `instagram_content_publish` (+ `pages_read_engagement`), com a conta do Instagram ligada a uma Página do Facebook. Host: `graph.facebook.com`. O token usado nas chamadas é o **token da Página**.

Obtenção do token (script `scripts/meta_token.py`):
1. No Graph API Explorer, gerar um token de usuário com as permissões acima (curto, ~1 h).
2. `exchange`: troca por token de usuário longo (~60 dias).
3. `pages`: com o token longo, lista suas Páginas e devolve o token da Página e o `IG_USER_ID` ligado. Um token de Página obtido de um token de usuário longo normalmente não expira. Conferir isso com `check` e, se expirar, refazer o passo 2 e 3.
4. Colocar `IG_USER_ID` e `IG_ACCESS_TOKEN` no `.env`.

Atenção: se a Página exigir Page Publishing Authorization, o publish falha até completar essa etapa no Facebook.

## Chamadas (post de imagem única)

1. `POST /{IG_ID}/media` com `image_url` (URL pública do JPEG) e `caption` → devolve `creation_id`.
2. (Opcional) `GET /{creation_id}?fields=status_code` até `FINISHED`.
3. `POST /{IG_ID}/media_publish` com `creation_id` → devolve o ID da mídia.

## Carrossel (v1.1)

Um container filho por imagem (`is_carousel_item=true`), depois um container `CAROUSEL` com `children=[ids]`, depois `media_publish`. Até 10 itens. Todas as imagens são cortadas na proporção da primeira.

## Imagem

- Somente **JPEG**.
- 1080×1350 (4:5). Conferir na documentação atual se a proporção continua aceita antes de implementar.
- URL precisa estar acessível publicamente no momento do publish; apagar depois.

## Limites

- Cerca de 100 posts por API por 24 h (a documentação tem uma menção a 50 para carrossel; verificar com `GET /{IG_ID}/content_publishing_limit`). Muito acima do uso previsto.

## Token

- Se o token da Página expirar, o publish devolve erro de token. O serviço mostra a mensagem da Meta e o n8n avisa no Telegram.
- Rotina de conferência (ex.: semanal) chamando `check` ou `GET /{IG_ID}?fields=username` para detectar token inválido antes de um post.
- Nunca commitar token.

## Erros a tratar

URL inacessível, formato não-JPEG, token expirado, container em `ERROR`/`EXPIRED`, Page Publishing Authorization pendente (fluxo Facebook). Em qualquer falha: estado `falhou`, mensagem no Telegram, sem retry infinito.

## Implementação

`POST /publish` no serviço `tools`, corpo `{"arquivo": "<uuid>.jpg", "legenda": "..."}`. Cria o container com a URL pública, consulta `status_code` até `FINISHED` (até ~60 s, configurável), chama `media_publish`, devolve `{"media_id"}` e apaga o JPEG. Em erro da Meta responde 502 com a mensagem (sem o token). Versão da API em `IG_GRAPH_VERSION` (padrão `v23.0`; atualizar quando a Meta descontinuar).
