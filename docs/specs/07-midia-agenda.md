# Spec 07: pauta do dia, agenda local, mídia do Telegram e música

## Pauta e agenda
- `Pauta`: por perfil, pesquisa os feeds nos temas (`palavras_chave`), ordena por relevância + “em alta” (mesmo assunto em fontes diferentes, medido pelas palavras do título) e cria N notícias × M versões. Cada versão tem um ângulo (opinião direta, explicação simples, impacto para gestores, pergunta para debate). Estado `rascunho`, sem notificar o Telegram por post (uma mensagem-resumo).
- Você marca os rascunhos, define data/hora (no fuso configurado) e intervalo; o estado vira `agendado` com `agendado_para` em UTC. O agendador (tick de 30 s) publica o que venceu. **A agenda é do app, não do Instagram**: a API não cria itens na lista de “Agendados” do app e o contêiner da Meta expira em 24 h.
- Estados: `rascunho` → `agendado` → `publicando` → `publicado` (ou `falhou`, `descartado`).

## Formatos publicados pela API
| Formato | Mídia | Observações |
|---|---|---|
| feed | JPEG 1080x1350 | legenda até 2200 |
| story | JPEG ou MP4 1080x1920 | sem legenda; sem sticker de link/enquete/música |
| reel | MP4 H.264/AAC 1080x1920, até 90 s | `share_to_feed=true` |

## Telegram: foto e vídeo
Mensagens do `telegram_chat_id` do perfil com foto/vídeo (limite de 20 MB do getFile) viram post. ffmpeg corta a foto (4:5 ou 9:16) e converte o vídeo para 9:16 com fundo borrado. A legenda vem do LLM a partir da frase de contexto (sem frase: legenda em branco). Palavras `story`, `reel`, `feed`, `sem música` mudam o destino. Aprovação pelos botões (Postar/Refazer legenda/Descartar). Vídeo maior que 20 MB: usar um servidor local da Bot API (não implementado).

## Música
- Biblioteca local em `data/musicas` (aba Músicas). Modo por perfil: nenhuma ou aleatória. Com áudio original a trilha entra a 22%; sem áudio, a 85%, com fade de saída.
- **Não implementado (a verificar):** Audio API da Meta para Reels (catálogo de músicas e sons em alta no Login do Facebook). O catálogo é menor que o do app e a disponibilidade depende da conta/região; precisa ser testada na conta real.
- Fontes de música livre (conferir a licença de cada faixa): Pixabay Music, YouTube Audio Library, Uppbeat, Free Music Archive, Meta Sound Collection (só dentro do app).

## Fora do alcance da API oficial
Repostar Story de terceiros, sticker de link, enquete e GIF em Story, música da biblioteca do app em feed/Story, rascunho/agendamento nativo do Instagram.
