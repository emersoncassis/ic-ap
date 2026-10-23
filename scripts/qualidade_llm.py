"""Compara a qualidade de modelos locais do Ollama gerando posts reais pelo pipeline do app.

Não faz parte da suíte automática (fala com o Ollama de verdade e demora). Uso:

    .\\.venv\\Scripts\\python.exe scripts\\qualidade_llm.py
    python scripts\\qualidade_llm.py --modelos qwen2.5:7b-instruct llama3.1:8b --posts 5

Para cada modelo gera, por ideia, um post de feed (legenda + card) e um carrossel, chamando
`pipeline.criar_de_texto` (o mesmo caminho do painel), e mede tempo, se o JSON veio válido
na primeira tentativa e o texto final. Usa um banco e uma pasta de dados TEMPORÁRIOS: não mexe
nos dados do painel.
"""
import argparse
import asyncio
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MODELOS_PADRAO = ["qwen2.5:7b-instruct", "llama3.1:8b"]
IDEIAS = [
    "Por que a maioria das pequenas empresas perde tempo com planilhas quando já poderia automatizar tarefas repetitivas",
    "Três erros que fazem um gestor desistir de usar inteligência artificial no primeiro mês",
    "Como transformar uma reunião de uma hora em um resumo de cinco linhas que todo mundo realmente lê",
    "O que muda no atendimento ao cliente quando um assistente de IA responde as dúvidas simples",
    "Quanto custa de verdade rodar um modelo de linguagem na sua própria máquina em vez de pagar por token",
]


def _preparar_ambiente(dados: Path) -> None:
    """Variáveis de caminho do app, apontando para dados temporários. Tem de rodar antes de importar `app`."""
    os.environ.update({
        "DATA_DIR": str(dados), "TEMPLATES_DIR": str(RAIZ / "templates"), "SKILLS_DIR": str(RAIZ / "skills"),
        "CONTEXT_FILE": str(RAIZ / "context" / "meu_contexto.md"), "FEEDS_FILE": str(RAIZ / "config" / "feeds.yml"),
        "PYTHONUTF8": "1",
    })
    sys.path.insert(0, str(RAIZ / "services" / "app"))


def _exe_ollama() -> str:
    achado = shutil.which("ollama")
    if achado:
        return achado
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return str(local) if local.exists() else "ollama"


def _ollama_ps() -> str:
    return subprocess.run([_exe_ollama(), "ps"], capture_output=True, text=True, encoding="utf-8").stdout.strip()


def _processador(modelo: str) -> str:
    """Coluna PROCESSOR do `ollama ps` para o modelo (ex.: '100% GPU'); 'não carregado' se não aparecer."""
    for linha in _ollama_ps().splitlines()[1:]:
        if linha.split()[0:1] == [modelo]:
            m = re.search(r"(\d+%/\d+%\s*CPU/GPU|\d+%\s*(?:GPU|CPU))", linha)
            return m.group(1) if m else linha
    return "não carregado"


async def _aquecer(base_url: str, modelo: str) -> float:
    """Carrega o modelo na VRAM antes de medir, para o tempo de carga não entrar na conta dos posts."""
    import httpx
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=600) as c:
        r = await c.post(f"{base_url}/api/generate", json={"model": modelo, "prompt": "ok", "stream": False,
                                                           "keep_alive": "10m", "options": {"num_predict": 1}})
        r.raise_for_status()
    return time.perf_counter() - t0


def _instrumentar(llm) -> dict:
    """Conta chamadas e ValueError (JSON/regra inválida) de cada gerador, sem alterar o comportamento do pipeline."""
    est = {"chamadas": 0, "invalidas": 0, "erros": []}
    for nome in ("post_de_texto", "carrossel_de_texto"):
        orig = getattr(llm, nome)

        async def envolto(*a, _orig=orig, **k):
            est["chamadas"] += 1
            try:
                return await _orig(*a, **k)
            except ValueError as e:
                est["invalidas"] += 1
                est["erros"].append(str(e))
                raise
        setattr(llm, nome, envolto)
    return est


async def _rodar_modelo(modelo: str, base_url: str, perfil_id: int, n_posts: int, n_slides: int, db, pipeline, est: dict) -> dict:
    db.x("DELETE FROM llm_conexoes")
    cid = db.x("INSERT INTO llm_conexoes(nome, tipo, base_url, api_key_enc, modelo, padrao, criado_em) VALUES(?,?,?,?,?,1,?)",
               (f"Ollama {modelo}", "ollama", base_url, "", modelo, db.now()))
    db.x("UPDATE perfis SET llm_conexao_id=? WHERE id=?", (cid, perfil_id))
    for mod in ("chat", "legenda", "noticias", "roteiro"):
        db.set_setting(f"llm_modulo_{mod}", str(cid))

    carga = await _aquecer(base_url, modelo)
    processador = _processador(modelo)
    print(f"\n=== {modelo} · carga {carga:.1f}s · {processador} ===", flush=True)

    itens = []
    for i, ideia in enumerate(IDEIAS[:n_posts], 1):
        for formato in ("feed", "carrossel"):
            est["chamadas"] = est["invalidas"] = 0
            est["erros"] = []
            t0 = time.perf_counter()
            ids = await pipeline.criar_de_texto(perfil_id, ideia, formato, n_slides)
            dt = time.perf_counter() - t0
            if ids:
                po = pipeline.post(ids[0])
                res = json.loads(po["json_llm"])
            else:
                po = db.one("SELECT * FROM posts WHERE perfil_id=? ORDER BY id DESC LIMIT 1", (perfil_id,))
                res = None
            item = {"n": i, "formato": formato, "ideia": ideia, "segundos": dt, "ok": bool(ids), "tentativas": est["chamadas"],
                    "invalidas": est["invalidas"], "erros": list(est["erros"]), "res": res, "erro_final": None if ids else (po or {}).get("erro")}
            itens.append(item)
            marca = "ok " if item["ok"] else "FALHOU"
            print(f"  [{i}/{n_posts}] {formato:<9} {dt:6.1f}s  tentativas={item['tentativas']}  json 1ª tentativa: "
                  f"{'sim' if item['ok'] and item['invalidas'] == 0 else 'não'}  {marca}", flush=True)
    return {"modelo": modelo, "carga": carga, "processador": processador, "itens": itens}


def _texto_do_item(it: dict) -> str:
    r = it["res"]
    if not r:
        return f"(sem saída válida: {it['erro_final']})"
    if "slides" in r:
        corpo = "\n".join(f"  {k}. {s['titulo']} — {s['texto']}" for k, s in enumerate(r["slides"], 1))
    else:
        corpo = f"  Manchete: {r['manchete_curta']}\n  Card: {r['texto_card']}"
    return f"{corpo}\n  Legenda:\n" + "\n".join("    " + ln for ln in r["legenda"].splitlines())


def _tabela(resultados: list[dict]) -> str:
    def linha(rotulo, f):
        return "| " + rotulo + " | " + " | ".join(f(r) for r in resultados) + " |"

    def stats(r, filtro=None):
        its = [i for i in r["itens"] if filtro is None or i["formato"] == filtro]
        return [i["segundos"] for i in its]

    def media(xs):
        return f"{statistics.mean(xs):.1f}s" if xs else "-"

    def pct(r):
        its = r["itens"]
        return f"{sum(1 for i in its if i['ok'] and i['invalidas'] == 0)}/{len(its)}"

    cab = "| Métrica | " + " | ".join(r["modelo"] for r in resultados) + " |\n|---|" + "---|" * len(resultados)
    linhas = [
        linha("Processador (ollama ps)", lambda r: r["processador"]),
        linha("Carga do modelo", lambda r: f"{r['carga']:.1f}s"),
        linha("Posts gerados (ok/total)", lambda r: f"{sum(1 for i in r['itens'] if i['ok'])}/{len(r['itens'])}"),
        linha("JSON válido na 1ª tentativa", pct),
        linha("Tentativas médias por post", lambda r: f"{statistics.mean(i['tentativas'] for i in r['itens']):.2f}"),
        linha("Tempo médio · feed (legenda+card)", lambda r: media(stats(r, "feed"))),
        linha("Tempo médio · carrossel", lambda r: media(stats(r, "carrossel"))),
        linha("Tempo mediano geral", lambda r: f"{statistics.median(stats(r)):.1f}s" if stats(r) else "-"),
        linha("Tempo total", lambda r: f"{sum(stats(r)):.0f}s"),
    ]
    return cab + "\n" + "\n".join(linhas)


def _relatorio(resultados: list[dict]) -> str:
    partes = [f"# Qualidade de LLM local · {datetime.now():%Y-%m-%d %H:%M}\n", _tabela(resultados), ""]
    for r in resultados:
        partes.append(f"\n## {r['modelo']}\n")
        for it in r["itens"]:
            estado = "JSON válido de primeira" if it["ok"] and it["invalidas"] == 0 else (
                f"{it['invalidas']} saída(s) inválida(s)" + ("" if it["ok"] else ", FALHOU"))
            partes.append(f"### Ideia {it['n']} · {it['formato']} · {it['segundos']:.1f}s · {estado}\n> {it['ideia']}\n")
            if it["erros"]:
                partes.append("Motivos de rejeição: " + "; ".join(it["erros"]) + "\n")
            partes.append("```\n" + _texto_do_item(it) + "\n```\n")
    return "\n".join(partes)


async def principal(args) -> int:
    dados = Path(tempfile.mkdtemp(prefix="icap-qualidade-"))
    _preparar_ambiente(dados)
    from app import db, llm, pipeline, render, seed

    if not shutil.which("ollama") and not Path(_exe_ollama()).exists():
        print("Ollama não encontrado.", file=sys.stderr)
        return 1
    try:
        import httpx
        httpx.get(args.base_url, timeout=5).raise_for_status()
    except Exception as e:
        print(f"Servidor Ollama não responde em {args.base_url}: {e}", file=sys.stderr)
        return 1

    db.init()
    seed.run()
    perfil_id = db.one("SELECT id FROM perfis ORDER BY id LIMIT 1")["id"]
    est = _instrumentar(llm)
    await render.start()  # cards e slides são renderizados no Chromium, como no painel

    resultados = []
    try:
        for modelo in args.modelos:
            resultados.append(await _rodar_modelo(modelo, args.base_url, perfil_id, args.posts, args.slides, db, pipeline, est))
    finally:
        # solta a VRAM para o próximo modelo (ou para o resto do sistema)
        await render.stop()
        for modelo in args.modelos:
            subprocess.run([_exe_ollama(), "stop", modelo], capture_output=True)

    print("\n" + _tabela(resultados))
    for r in resultados:
        print(f"\n######## {r['modelo']} ########")
        for it in r["itens"]:
            print(f"\n--- ideia {it['n']} · {it['formato']} · {it['segundos']:.1f}s ---\n{_texto_do_item(it)}")

    saida = Path(args.saida) if args.saida else RAIZ / "scratch" / f"qualidade_llm_{datetime.now():%Y%m%d_%H%M%S}.md"
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(_relatorio(resultados), encoding="utf-8")
    print(f"\nRelatório completo: {saida}")
    shutil.rmtree(dados, ignore_errors=True)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelos", nargs="+", default=MODELOS_PADRAO)
    ap.add_argument("--base-url", default="http://localhost:11434")
    ap.add_argument("--posts", type=int, default=5, help="quantas ideias (cada uma vira um feed e um carrossel)")
    ap.add_argument("--slides", type=int, default=6)
    ap.add_argument("--saida", help="arquivo .md do relatório (padrão: scratch/qualidade_llm_<data>.md)")
    sys.exit(asyncio.run(principal(ap.parse_args())))
