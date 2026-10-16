"""Serviços simulados: RSS + artigos, Ollama, Graph API da Meta, Telegram e o 'nginx' público."""
import asyncio, json, os, re
from pathlib import Path
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response


def make(port: int) -> FastAPI:
    app = FastAPI()
    st = {"agente": [], "carrossel_modo": "ok", "llm_turnos": [], "openai_no_format": False, "openai_keys": [], "llm_mode": "ok", "llm_users": [], "graph": [], "tg": [], "tg_updates": [], "uid": 100, "graph_fail": False, "banco": []}
    app.state.st = st

    @app.get("/_st")
    def _st():
        return {k: v for k, v in st.items()}

    @app.post("/_reset")
    def _reset(request: Request):
        st.update(agente=[], carrossel_modo="ok", llm_turnos=[], llm_mode="ok", llm_users=[], graph=[], tg=[], tg_updates=[], graph_fail=False, openai_no_format=False, openai_keys=[], banco=[])
        return {}

    @app.post("/_set")
    async def _set(request: Request):
        st.update(await request.json())
        return {}

    @app.post("/_tg/push_msg")
    async def tg_push_msg(request: Request):
        st["uid"] += 1
        b = await request.json()
        m = {"message_id": st["uid"], "chat": {"id": b["chat_id"]}}
        if b.get("caption"):
            m["caption"] = b["caption"]
        if b.get("tipo") == "foto":
            m["photo"] = [{"file_id": "foto.jpg", "file_size": 1000}, {"file_id": "foto.jpg", "file_size": b.get("size", 5000)}]
        elif b.get("tipo") == "video":
            m["video"] = {"file_id": b.get("arquivo", "video.mp4"), "file_size": b.get("size", 5000)}
        elif b.get("tipo") == "texto":
            m["text"] = b["caption"]
        st["tg_updates"].append({"update_id": st["uid"], "message": m})
        return {}

    @app.get("/file/bot{token}/files/{nome}")
    def tg_file(token: str, nome: str):
        return Response((Path(os.environ["FAKE_MEDIA_DIR"]) / nome).read_bytes())

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
                        f"<pubDate>{now}</pubDate><description>IA e empresas</description></item>" for i in range(1, 41))
        return Response(f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{itens}</channel></rss>',
                        media_type="application/rss+xml")

    @app.get("/art/{n}")
    def art(n: int):
        par = "".join(f"<p>Parágrafo {k} da notícia {n}: a empresa anunciou que passa a usar inteligência artificial "
                      f"em atendimento, marketing e rotina, mantendo os dados sob controle próprio e avaliando custos.</p>"
                      for k in range(8))
        return Response(f"<html><head><title>Notícia {n}</title></head><body><article><h1>Notícia {n}</h1>{par}</article></body></html>",
                        media_type="text/html")

    def conteudo(user_text: str, system: str = "", turnos: int = 1) -> str:
        st["llm_users"].append(user_text)
        st["llm_turnos"].append(turnos)
        if "assistente de brainstorming" in system:
            r = st["agente"].pop(0) if st["agente"] else {"resposta": "Oi! Vamos montar seu perfil. Quem é você e o que faz?", "acao": "conversar"}
            base = {"perfil_md": "", "palavras_chave": "", "horarios": "", "marca": {"fundo": "", "texto": "", "acento": "", "fonte": ""}, "gerar": {"formato": "feed", "ideia": "", "n_slides": 0, "variacoes": 1}}
            return json.dumps({**base, **r}, ensure_ascii=False)
        if "monta um carrossel" in system:
            n = int(re.search(r"EXATAMENTE (\d+) slides", system).group(1))
            slides = [{"titulo": f"Slide {i} da ideia", "texto": ("palavra " * 50 if st["carrossel_modo"] == "estoura" and i == 2 else f"Texto curto do slide {i}.")}
                      for i in range(1, n + 1)]
            if st["carrossel_modo"] == "estoura":
                st["carrossel_modo"] = "ok"
            return json.dumps({"slides": slides, "legenda_instagram": "Carrossel sobre a ideia.", "cta": "Salve este post.",
                               "hashtags": ["ia", "#Empresas", "tecnologia", "gestão", "#ia", "dados privados", "ysafe", "saude digital"]}, ensure_ascii=False)
        if "escreve um post de Instagram (imagem" in system:
            v = re.search(r"Estratégia desta versão: ([^.]*)\.", user_text)
            return json.dumps({"manchete_curta": "Dado na mão da empresa" + (f" ({v.group(1)[:12]})" if v else ""),
                               "texto_card": "Não é moda, é controle.\n\nPergunte onde o dado fica.",
                               "legenda_instagram": "Minha ideia de hoje: " + user_text[:60].replace("\n", " "), "cta": "Comente o que você acha.",
                               "hashtags": ["#ia", "#empresas", "#dados", "#privacidade", "#tecnologia", "#gestao", "#ysafe", "#startup"]}, ensure_ascii=False)
        if "card de citação" in system:
            return json.dumps({"frase": "Quem controla o dado controla o jogo.", "autor": "Emerson Assis",
                               "legenda": "Minha frase de hoje.\n\nComente o que você acha. #ia #dados #empresas #gestao #ysafe",
                               "busca": "calm mountain"}, ensure_ascii=False)
        if "cria um meme" in system:
            return json.dumps({"topo": "Quando o relatório fecha", "base": "mas o dado era de outro cliente",
                               "legenda": "Todo mundo já passou por isso. #ia #dados #humor #empresas #gestao", "busca": "surprised office"}, ensure_ascii=False)
        if "texto curto que aparece NA TELA" in system:
            return json.dumps({"texto": "Disciplina sustenta o resultado. Sempre."}, ensure_ascii=False)
        if "sugere hashtags" in system:
            return json.dumps({"hashtags": ["#novatag1", "#novatag2", "#novatag3", "#novatag4"]})
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
        return content

    # --- Ollama ---
    @app.get("/api/tags")
    def tags():
        return {"models": [{"name": "teste:7b"}]}

    @app.post("/api/chat")
    async def chat(request: Request):
        b = await request.json()
        return {"message": {"role": "assistant", "content": conteudo(b["messages"][-1]["content"], b["messages"][0]["content"], len(b["messages"]) - 1)}}

    # --- OpenAI-compatível (LM Studio, Jan, llama.cpp…) ---
    @app.get("/v1/models")
    def v1_models(request: Request):
        st["openai_keys"].append(request.headers.get("authorization", ""))
        return {"data": [{"id": "modelo-b"}, {"id": "modelo-a"}]}

    @app.post("/v1/chat/completions")
    async def v1_chat(request: Request):
        b = await request.json()
        if st["openai_no_format"] and "response_format" in b:
            return JSONResponse({"error": {"message": "response_format não suportado"}}, status_code=400)
        return {"choices": [{"message": {"role": "assistant", "content": conteudo(b["messages"][-1]["content"], b["messages"][0]["content"], len(b["messages"]) - 1)}}]}

    # --- Gemini ---
    @app.get("/gemini/models")
    def gem_models(request: Request):
        if request.headers.get("x-goog-api-key") != "g-key":
            return JSONResponse({"error": {"message": "API key not valid"}}, status_code=400)
        return {"models": [{"name": "models/g-flash", "supportedGenerationMethods": ["generateContent"]},
                           {"name": "models/emb", "supportedGenerationMethods": ["embedContent"]}]}

    @app.post("/gemini/models/{m}:generateContent")
    async def gem_gen(m: str, request: Request):
        b = await request.json()
        return {"candidates": [{"content": {"parts": [{"text": conteudo(b["contents"][-1]["parts"][0]["text"], b["systemInstruction"]["parts"][0]["text"], len(b["contents"]))}]}}]}

    # --- Anthropic ---
    @app.get("/anthropic/models")
    def ant_models(request: Request):
        if request.headers.get("x-api-key") != "a-key":
            return JSONResponse({"error": {"message": "invalid x-api-key"}}, status_code=401)
        return {"data": [{"id": "claude-test"}]}

    @app.post("/anthropic/messages")
    async def ant_msg(request: Request):
        b = await request.json()
        return {"content": [{"type": "text", "text": conteudo(b["messages"][-1]["content"], b.get("system", ""), len(b["messages"]))}]}

    # --- assistente de token da Meta ---
    @app.get("/graph/oauth/access_token")
    def g_oauth(request: Request):
        p = request.query_params
        if p.get("client_secret") != "segredo-app" or p.get("fb_exchange_token") != "TOKEN-CURTO":
            return JSONResponse({"error": {"message": "Invalid client secret", "code": 1}}, status_code=400)
        return {"access_token": "LONGO123", "token_type": "bearer"}

    @app.get("/graph/me/accounts")
    def g_accounts(request: Request):
        if request.query_params.get("access_token") != "LONGO123":
            return JSONResponse({"error": {"message": "token inválido", "code": 190}}, status_code=400)
        return {"data": [
            {"id": "P1", "name": "Página Sem Instagram", "access_token": "PAGETOKEN-sem"},
            {"id": "P2", "name": "Página do Emerson", "access_token": "PAGETOKEN-xyz",
             "instagram_business_account": {"id": "1784", "username": "emerson_teste"}}]}

    # --- Graph API ---
    @app.post("/graph/{ig}/media")
    async def g_media(ig: str, request: Request):
        p = dict(request.query_params)
        if st["graph_fail"]:
            return JSONResponse({"error": {"message": "Invalid OAuth access token.", "code": 190}}, status_code=400)
        if p.get("media_type") == "CAROUSEL":
            st["graph"].append(["media", p])
            filhos = p.get("children", "").split(",")
            if len(filhos) < 2 or not all(f.startswith("ITEM") for f in filhos):
                return JSONResponse({"error": {"message": "children inválidos", "code": 100}}, status_code=400)
            return {"id": "CARR1"}
        url = p.get("image_url") or p.get("video_url")
        async with httpx.AsyncClient() as c:  # a Meta precisa conseguir BUSCAR a mídia pela URL pública
            r = await c.get(url)
        jpeg = r.content[:2] == b"\xff\xd8"
        mp4 = r.content[4:8] == b"ftyp"
        if r.status_code != 200 or not (jpeg if "image_url" in p else mp4):
            return JSONResponse({"error": {"message": "Falha ao baixar a mídia", "code": 9004}}, status_code=400)
        st["graph"].append(["media", p])
        if p.get("is_carousel_item") == "true":
            return {"id": f"ITEM{sum(1 for g in st['graph'] if g[0] == 'media')}"}
        return {"id": "CONT1"}

    @app.get("/graph/{cid}")
    def g_status(cid: str, request: Request):
        if not (cid.startswith(("ITEM", "CARR")) or cid == "CONT1"):
            return {"username": "emerson_teste", "id": cid}
        if "status_code" not in request.query_params.get("fields", ""):
            return {"username": "emerson_teste", "id": cid}
        n = sum(1 for g in st["graph"] if g[0] == "status") + 1
        st["graph"].append(["status", {"id": cid}])
        return {"status_code": "FINISHED" if n % 2 == 0 else "IN_PROGRESS"}

    @app.post("/graph/{ig}/media_publish")
    async def g_pub(ig: str, request: Request):
        st["graph"].append(["publish", dict(request.query_params)])
        return {"id": "MEDIA9"}

    @app.get("/graph/PAGE1/content_publishing_limit")
    def g_limit_page():
        return JSONResponse({"error": {"message": "(#100) Tried accessing nonexisting field (content_publishing_limit)", "code": 100}}, status_code=400)

    @app.get("/graph/{ig}/content_publishing_limit")
    def g_limit(ig: str):
        return {"data": [{"quota_usage": 1}]}

    # --- bancos de imagens ---
    @app.get("/img/foto.jpg")
    def img_foto():
        return Response((Path(os.environ["FAKE_MEDIA_DIR"]) / "foto.jpg").read_bytes(), media_type="image/jpeg")

    @app.get("/pexels/v1/search")
    def pexels(request: Request):
        st["banco"].append(["pexels", request.headers.get("authorization", ""), dict(request.query_params)])
        return {"photos": [{"photographer": "Ana Souza", "url": "https://pexels.test/foto/1", "src": {"large2x": f"http://127.0.0.1:{port}/img/foto.jpg"}}]}

    @app.get("/unsplash/search/photos")
    def unsplash(request: Request):
        st["banco"].append(["unsplash", request.headers.get("authorization", ""), dict(request.query_params)])
        return {"results": [{"user": {"name": "Bruno Lima"}, "links": {"html": "https://unsplash.test/p/1", "download_location": f"http://127.0.0.1:{port}/unsplash/dl/1"},
                             "urls": {"regular": f"http://127.0.0.1:{port}/img/foto.jpg"}}]}

    @app.get("/unsplash/dl/{n}")
    def unsplash_dl(n: int, request: Request):
        st["banco"].append(["unsplash-download", request.headers.get("authorization", ""), {}])
        return {"url": "x"}

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
        if metodo == "getFile":
            return {"ok": True, "result": {"file_path": f"files/{form['file_id']}"}}
        st["tg"].append([metodo, {k: (v if isinstance(v, str) else "<arquivo>") for k, v in form.items()}])
        return {"ok": True, "result": {"message_id": 555}}

    return app
