# 03 · Publicação no Instagram

## Pré-requisitos

- Conta Instagram **Profissional** (Criador ou Empresa).
- App criado no Meta for Developers; você já tem credenciais e o ID da conta.
- Standard Access basta, porque o app só publica na sua própria conta. App Review não é exigido.

## Decisão de fluxo de login (a confirmar com o app existente)

| | Instagram Login | Facebook Login |
|---|---|---|
| Host | `graph.instagram.com` | `graph.facebook.com` |
| Token | Instagram User token | Page token |
| Permissão | `instagram_business_basic`, `instagram_business_content_publish` | `instagram_basic`, `instagram_content_publish`, `pages_read_engagement` |
| Página do Facebook | Não precisa | Precisa estar vinculada |

**Recomendação:** usar o fluxo que o seu app atual já tem configurado. Se ainda não definiu, Instagram Login é mais simples.

## Estado atual do seu app

Você já tem o app criado no Meta Developers, o ID da conta Instagram e um token. A conferir antes de implementar:
- Qual produto o app usa (Instagram Login ou Facebook Login) e se a permissão de publicação foi concedida.
- Se o token é de curta duração (~1 h) ou longo (~60 dias). Se for curto, o primeiro passo é trocá-lo por um longo.
- O token vai só no `.env`. Não colar em chat nem commitar.

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

- Token curto → trocar por token longo (~60 dias).
- Workflow de refresh agendado (ex.: a cada 30 dias) que grava o novo token e avisa no Telegram se falhar.
- Nunca commitar token.

## Erros a tratar

URL inacessível, formato não-JPEG, token expirado, container em `ERROR`/`EXPIRED`, Page Publishing Authorization pendente (fluxo Facebook). Em qualquer falha: estado `falhou`, mensagem no Telegram, sem retry infinito.
