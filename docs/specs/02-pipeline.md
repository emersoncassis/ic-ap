# 02 · Pipeline

## Gatilhos

1. **Automático:** cron (ex.: 1×/dia) lê feeds RSS configurados e escolhe as N notícias mais relevantes ainda não processadas.
2. **Manual:** você manda um link ao bot do Telegram.

Deduplicação: guardar hash/URL de cada notícia já processada (tabela `posts` no SQLite, única por perfil + URL).

## Etapas

1. **Captura:** pega URL, título, data, fonte.
2. **Extração:** serviço `extractor` devolve texto limpo (truncar para caber no contexto do modelo).
3. **Reação:** Ollama recebe `meu_contexto.md` (system) + texto da notícia (user) e devolve JSON. Usar modo `format: json` do Ollama com o schema abaixo; validar e tentar de novo até 2× se inválido.
4. **Render:** injeta o JSON em `templates/reacao.html`, renderiza em 1080×1350 e exporta **JPEG** (qualidade ~90).
5. **Aprovação:** Telegram envia imagem + legenda com botões `[Postar]` `[Refazer]` `[Descartar]`. Refazer volta ao passo 3 com temperatura maior.
6. **Publicação:** spec 03.
7. **Registro:** salva notícia, JSON, JPG, ID do post e horário.

## Contrato JSON do LLM

```json
{
  "manchete_curta": "string, até 8 palavras",
  "minha_reacao": "string, 2 parágrafos curtos, primeira pessoa, tom do contexto",
  "legenda_instagram": "string, inclui crédito da fonte e hashtags",
  "fonte": "string, nome do veículo",
  "confianca": "alta | media | baixa"
}
```

Regras de validação: manchete ≤ 10 palavras; reação pedida com ≤ 450 caracteres e aceita até 600, mas o card é conferido: se o texto estourar a área, o modelo é chamado de novo pedindo para encurtar (até 3 tentativas); legenda ≤ 2200 caracteres (limite do Instagram); `fonte` obrigatório; se `confianca = baixa`, marcar o post no Telegram com aviso.

## Estados de um post

`capturado → extraido → gerado → aguardando_aprovacao → aprovado → publicando → publicado`
Saídas laterais: `descartado`, `falhou` (com motivo e botão de retry).

## Requisitos de qualidade

- Reação nunca inventa dado que não esteja na matéria; quando opinar, deixa claro que é opinião.
- Sem frases genéricas de IA ("no mundo dinâmico de hoje…"). Lista de frases banidas no contexto.
- Toda postagem cita a fonte.
