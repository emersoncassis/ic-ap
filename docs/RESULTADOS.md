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
