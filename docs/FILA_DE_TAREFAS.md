# Fila de tarefas do ic-ap

Caixa de correio entre o Claude do Cowork (planeja e revisa) e o Claude Code local (executa no Windows, com GPU e Ollama).

## Como funciona

- **Claude Code local:** ao ser chamado com "continue" ou "próxima tarefa", leia este arquivo, pegue a primeira tarefa com status `[ ]` e execute. Siga o `CLAUDE.md`.
- Ao terminar cada tarefa: troque `[ ]` por `[x]` e acrescente uma seção no fim de `docs/RESULTADOS.md` (data, o que mudou, resultado de `testar.ps1`, o que precisa de decisão do Emerson). Não cole logs enormes: resuma e salve o bruto em `scratch\`.
- Rode `testar.ps1` completo antes de marcar `[x]` qualquer tarefa que mude código. Não apague arquivos nem faça commit sem o "sim" do Emerson no terminal, salvo quando a tarefa disser que está autorizado.
- Se travar, escreva o motivo em `docs/RESULTADOS.md` e passe para a próxima.
- **Claude do Cowork:** lê `docs/RESULTADOS.md` pela pasta conectada e acrescenta novas tarefas aqui.

## Tarefas

- [x] **T1. Primeiro commit.** Só com o "sim" do Emerson no terminal. Mensagem em português; incluir `.gitignore` atualizado; não incluir `.venv\`, `bin\`, `data\`, `scratch\*.md` gerados.
- [x] **T2. Slide vazio no carrossel.** No `qualidade_llm.py` o llama3.1:8b gerou um carrossel com o slide 1 sem texto. Em `llm.carrossel_de_texto` (e no agente `carousel_planner`), valide que nenhum slide venha vazio e que o número de slides bata com o pedido; se não, levante `ValueError` para o laço de tentativas repetir. Teste novo em `tests/` usando `fake_services`.
- [x] **T3. Frases do contexto copiadas.** Os dois modelos repetem frases literais de `context/meu_contexto.md` ("Minha carreira subia. Minha saúde caía.", "Não é X, é Y."). Investigue `llm.montar_system` e as skills do redator: separe o que é tom e voz do que são frases de exemplo, e instrua o modelo a não copiar frases do contexto. Adicione uma checagem pós-geração que rejeite texto com trecho literal longo (por exemplo 8 palavras seguidas) vindo do contexto, e teste. Depois rode `qualidade_llm.py` de novo e compare antes e depois (tabela em `docs/RESULTADOS.md`).
- [x] **T4. Hashtags duplicadas** na legenda do Qwen (visto em `scratch\qualidade_llm_20261022_233716.md`). Deduplique em `llm.normalizar_hashtags` / `montar_legenda`, com teste.
- [x] **T5. Rubrica objetiva do crítico visual.** Em `agentes/critico.py` e `skills/critico/SKILL.md`, troque a nota solta 0–10 por uma lista de critérios verificáveis (texto cortado, contraste, hierarquia, safe zone, legibilidade), cada um sim/não com a justificativa curta, e calcule a nota no código a partir deles. Mantenha o ciclo de refino. Atualize os testes.
- [x] **T6. Documentar o Windows.** Em `docs/OPERACAO.md` registre: caminho do `ass=` no ffmpeg, arquivos em uso no Windows (`_apagar` com tentativas), `secret.key` sem permissão POSIX, `ruff` no `testar.ps1`. Corrija também o erro do caminho relativo do ruff no `testar.ps1` que você mencionou.
- [x] **T7. `_apagar` sem bloquear.** Chame o `_apagar` por `asyncio.to_thread` nos pontos assíncronos (ex.: `descartar`), mantendo a função síncrona. Teste.

## Depois (precisam de decisão ou dados do Emerson)

- Comparar o Gemini na tabela de `qualidade_llm.py` (precisa que a chave esteja cadastrada no painel).
- Fechar o loop de aprendizado com a Insights API da Meta (precisa de token real).
- Dividir `main.py` e `pipeline.py` em módulos.
