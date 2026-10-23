# Resultados do Claude Code local

Acrescente uma seção por tarefa concluída (mais recente embaixo): data, o que mudou, resultado de `testar.ps1`, decisões pendentes do Emerson.

## 2026-10-22 · Windows e Ollama (resumo feito pelo Cowork a partir do terminal)

- `instalar.ps1` ok; `testar.ps1 -Rapido` 17 ok; suíte completa **158 passam, 0 falham** (≈8 min) no Windows.
- Correções no app: `midia.py` (filtro `ass=` do ffmpeg com caminho entre aspas simples e `:` escapado), `pipeline._apagar` (5 tentativas com arquivo em uso). Testes: `cloudflared` falso portável (`.bat`/Python), asserção de `0o600` só fora do Windows, espera pela remoção no teste de descartar. `ruff==0.8.4` no `requirements-dev.txt`.
- Ollama 0.40.8 na RTX 5070, 100% GPU. `scripts\qualidade_llm.py` pronto.

| Métrica | qwen2.5:7b-instruct | llama3.1:8b |
|---|---|---|
| Posts gerados | 10/10 | 10/10 |
| JSON válido na 1ª tentativa | 10/10 | 10/10 |
| Tempo médio feed | 6,9 s | 7,5 s |
| Tempo médio carrossel | 7,3 s | 8,8 s |
| Tempo total | 71 s | 81 s |

Observações: Qwen um pouco melhor (slides curtos e completos; hashtags duplicadas). Llama: slide 1 vazio num carrossel, legendas longas e repetitivas. Os dois copiam frases literais do contexto do perfil. Pendências T1–T7 em `docs/FILA_DE_TAREFAS.md`.

## 2026-10-23 · T1 e T2

**T1. Primeiro commit** (autorizado pelo Emerson no terminal): `a4bf668`, 185 arquivos. Ficaram de fora `.venv\`, `bin\`, `data\` e o relatório gerado `scratch\qualidade_llm_*.md`. **Decisão tomada por mim, a confirmar:** acrescentei `old/` ao `.gitignore`, porque `old/agentroom` e `old/vectorcraft_rust` são repositórios git aninhados (entrariam como ponteiros quebrados) e `old/zips` pesa ≈200 MB. Os arquivos continuam no disco; a seção 4 de `docs/REVISAO_2026-10-22.md` segue aguardando sua autorização para apagar.

**T2. Slide vazio no carrossel.** Nova `llm.validar_slides(slides, n)`: rejeita lista fora do tamanho pedido, slide sem título e slide sem texto, com `ValueError` para o laço de tentativas (o motivo vai para o modelo como feedback). Usada por `llm.carrossel_de_texto` e pelo agente `carousel_planner` (que agora sabe quantos slides foram pedidos, via `ContextVar`). O prompt deixou de dizer que o subtítulo da capa "pode ficar vazio" (era isso que o Llama fazia; o texto da capa agora é obrigatório). Testes novos: `tests/test_carrossel_validacao.py` (11), com os modos `vazio` e `faltando` em `fake_services`. Suíte completa: **169 passam, 0 falham**; `ruff` limpo.

## 2026-10-23 · T3 a T7

Suíte completa ao final (com lint): **201 passam, 0 falham** (≈9 min). `ruff check --select F,E9` limpo. Nada commitado além do `a4bf668` (T1): as mudanças das T2 a T7 estão no disco, sem commit, aguardando o seu "sim".

**T3. Frases do contexto copiadas.**
- Causa: o `context/meu_contexto.md` traz frases-modelo entre aspas ("Minha carreira subia. Minha saúde caía.", "No fim, você sabe o que pegar…") e o modelo as copia. O próprio contexto empurra para isso: a seção "Regras de saída" manda fechar com uma frase-síntese e o fecho de exemplo é justamente essa frase.
- Prompt: regra "as frases entre aspas e os padrões do perfil são exemplos do jeito, não texto pronto; não copie" em `INSTRUCOES`, `INSTR_POST`, `INSTR_CARROSSEL`, nas diretrizes comuns dos agentes (`agentes/base.py`) e nas skills `caption-writer` e `carousel-planner`.
- Checagem pós-geração: `llm.trecho_copiado` rejeita 8 palavras seguidas vindas do contexto **ou** uma frase-modelo (trecho entre aspas com 4+ palavras) inteira; o limite de 8 palavras sozinho não pegaria "Minha carreira subia. Minha saúde caía." (6). Aplicada em `post_de_texto` e `carrossel_de_texto`; rejeição vira `ValueError` com o trecho como feedback para o laço de tentativas.
- Antes e depois (`qualidade_llm.py`, 5 ideias × feed e carrossel por modelo; "antes" medido com o mesmo detector sobre os textos do relatório de 22/10):

| Métrica (10 posts por modelo) | Qwen antes | Qwen depois | Llama antes | Llama depois |
|---|---|---|---|---|
| Posts finais com trecho copiado do contexto | 3/10 | **0/10** | 4/10 | **0/10** |
| Posts gerados (ok/total) | 10/10 | 7/10 | 10/10 | 10/10 |
| Saídas rejeitadas por cópia | n/a | 10 | n/a | 1 |
| Tentativas médias por post | 1,00 | 1,70 | 1,00 | 1,10 |
| Tempo total | 71 s | 108 s | 81 s | 93 s |

- Leitura: a checagem funciona (nenhuma cópia chega ao post), mas o **Qwen insiste no fecho "No fim, você sabe o que pegar…" e perdeu 3 dos 5 feeds** depois de 3 tentativas. O Llama obedece quase sempre. Testes: `tests/test_carrossel_validacao.py`.
- **Precisa de decisão do Emerson:** (a) tirar do `meu_contexto.md` a instrução de "fechar com frase-síntese" ou trocar o exemplo por uma descrição do tipo de fecho, sem a frase pronta; é a causa de fundo e é conteúdo seu, por isso não mexi; (b) ou subir de 3 para 4 tentativas no laço do pipeline; (c) com o contexto como está, o Llama 3.1 8B é hoje o mais confiável para o fluxo completo.

**T4. Hashtags duplicadas.** `llm.montar_legenda` agora tira do corpo as hashtags que o modelo escreveu no fim das linhas (ou em linhas só de hashtags), junta com a lista `hashtags` e escreve **um único bloco** no fim, sem repetir (sem diferenciar maiúsculas, máximo 10). Hashtag no meio de uma frase fica onde está e não é repetida no bloco. Afeta também citação e meme. Testes em `tests/test_carrossel_validacao.py`.

**T5. Rubrica do crítico visual.** `agentes/critico.py` e `skills/critico-visual/SKILL.md`: o modelo responde 5 critérios sim/não com justificativa curta (texto cortado, contraste, legibilidade, hierarquia, safe zone); **a nota é calculada no código** (pesos 3, 2, 2, 2, 1; aprova com nota ≥ 8 **e** os três eliminatórios, texto cortado, contraste e legibilidade, ok). O overflow medido pelo navegador e a manchete com mais de 16 palavras valem mais que a resposta do modelo. O contrato com o ciclo de refino (`score`, `aprovado`, `problemas`, `sugestao_ajuste`, `usou_visao`) foi mantido, com `criterios` e `pontos_fortes` a mais; os critérios reprovados viram o feedback do Diretor de Arte. Testes: `tests/test_critico.py` (novo) e `test_agentes.py`; `fake_services` ganhou o modo `critico_modo`. Observação: a antiga checagem eliminatória de "aderência ao pedido" saiu da nota (a rubrica pedida tem só os cinco critérios).

**T6. Documentar o Windows.** `docs/OPERACAO.md` seção 5: `ass=` entre aspas simples com `:` escapado, arquivos em uso e `_apagar`, `secret.key` sem permissão POSIX, cloudflared falso, ruff e `testar.ps1`, pegadinha do Git Bash, script de qualidade. `scripts/testar.ps1`: roda o `ruff` antes dos testes (`-Lint` só lint, `-SemLint` pula) e **volta ao diretório de origem** (o "erro do caminho relativo" era isso: o script deixava o PowerShell dentro de `servicespp`).

**T7. `_apagar` sem bloquear.** `_apagar` continua síncrona, com 10 tentativas de 0,5 s e, se o arquivo seguir preso, uma thread de fundo tenta por mais 2 min. Todos os pontos assíncronos usam `await _apagar_async(...)` ou `asyncio.to_thread(_apagar_post, ...)`. Testes: `tests/test_apagar.py` (o loop não trava durante a espera; arquivo preso por muito tempo acaba apagado).

**Testes que eram intermitentes no Windows, corrigidos:** o teste de lote da esteira usava espera de 1 s para o resumo (`LOTE_ESPERA_S`), menor que o tempo de gerar uma foto no Windows, e o resumo saía com 2 posts em vez de 3; subi para 6 s só no teste (em produção é 20 s). O teste do carrossel que esperava slides sumirem passou a passar de forma estável com a T7.

**Sugestões (sem ação minha):** atualizar as "Pendências conhecidas" do `CLAUDE.md` (itens 1 e 3 estão resolvidos); decidir sobre `old/` (seção 4 de `REVISAO_2026-10-22.md`); fazer o commit das T2 a T7.
