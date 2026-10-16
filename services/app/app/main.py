"""Dashboard web + ciclo de vida (agendador, Telegram, navegador do render)."""
import asyncio, re, secrets, time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import config as C, crypto, db, ig, pipeline, render, scheduler, seed, telegram

WEB = Path(__file__).parent / "web"
templates = Jinja2Templates(directory=str(WEB / "templates"))
_tasks: list[asyncio.Task] = []
_falhas: dict[str, list[float]] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    seed.run()
    await render.start()
    _tasks.append(asyncio.create_task(scheduler.loop()))
    if telegram.ativo():
        _tasks.append(asyncio.create_task(telegram.poll(pipeline.acao_telegram)))
    yield
    for t in _tasks:
        t.cancel()
    await render.stop()


app = FastAPI(title="ic-ap", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


class NaoLogado(Exception):
    pass


@app.exception_handler(NaoLogado)
async def _nao_logado(request: Request, exc: NaoLogado):
    return RedirectResponse("/login", status_code=303)


def _secret() -> str:
    import os
    return os.environ.get("APP_SECRET_KEY", "x" * 32)


app.add_middleware(SessionMiddleware, secret_key=_secret(), same_site="lax", max_age=7 * 86400, session_cookie="icap")


# ---------- helpers ----------
def logado(request: Request) -> None:
    if not request.session.get("ok"):
        raise NaoLogado()


def flash(request: Request, msg: str, tipo: str = "ok") -> None:
    request.session["flash"] = request.session.get("flash", []) + [[tipo, msg]]


async def form(request: Request) -> dict:
    """Lê o formulário e confere o CSRF."""
    f = dict((await request.form()).items())
    if not secrets.compare_digest(str(f.get("csrf", "")), request.session.get("csrf", "-")):
        raise HTTPException(403, "CSRF inválido")
    return f


def perfil_atual_id(request: Request):
    """Perfil selecionado no topo do painel (não consome as mensagens flash)."""
    ids = [p["id"] for p in db.q("SELECT id FROM perfis ORDER BY id")]
    atual = request.session.get("perfil_id")
    if atual not in ids:
        atual = ids[0] if ids else None
        request.session["perfil_id"] = atual
    return atual


def ctx(request: Request, **kw) -> dict:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_hex(16)
    perfis = db.q("SELECT id, nome, ativo FROM perfis ORDER BY id")
    atual = perfil_atual_id(request)
    msgs = request.session.pop("flash", [])
    return {"request": request, "csrf": request.session["csrf"], "perfis": perfis, "perfil_id": atual,
            "flashes": msgs, "mask": crypto.mask, **kw}


def render_page(request: Request, nome: str, **kw):
    return templates.TemplateResponse(request, nome, ctx(request, **kw))


def voltar(request: Request, destino: str = "/"):
    return RedirectResponse(destino, status_code=303)


# ---------- auth ----------
@app.get("/login")
def login_page(request: Request):
    return render_page(request, "login.html", erro=None)


@app.post("/login")
async def login(request: Request):
    ip = request.client.host if request.client else "?"
    agora = time.time()
    _falhas[ip] = [t for t in _falhas.get(ip, []) if agora - t < 300]
    if len(_falhas[ip]) >= 5:
        return render_page(request, "login.html", erro="Muitas tentativas. Espere 5 minutos.")
    f = dict((await request.form()).items())
    if crypto.check_password(str(f.get("senha", "")), db.get_setting("admin_hash")):
        request.session.clear()
        request.session["ok"] = True
        return RedirectResponse("/", status_code=303)
    _falhas[ip].append(agora)
    return render_page(request, "login.html", erro="Senha incorreta.")


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.post("/perfil-atual")
async def perfil_atual(request: Request):
    logado(request)
    f = await form(request)
    if db.one("SELECT 1 FROM perfis WHERE id=?", (int(f.get("perfil_id", 0)),)):
        request.session["perfil_id"] = int(f["perfil_id"])
    return voltar(request, f.get("next") or "/")


# ---------- fila ----------
@app.get("/")
def fila(request: Request):
    logado(request)
    pid = perfil_atual_id(request)
    posts = db.q("SELECT * FROM posts WHERE perfil_id=? AND estado NOT IN ('publicado','descartado') "
                 "ORDER BY id DESC LIMIT 50", (pid,)) if pid else []
    return render_page(request, "fila.html", posts=posts, gerando=pid in pipeline.RUNNING,
                       perfil=pipeline.perfil(pid) if pid else None)


@app.post("/gerar")
async def gerar(request: Request):
    logado(request)
    f = await form(request)
    pid = int(f["perfil_id"])
    if pid in pipeline.RUNNING:
        flash(request, "Já está gerando para este perfil.", "aviso")
    else:
        asyncio.create_task(pipeline.gerar(pid, 1, "manual"))
        flash(request, "Gerando um post novo. Atualize em alguns instantes.")
    return voltar(request)


@app.post("/posts/{post_id}/{acao}")
async def acao_post(request: Request, post_id: int, acao: str):
    logado(request)
    await form(request)
    fn = {"aprovar": pipeline.aprovar, "refazer": pipeline.refazer, "descartar": pipeline.descartar}.get(acao)
    if not fn:
        raise HTTPException(404)
    flash(request, f"{acao.capitalize()}: {'ok' if await fn(post_id) else 'não foi possível (veja o erro no post)'}")
    return voltar(request)


@app.post("/posts/{post_id}/legenda")
async def editar_legenda(request: Request, post_id: int):
    logado(request)
    f = await form(request)
    db.x("UPDATE posts SET legenda=?, atualizado_em=? WHERE id=? AND estado IN ('aguardando_aprovacao','falhou')",
         (f.get("legenda", "")[:2200], db.now(), post_id))
    flash(request, "Legenda salva.")
    return voltar(request)


@app.get("/cards/{nome}")
def card(request: Request, nome: str):
    logado(request)
    if not re.fullmatch(r"[0-9a-f]{32}\.jpg", nome) or not (C.CARDS / nome).exists():
        raise HTTPException(404)
    return FileResponse(C.CARDS / nome, media_type="image/jpeg")


# ---------- perfis ----------
@app.get("/perfis")
def perfis_page(request: Request):
    logado(request)
    return render_page(request, "perfis.html", lista=db.q("SELECT * FROM perfis ORDER BY id"))


@app.get("/perfis/{pid}")
def perfil_page(request: Request, pid: int):
    logado(request)
    p = pipeline.perfil(pid)
    if not p:
        raise HTTPException(404)
    return render_page(request, "perfil.html", p=p, token_mask=crypto.mask(crypto.dec(p["ig_token_enc"])))


@app.post("/perfis")
async def perfil_novo(request: Request):
    logado(request)
    f = await form(request)
    nome = f.get("nome", "").strip()
    if not nome:
        flash(request, "Informe um nome.", "erro")
        return voltar(request, "/perfis")
    pid = db.x("INSERT INTO perfis(nome,handle,ativo,criado_em) VALUES(?,?,0,?)", (nome, f.get("handle", ""), db.now()))
    flash(request, "Perfil criado (desligado). Preencha contexto, token e conexões.")
    return voltar(request, f"/perfis/{pid}")


@app.post("/perfis/{pid}")
async def perfil_salvar(request: Request, pid: int):
    logado(request)
    f = await form(request)
    if not pipeline.perfil(pid):
        raise HTTPException(404)
    horarios = ",".join(h.strip() for h in f.get("horarios", "").split(",") if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h.strip()))
    prov = f.get("llm_provider", "ollama")
    db.x("UPDATE perfis SET nome=?,handle=?,ativo=?,ig_user_id=?,telegram_chat_id=?,llm_provider=?,llm_model=?,"
         "contexto_md=?,horarios=?,palavras_chave=?,max_idade_horas=? WHERE id=?",
         (f.get("nome", "").strip() or "Sem nome", f.get("handle", "").strip(), 1 if f.get("ativo") else 0,
          f.get("ig_user_id", "").strip(), f.get("telegram_chat_id", "").strip(),
          prov if prov in ("ollama", "gemini", "anthropic") else "ollama", f.get("llm_model", "").strip(),
          f.get("contexto_md", ""), horarios, f.get("palavras_chave", "").strip(),
          max(1, min(int(f.get("max_idade_horas") or 36), 720)), pid))
    if f.get("ig_token", "").strip():
        db.x("UPDATE perfis SET ig_token_enc=? WHERE id=?", (crypto.enc(f["ig_token"].strip()), pid))
    db.log(pid, None, "perfil_salvo")
    flash(request, "Perfil salvo.")
    return voltar(request, f"/perfis/{pid}")


# ---------- feeds ----------
@app.get("/feeds")
def feeds_page(request: Request):
    logado(request)
    pid = perfil_atual_id(request)
    return render_page(request, "feeds.html", lista=db.q(
        "SELECT * FROM feeds WHERE perfil_id IS NULL OR perfil_id=? ORDER BY perfil_id IS NULL DESC, id", (pid,)))


@app.post("/feeds")
async def feed_novo(request: Request):
    logado(request)
    f = await form(request)
    url = f.get("url", "").strip()
    if not url.startswith(("http://", "https://")):
        flash(request, "URL inválida.", "erro")
        return voltar(request, "/feeds")
    escopo = perfil_atual_id(request) if f.get("escopo") == "perfil" else None
    db.x("INSERT INTO feeds(perfil_id,nome,url,tema,ativo) VALUES(?,?,?,?,1)",
         (escopo, f.get("nome", "").strip() or url, url, f.get("tema", "").strip()))
    return voltar(request, "/feeds")


@app.post("/feeds/{fid}/{acao}")
async def feed_acao(request: Request, fid: int, acao: str):
    logado(request)
    await form(request)
    if acao == "alternar":
        db.x("UPDATE feeds SET ativo=1-ativo WHERE id=?", (fid,))
    elif acao == "remover":
        db.x("DELETE FROM feeds WHERE id=?", (fid,))
    return voltar(request, "/feeds")


# ---------- conexões ----------
@app.get("/conexoes")
def conexoes_page(request: Request):
    logado(request)
    pid = perfil_atual_id(request)
    return render_page(request, "conexoes.html", perfil=pipeline.perfil(pid) if pid else None,
                       tg=telegram.ativo(), base=C.BASE_URL)


@app.post("/conexoes/{alvo}")
async def conexao_testar(request: Request, alvo: str):
    logado(request)
    f = await form(request)
    p = pipeline.perfil(int(f.get("perfil_id", 0)))
    try:
        if alvo == "meta":
            r = await ig.conferir(p["ig_user_id"], crypto.dec(p["ig_token_enc"]))
            flash(request, f"Meta OK: conta @{r['username']}.")
        elif alvo == "ollama":
            async with httpx.AsyncClient(timeout=15) as c:
                tags = (await c.get(f"{C.OLLAMA_URL}/api/tags")).json().get("models", [])
            nomes = [m["name"] for m in tags]
            modelo = p["llm_model"] or C.OLLAMA_MODEL
            if modelo in nomes:
                flash(request, f"Ollama OK, modelo {modelo} instalado.")
            else:
                flash(request, f"Ollama responde, mas o modelo {modelo} não está instalado. Rode: ollama pull {modelo}", "aviso")
        elif alvo == "telegram":
            if not telegram.ativo() or not p["telegram_chat_id"]:
                raise RuntimeError("falta TELEGRAM_BOT_TOKEN no .env ou o chat_id do perfil")
            await telegram._call("sendMessage", data={"chat_id": p["telegram_chat_id"], "text": f"Teste do ic-ap: perfil {p['nome']}."})
            flash(request, "Telegram OK: mensagem de teste enviada.")
        elif alvo == "publico":
            if not C.BASE_URL:
                raise RuntimeError("PUBLIC_BASE_URL vazia")
            nome = f"_teste_{secrets.token_hex(8)}.txt"
            (C.PUBLIC / nome).write_text("ok")
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                    r = await c.get(f"{C.BASE_URL}/{nome}")
            finally:
                (C.PUBLIC / nome).unlink(missing_ok=True)
            if r.status_code == 200 and r.text.strip() == "ok":
                flash(request, "URL pública OK: o túnel está servindo a pasta de imagens.")
            else:
                flash(request, f"URL pública respondeu HTTP {r.status_code}. Confira o túnel e a rota.", "erro")
        else:
            raise HTTPException(404)
    except HTTPException:
        raise
    except Exception as e:
        flash(request, f"{alvo}: falhou — {str(e)[:200]}", "erro")
    return voltar(request, "/conexoes")


# ---------- histórico ----------
@app.get("/historico")
def historico(request: Request):
    logado(request)
    pid = perfil_atual_id(request)
    return render_page(request, "historico.html",
                       posts=db.q("SELECT * FROM posts WHERE perfil_id=? AND estado IN ('publicado','descartado') "
                                  "ORDER BY id DESC LIMIT 100", (pid,)),
                       eventos=db.q("SELECT * FROM eventos WHERE perfil_id=? ORDER BY id DESC LIMIT 30", (pid,)))


@app.get("/saude")
def saude():
    return {"ok": True}
