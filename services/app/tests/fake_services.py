"""Serviços simulados: RSS + artigos, Ollama, Graph API da Meta, Telegram e o 'nginx' público."""
import asyncio, json, os
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles


def make(public_dir: str, port: int) -> FastAPI:
    app = FastAPI()
    st = {"llm_mode": "ok", "llm_users": [], "graph": [], "tg": [], "tg_updates": [], "uid": 100, "graph_fail": False}
    app.state.st = st
    os.makedirs(public_dir, exist_ok=True)
    app.mount("/public", StaticFiles(directory=public_dir), name="public")

    @app.get("/_st")
    def _st():
        return {k: v for k, v in st.items()}

    @app.post("/_reset")
    def _reset(request: Request):
        st.update(llm_mode="ok", llm_users=[], graph=[], tg=[], tg_updates=[], graph_fail=False)
        return {}

    @app.post("/_set")
    async def _set(request: Request):
        st.update(await request.json())
        return {}

    @app.post("/_tg/push")
    async def tg_push(request: Request):
        st["uid"] += 1
        b = await request.json()
        st["tg_updates"].append({"update_id": st["uid"], "callback_query": {
            "id": f"cb{st['uid']}", "data": b["data"], "message": {"chat": {"id": b["chat_id"]}}}})
        return {}

    # --- RSS + artigos ---
    @app.get("/feed.xml")
    def feed():
        now = format_datetime(datetime.now(timezone.utc))
        itens = "".join(f"<item><title>IA muda a empresa {i}</title><link>http://127.0.0.1:{port}/art/{i}</link>"
                        f"<pubDate>{now}</pubDate><description>IA e empresas</description></item>" for i in range(1, 13))
        return Response(f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{itens}</channel></rss>',
                        media_type="application/rss+xml")

    @app.get("/art/{n}")
    def art(n: int):
        par = "".join(f"<p>Parágrafo {k} da notícia {n}: a empresa anunciou que passa a usar inteligência artificial "
                      f"em atendimento, marketing e rotina, mantendo os dados sob controle próprio e avaliando custos.</p>"
                      for k in range(8))
        return Response(f"<html><head><title>Notícia {n}</title></head><body><article><h1>Notícia {n}</h1>{par}</article></body></html>",
                        media_type="text/html")

    # --- Ollama ---
    @app.get("/api/tags")
    def tags():
        return {"models": [{"name": "teste:7b"}]}

    @app.post("/api/chat")
    async def chat(request: Request):
        b = await request.json()
        st["llm_users"].append(b["messages"][-1]["content"])
        ok = {"manchete_curta": "IA vira prioridade nas empresas",
              "minha_reacao": "Não é moda, é controle.\n\nMinha leitura: pergunte onde o dado fica.",
              "legenda_instagram": "Minha leitura sobre a notícia. #ia #empresas #tecnologia",
              "fonte": "Feed Teste", "confianca": "alta"}
        if st["llm_mode"] == "bad_then_ok" and len(st["llm_users"]) == 1:
            content = json.dumps({"manchete_curta": "só isso"})
        elif st["llm_mode"] == "always_bad":
            content = "isto não é json"
        elif st["llm_mode"] == "long_then_ok" and len(st["llm_users"]) == 1:
            content = json.dumps({**ok, "minha_reacao": "palavra " * 90})
        else:
            content = json.dumps(ok, ensure_ascii=False)
        return {"message": {"role": "assistant", "content": content}}

    # --- Graph API ---
    @app.post("/graph/{ig}/media")
    async def g_media(ig: str, request: Request):
        p = dict(request.query_params)
        if st["graph_fail"]:
            return JSONResponse({"error": {"message": "Invalid OAuth access token.", "code": 190}}, status_code=400)
        async with httpx.AsyncClient() as c:  # a Meta precisa conseguir BUSCAR a imagem pela URL pública
            r = await c.get(p["image_url"])
        if r.status_code != 200 or r.content[:2] != b"\xff\xd8":
            return JSONResponse({"error": {"message": "Falha ao baixar a imagem", "code": 9004}}, status_code=400)
        st["graph"].append(["media", p])
        return {"id": "CONT1"}

    @app.get("/graph/CONT1")
    def g_status():
        n = sum(1 for g in st["graph"] if g[0] == "status") + 1
        st["graph"].append(["status", {}])
        return {"status_code": "FINISHED" if n > 1 else "IN_PROGRESS"}

    @app.post("/graph/{ig}/media_publish")
    async def g_pub(ig: str, request: Request):
        st["graph"].append(["publish", dict(request.query_params)])
        return {"id": "MEDIA9"}

    @app.get("/graph/{ig}/content_publishing_limit")
    def g_limit(ig: str):
        return {"data": [{"quota_usage": 1}]}

    @app.get("/graph/{ig}")
    def g_conta(ig: str):
        return {"username": "emerson_teste", "id": ig}

    # --- Telegram ---
    @app.post("/bot{token}/{metodo}")
    async def tg(token: str, metodo: str, request: Request):
        if metodo == "getUpdates":
            if not st["tg_updates"]:
                await asyncio.sleep(0.2)
                return {"ok": True, "result": []}
            out, st["tg_updates"] = st["tg_updates"], []
            return {"ok": True, "result": out}
        form = await request.form()
        st["tg"].append([metodo, {k: (v if isinstance(v, str) else "<arquivo>") for k, v in form.items()}])
        return {"ok": True, "result": {"message_id": 555}}

    return app
