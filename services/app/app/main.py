"""Painel web + ciclo de vida (agendador, supervisor do Telegram/túnel, servidor público, navegador do render)."""
import asyncio, json, re, secrets, time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import banco, config as C, crypto, db, ig, llm, marca as marca_mod, midia, pipeline, publico, render, scheduler, seed, settings, supervisor, telegram, voz
from .tunnel import tunel

WEB = Path(__file__).parent / "web"
templates = Jinja2Templates(directory=str(WEB / "templates"))
templates.env.filters["from_json"] = lambda v: json.loads(v) if v else []
_tasks: list[asyncio.Task] = []
_falhas: dict[str, list[float]] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    seed.run()
    await render.start()
    _tasks.extend([asyncio.create_task(scheduler.loop()), asyncio.create_task(supervisor.loop()),
                   asyncio.create_task(publico.servir())])
    yield
    publico.parar()
    for t in _tasks:
        t.cancel()
    await asyncio.gather(*_tasks, return_exceptions=True)
    await render.stop()


app = FastAPI(title="ic-ap", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=crypto.secret_key(), same_site="lax", max_age=7 * 86400, session_cookie="icap")


class NaoLogado(Exception):
    pass


class NaoConfigurado(Exception):
    pass


@app.exception_handler(NaoLogado)
async def _nao_logado(request: Request, exc: NaoLogado):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(NaoConfigurado)
async def _nao_configurado(request: Request, exc: NaoConfigurado):
    return RedirectResponse("/setup", status_code=303)


# ---------- helpers ----------
def configurado() -> bool:
    return bool(db.get_setting("admin_hash"))


def logado(request: Request) -> None:
    if not configurado():
        raise NaoConfigurado()
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


def _senha_ok(s: str) -> bool:
    return len(s) >= 8


# ---------- setup e auth ----------
@app.get("/setup")
def setup_page(request: Request):
    if configurado():
        return voltar(request, "/login")
    return render_page(request, "setup.html", erro=None)


@app.post("/setup")
async def setup(request: Request):
    if configurado():
        return voltar(request, "/login")
    f = dict((await request.form()).items())
    if not _senha_ok(f.get("senha", "")) or f.get("senha") != f.get("senha2"):
        return render_page(request, "setup.html", erro="A senha precisa ter 8+ caracteres e as duas precisam ser iguais.")
    db.set_setting("admin_hash", crypto.hash_password(f["senha"]))
    request.session.clear()
    request.session["ok"] = True
    return voltar(request, "/llm")


@app.get("/login")
def login_page(request: Request):
    if not configurado():
        raise NaoConfigurado()
    return render_page(request, "login.html", erro=None)


@app.post("/login")
async def login(request: Request):
    if not configurado():
        raise NaoConfigurado()
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
    posts = db.q("SELECT * FROM posts WHERE perfil_id=? AND estado NOT IN ('publicado','descartado','rascunho','agendado') "
                 "ORDER BY id DESC LIMIT 50", (pid,)) if pid else []
    return render_page(request, "fila.html", posts=posts, gerando=pid in pipeline.RUNNING,
                       perfil=pipeline.perfil(pid) if pid else None,
                       sem_llm=not db.q("SELECT 1 FROM llm_conexoes WHERE modelo!=''"))


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



# ---------- pauta do dia e agenda ----------
@app.get("/pauta")
def pauta_page(request: Request):
    logado(request)
    pid = perfil_atual_id(request)
    rasc = db.q("SELECT * FROM posts WHERE perfil_id=? AND estado='rascunho' ORDER BY COALESCE(grupo,id) DESC, variacao", (pid,)) if pid else []
    grupos: dict[int, list] = {}
    for r in rasc:
        grupos.setdefault(r["grupo"] or r["id"], []).append(r)
    return render_page(request, "pauta.html", grupos=list(grupos.values()), perfil=pipeline.perfil(pid) if pid else None,
                       gerando=pid in pipeline.RUNNING, tz=settings.tz(),
                       sem_llm=not db.q("SELECT 1 FROM llm_conexoes WHERE modelo!=''"))


@app.post("/pauta/gerar")
async def pauta_gerar(request: Request):
    logado(request)
    f = await form(request)
    pid = int(f["perfil_id"])
    if pid in pipeline.RUNNING:
        flash(request, "Já está gerando para este perfil.", "aviso")
    else:
        asyncio.create_task(pipeline.pauta(pid, int(f.get("noticias") or 3), int(f.get("variacoes") or 2),
                                           f.get("formato", "feed"), bool(f.get("com_print")), "manual"))
        flash(request, "Pesquisando as notícias em alta e gerando os rascunhos. Atualize a página em alguns instantes.")
    return voltar(request, "/pauta")


@app.post("/pauta/agendar")
async def pauta_agendar(request: Request):
    logado(request)
    dados = await request.form()
    if not secrets.compare_digest(str(dados.get("csrf", "")), request.session.get("csrf", "x")):
        raise HTTPException(403, "csrf")
    ids = [int(i) for i in dados.getlist("ids") if str(i).isdigit()]
    acao = dados.get("acao", "agendar")
    if not ids:
        flash(request, "Marque pelo menos um post.", "aviso")
    elif acao == "descartar":
        n = 0
        for i in ids:
            n += 1 if await pipeline.descartar(i) else 0
        flash(request, f"{n} descartado(s).")
    else:
        n = pipeline.agendar(ids, str(dados.get("quando", "")), int(dados.get("intervalo") or 60))
        flash(request, f"{n} post(s) agendado(s)." if n else "Data inválida ou posts sem imagem.", "ok" if n else "erro")
    return voltar(request, "/pauta")


@app.get("/agenda")
def agenda_page(request: Request):
    logado(request)
    pid = perfil_atual_id(request)
    posts = db.q("SELECT * FROM posts WHERE perfil_id=? AND estado='agendado' ORDER BY agendado_para", (pid,)) if pid else []
    for p in posts:
        p["quando"] = pipeline.local(p["agendado_para"])
    return render_page(request, "agenda.html", posts=posts, tz=settings.tz(), perfil=pipeline.perfil(pid) if pid else None)


@app.post("/posts/{post_id}/desagendar")
async def desagendar(request: Request, post_id: int):
    logado(request)
    await form(request)
    flash(request, "Voltou para os rascunhos." if pipeline.desagendar(post_id) else "Não foi possível.")
    return voltar(request, "/agenda")


@app.post("/posts/{post_id}/legenda")
async def editar_legenda(request: Request, post_id: int):
    logado(request)
    f = await form(request)
    db.x("UPDATE posts SET legenda=?, atualizado_em=? WHERE id=? AND estado IN ('aguardando_aprovacao','falhou')",
         (f.get("legenda", "")[:2200], db.now(), post_id))
    flash(request, "Legenda salva.")
    return voltar(request)


@app.post("/posts/{post_id}/hashtags")
async def hashtags(request: Request, post_id: int):
    logado(request)
    await form(request)
    flash(request, "Hashtags novas na legenda." if await pipeline.novas_hashtags(post_id) else "Não consegui gerar hashtags agora.",
          "ok")
    return voltar(request)


@app.post("/posts/{post_id}/{acao}")
async def acao_post(request: Request, post_id: int, acao: str):
    logado(request)
    await form(request)
    if acao in ("adaptar-story", "adaptar-feed"):
        try:
            novo = await pipeline.adaptar(post_id, acao.split("-")[1])
        except Exception as e:
            flash(request, f"Adaptar: {str(e)[:200]}", "erro")
            return voltar(request)
        flash(request, "Versão criada, veja na fila." if novo else "Esse post não pode ser adaptado (só imagens de feed ou story).", "ok" if novo else "aviso")
        return voltar(request)
    fn = {"aprovar": pipeline.aprovar, "refazer": pipeline.refazer, "descartar": pipeline.descartar}.get(acao)
    if not fn:
        raise HTTPException(404)
    flash(request, f"{acao.capitalize()}: {'ok' if await fn(post_id) else 'não foi possível (veja o erro no post)'}")
    return voltar(request)


@app.get("/cards/{nome}")
def card(request: Request, nome: str):
    logado(request)
    if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|mp4)", nome) or not (C.CARDS / nome).exists():
        raise HTTPException(404)
    return FileResponse(C.CARDS / nome, media_type="video/mp4" if nome.endswith(".mp4") else "image/jpeg")



# ---------- músicas (trilhas livres de direitos para os vídeos) ----------
MAX_MUSICA = 30 * 1024 * 1024


@app.get("/musicas")
def musicas_page(request: Request):
    logado(request)
    return render_page(request, "musicas.html", lista=[{"nome": p.name, "mb": round(p.stat().st_size / 1048576, 1)} for p in midia.musicas()])


@app.post("/musicas")
async def musicas_enviar(request: Request):
    logado(request)
    dados = await request.form()
    if not secrets.compare_digest(str(dados.get("csrf", "")), request.session.get("csrf", "x")):
        raise HTTPException(403, "csrf")
    ok = 0
    for arq in dados.getlist("arquivo"):
        nome = midia.nome_seguro(getattr(arq, "filename", "") or "")
        if not nome.lower().endswith(midia.EXT_MUSICA):
            flash(request, f"{nome or 'arquivo'}: formato não aceito (use mp3, m4a, wav, ogg ou aac).", "erro")
            continue
        conteudo = await arq.read()
        if len(conteudo) > MAX_MUSICA:
            flash(request, f"{nome}: maior que 30 MB.", "erro")
            continue
        C.MUSICAS.mkdir(parents=True, exist_ok=True)
        (C.MUSICAS / nome).write_bytes(conteudo)
        ok += 1
    if ok:
        flash(request, f"{ok} música(s) adicionada(s).")
    return voltar(request, "/musicas")


@app.post("/musicas/remover")
async def musicas_remover(request: Request):
    logado(request)
    f = await form(request)
    alvo = C.MUSICAS / midia.nome_seguro(f.get("nome", ""))
    if alvo.parent == C.MUSICAS and alvo.exists():
        alvo.unlink()
        flash(request, "Música removida.")
    return voltar(request, "/musicas")

# ---------- perfis ----------
@app.get("/perfis")
def perfis_page(request: Request):
    logado(request)
    return render_page(request, "perfis.html", lista=db.q("SELECT * FROM perfis ORDER BY id"))


def _metatmp(pid: int) -> list[dict]:
    raw = db.get_setting(f"metatmp:{pid}")
    if not raw:
        return []
    try:
        d = json.loads(crypto.dec(raw))
    except Exception:
        return []
    return d["paginas"] if d.get("exp", 0) > time.time() else []


@app.get("/perfis/{pid}")
def perfil_page(request: Request, pid: int):
    logado(request)
    p = pipeline.perfil(pid)
    if not p:
        raise HTTPException(404)
    return render_page(request, "perfil.html", p=p, marca=marca_mod.carregar(p), tem_logo=bool(marca_mod._logo_path(pid)),
                       fontes=marca_mod.NOMES_FONTE, token_mask=crypto.mask(crypto.dec(p["ig_token_enc"])),
                       conexoes=db.q("SELECT id, nome, modelo, padrao FROM llm_conexoes ORDER BY id"),
                       paginas=[{k: v for k, v in pg.items() if k != "token"} for pg in _metatmp(pid)])


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


@app.get("/perfis/{pid}/logo")
def perfil_logo(request: Request, pid: int):
    logado(request)
    f = marca_mod._logo_path(pid)
    if not f:
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "no-store"})


@app.post("/perfis/{pid}/marca")
async def perfil_marca(request: Request, pid: int):
    logado(request)
    dados = await request.form()
    if not secrets.compare_digest(str(dados.get("csrf", "")), request.session.get("csrf", "-")):
        raise HTTPException(403, "CSRF inválido")
    if not pipeline.perfil(pid):
        raise HTTPException(404)
    nova, avisos = marca_mod.definir(pid, **{k: str(dados.get(k) or "") for k in ("fundo", "texto", "acento", "fonte")})
    for a in avisos:
        flash(request, a, "aviso")
    if dados.get("remover_logo"):
        marca_mod.remover_logo(pid)
    arq = dados.get("logo")
    if arq is not None and getattr(arq, "filename", ""):
        try:
            marca_mod.salvar_logo(pid, await arq.read())
        except ValueError as e:
            flash(request, f"Logotipo: {e}.", "erro")
    db.log(pid, None, "marca_salva")
    flash(request, "Kit de marca salvo. Vale para os próximos cards.")
    return voltar(request, f"/perfis/{pid}")


@app.post("/perfis/{pid}")
async def perfil_salvar(request: Request, pid: int):
    logado(request)
    f = await form(request)
    if not pipeline.perfil(pid):
        raise HTTPException(404)
    horarios = ",".join(h.strip() for h in f.get("horarios", "").split(",") if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h.strip()))
    con = int(f["llm_conexao_id"]) if str(f.get("llm_conexao_id", "")).isdigit() else None
    db.x("UPDATE perfis SET nome=?,handle=?,ativo=?,ig_user_id=?,telegram_chat_id=?,llm_conexao_id=?,"
         "contexto_md=?,horarios=?,palavras_chave=?,max_idade_horas=?,musica_modo=? WHERE id=?",
         (f.get("nome", "").strip() or "Sem nome", f.get("handle", "").strip(), 1 if f.get("ativo") else 0,
          f.get("ig_user_id", "").strip(), f.get("telegram_chat_id", "").strip(), con,
          f.get("contexto_md", ""), horarios, f.get("palavras_chave", "").strip(),
          max(1, min(int(f.get("max_idade_horas") or 36), 720)),
          "aleatoria" if f.get("musica_modo") == "aleatoria" else "nenhuma", pid))
    if f.get("ig_token", "").strip():
        db.x("UPDATE perfis SET ig_token_enc=? WHERE id=?", (crypto.enc(f["ig_token"].strip()), pid))
    db.log(pid, None, "perfil_salvo")
    flash(request, "Perfil salvo.")
    return voltar(request, f"/perfis/{pid}")


@app.post("/perfis/{pid}/meta/buscar")
async def meta_buscar(request: Request, pid: int):
    """Assistente: troca o token curto por longo e lista as Páginas com Instagram. O App Secret não é guardado."""
    logado(request)
    f = await form(request)
    try:
        longo = await ig.token_longo(f.get("app_id", "").strip(), f.get("app_secret", "").strip(), f.get("token_curto", "").strip())
        pgs = await ig.paginas(longo)
        if not pgs:
            raise ig.MetaError("nenhuma Página com Instagram profissional ligado foi encontrada para este token (confira as permissões)")
        db.set_setting(f"metatmp:{pid}", crypto.enc(json.dumps({"exp": time.time() + 600, "paginas": pgs})))
        flash(request, f"{len(pgs)} Página(s) encontrada(s). Escolha qual usar neste perfil.")
    except Exception as e:
        flash(request, f"Meta: {str(e)[:250]}", "erro")
    return voltar(request, f"/perfis/{pid}")


@app.post("/perfis/{pid}/meta/usar")
async def meta_usar(request: Request, pid: int):
    logado(request)
    f = await form(request)
    pgs = _metatmp(pid)
    try:
        pg = pgs[int(f.get("idx", -1))]
    except (IndexError, ValueError):
        flash(request, "A lista expirou (10 min). Busque de novo.", "aviso")
        return voltar(request, f"/perfis/{pid}")
    db.x("UPDATE perfis SET ig_user_id=?, ig_token_enc=? WHERE id=?", (pg["ig_id"], crypto.enc(pg["token"]), pid))
    db.x("DELETE FROM settings WHERE k=?", (f"metatmp:{pid}",))
    db.log(pid, None, "meta_token", f"página {pg['nome']} / @{pg['ig_user']}")
    flash(request, f"Perfil ligado a @{pg['ig_user']} (Página {pg['nome']}). Teste em Conexões.")
    return voltar(request, f"/perfis/{pid}")


# ---------- LLM ----------
def _con_form(f: dict) -> dict:
    return {"id": f.get("id", ""), "nome": f.get("nome", "").strip(), "tipo": f.get("tipo", "openai"),
            "base_url": f.get("base_url", "").strip(), "modelo": f.get("modelo", "").strip(), "padrao": bool(f.get("padrao"))}


@app.get("/llm")
def llm_page(request: Request):
    logado(request)
    lista = db.q("SELECT * FROM llm_conexoes ORDER BY id")
    sel = request.query_params.get("editar")
    atual = next((c for c in lista if str(c["id"]) == sel), None)
    form_v = {**atual, "id": str(atual["id"]), "padrao": bool(atual["padrao"])} if atual else \
        {"id": "", "nome": "", "tipo": "openai", "base_url": "", "modelo": "", "padrao": not lista}
    return render_page(request, "llm.html", lista=lista, f=form_v, modelos=[], tipos=llm.TIPOS, dicas=llm.DICAS_URL)


@app.post("/llm/editar")
async def llm_editar(request: Request):
    logado(request)
    f = await form(request)
    v = _con_form(f)
    existente = db.one("SELECT * FROM llm_conexoes WHERE id=?", (int(v["id"]),)) if v["id"].isdigit() else None
    chave = f.get("api_key", "").strip() or (crypto.dec(existente["api_key_enc"]) if existente else "")
    if v["tipo"] not in llm.TIPOS:
        raise HTTPException(400, "tipo inválido")
    lista = db.q("SELECT * FROM llm_conexoes ORDER BY id")

    def pagina(modelos=None):
        return render_page(request, "llm.html", lista=lista, f=v, modelos=modelos or [], tipos=llm.TIPOS, dicas=llm.DICAS_URL)

    if f.get("acao") == "detectar":
        try:
            modelos, base = await llm.listar_modelos(v["tipo"], v["base_url"], chave)
        except Exception as e:
            flash(request, f"Não consegui listar os modelos: {str(e)[:300]}", "erro")
            return pagina()
        v["base_url"] = base or v["base_url"]
        if v["modelo"] not in modelos:
            v["modelo"] = modelos[0] if modelos else ""
        flash(request, f"{len(modelos)} modelo(s) encontrado(s). Escolha um e clique em Aplicar e testar." if modelos
              else "Conectou, mas nenhum modelo foi listado. Carregue um modelo no programa e tente de novo.",
              "ok" if modelos else "aviso")
        return pagina(modelos)

    # aplicar e testar
    if not v["nome"] or not v["modelo"]:
        flash(request, "Informe um nome e escolha o modelo (use Detectar modelos).", "erro")
        return pagina()
    if v["tipo"] in ("openai", "ollama") and not v["base_url"].startswith(("http://", "https://")):
        flash(request, "Informe a URL do servidor (começa com http:// ou https://).", "erro")
        return pagina()
    if existente:
        db.x("UPDATE llm_conexoes SET nome=?,tipo=?,base_url=?,api_key_enc=?,modelo=? WHERE id=?",
             (v["nome"], v["tipo"], v["base_url"], crypto.enc(chave), v["modelo"], existente["id"]))
        cid = existente["id"]
    else:
        cid = db.x("INSERT INTO llm_conexoes(nome,tipo,base_url,api_key_enc,modelo,padrao,criado_em) VALUES(?,?,?,?,?,0,?)",
                   (v["nome"], v["tipo"], v["base_url"], crypto.enc(chave), v["modelo"], db.now()))
    if v["padrao"] or db.one("SELECT COUNT(*) n FROM llm_conexoes WHERE padrao=1")["n"] == 0:
        db.x("UPDATE llm_conexoes SET padrao=CASE WHEN id=? THEN 1 ELSE 0 END", (cid,))
    r = await llm.testar({"tipo": v["tipo"], "base_url": v["base_url"], "modelo": v["modelo"], "api_key": chave})
    if r["ok"]:
        flash(request, f"Aplicado. Teste OK em {r['segundos']} s. Exemplo de manchete gerada: “{r['manchete']}”.")
    else:
        flash(request, f"Aplicado, mas o teste falhou: {r['erro']}", "erro")
    return voltar(request, f"/llm?editar={cid}")


@app.post("/llm/{cid}/{acao}")
async def llm_acao(request: Request, cid: int, acao: str):
    logado(request)
    await form(request)
    c = db.one("SELECT * FROM llm_conexoes WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404)
    if acao == "padrao":
        db.x("UPDATE llm_conexoes SET padrao=CASE WHEN id=? THEN 1 ELSE 0 END", (cid,))
    elif acao == "remover":
        db.x("DELETE FROM llm_conexoes WHERE id=?", (cid,))
        db.x("UPDATE perfis SET llm_conexao_id=NULL WHERE llm_conexao_id=?", (cid,))
        if not db.one("SELECT 1 FROM llm_conexoes WHERE padrao=1"):
            db.x("UPDATE llm_conexoes SET padrao=1 WHERE id=(SELECT MIN(id) FROM llm_conexoes)")
    elif acao == "testar":
        r = await llm.testar({**c, "api_key": crypto.dec(c["api_key_enc"])})
        flash(request, f"{c['nome']}: teste OK em {r['segundos']} s." if r["ok"] else f"{c['nome']}: {r['erro']}", "ok" if r["ok"] else "erro")
    else:
        raise HTTPException(404)
    return voltar(request, "/llm")


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


# ---------- conexões e configurações globais ----------
@app.get("/conexoes")
def conexoes_page(request: Request):
    logado(request)
    pid = perfil_atual_id(request)
    return render_page(request, "conexoes.html", perfil=pipeline.perfil(pid) if pid else None,
                       base=settings.base_url(), tunel=tunel, tem_tunel=bool(settings.tunnel_token()),
                       tg_token=crypto.mask(settings.telegram_token()), tz=settings.tz(),
                       hg_key=crypto.mask(banco.higgs_chave().split(':')[-1]),
                       wh={"url": db.get_setting("whisper_url"), "modelo": db.get_setting("whisper_model"), "chave": crypto.mask(settings.segredo("whisper_key"))},
                       tt={"url": db.get_setting("tts_url"), "modelo": db.get_setting("tts_model"), "voz": db.get_setting("tts_voz"), "chave": crypto.mask(settings.segredo("tts_key"))}, un_key=crypto.mask(settings.unsplash_key()))


@app.post("/config/{secao}")
async def config_salvar(request: Request, secao: str):
    logado(request)
    f = await form(request)
    if secao == "publico":
        url = f.get("public_base_url", "").strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            flash(request, "A URL pública precisa começar com https://", "erro")
        else:
            db.set_setting("public_base_url", url)
            flash(request, "URL pública salva.")
    elif secao == "tunel":
        if f.get("acao") == "remover":
            settings.guardar_segredo("tunnel_token", "")
            flash(request, "Túnel removido.")
        elif f.get("tunnel_token", "").strip():
            settings.guardar_segredo("tunnel_token", f["tunnel_token"].strip())
            flash(request, "Token do túnel salvo. O túnel (re)inicia em alguns segundos.")
        else:
            flash(request, "Cole o token do túnel.", "aviso")
    elif secao == "telegram":
        if f.get("acao") == "remover":
            settings.guardar_segredo("telegram_token", "")
            flash(request, "Bot do Telegram removido.")
        elif f.get("telegram_token", "").strip():
            settings.guardar_segredo("telegram_token", f["telegram_token"].strip())
            flash(request, "Token do bot salvo. O bot passa a escutar em alguns segundos.")
        else:
            flash(request, "Cole o token do bot.", "aviso")
    elif secao == "higgs":
        if f.get("acao") == "remover":
            settings.guardar_segredo("higgs_key", "")
            flash(request, "Chave do Higgsfield removida.")
        elif f.get("key_id", "").strip() and f.get("key_secret", "").strip():
            settings.guardar_segredo("higgs_key", f"{f['key_id'].strip()}:{f['key_secret'].strip()}")
            flash(request, "Chave do Higgsfield salva. Use “Testar” abaixo (gera uma imagem de verdade e gasta créditos).")
        else:
            flash(request, "Preencha o ID e o segredo da chave.", "aviso")
    elif secao in ("whisper", "tts"):
        if f.get("acao") == "remover":
            for k in ("url", "model"):
                db.set_setting(f"{secao}_{k}", "")
            settings.guardar_segredo(f"{secao}_key", "")
            if secao == "tts":
                db.set_setting("tts_voz", "")
            flash(request, "Configuração removida.")
        else:
            url = f.get("endereco", "").strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                flash(request, "O endereço precisa começar com http:// ou https:// (ex.: http://host.docker.internal:8000).", "erro")
            else:
                db.set_setting(f"{secao}_url", url)
                db.set_setting(f"{secao}_model", f.get("modelo", "").strip())
                if secao == "tts":
                    db.set_setting("tts_voz", f.get("voz", "").strip())
                if f.get("chave", "").strip():
                    settings.guardar_segredo(f"{secao}_key", f["chave"].strip())
                flash(request, "Salvo. Use “Testar” abaixo.")
    elif secao == "unsplash":
        if f.get("acao") == "remover":
            settings.guardar_segredo("unsplash_key", "")
            flash(request, "Chave do Unsplash removida.")
        elif f.get("chave", "").strip():
            settings.guardar_segredo("unsplash_key", f["chave"].strip())
            flash(request, "Chave do Unsplash salva.")
        else:
            flash(request, "Cole a chave de API.", "aviso")
    elif secao == "geral":
        tz = f.get("tz", "").strip()
        if settings.tz_valido(tz):
            db.set_setting("tz", tz)
            flash(request, "Fuso horário salvo.")
        else:
            flash(request, "Fuso inválido (exemplo: America/Sao_Paulo).", "erro")
    elif secao == "senha":
        if not crypto.check_password(f.get("atual", ""), db.get_setting("admin_hash")):
            flash(request, "Senha atual incorreta.", "erro")
        elif not _senha_ok(f.get("nova", "")) or f.get("nova") != f.get("nova2"):
            flash(request, "A nova senha precisa ter 8+ caracteres e as duas precisam ser iguais.", "erro")
        else:
            db.set_setting("admin_hash", crypto.hash_password(f["nova"]))
            flash(request, "Senha alterada.")
    else:
        raise HTTPException(404)
    return voltar(request, "/conexoes")


@app.post("/conexoes/{alvo}")
async def conexao_testar(request: Request, alvo: str):
    logado(request)
    f = await form(request)
    p = pipeline.perfil(int(f.get("perfil_id", 0)))
    try:
        if alvo == "meta":
            r = await ig.conferir(p["ig_user_id"], crypto.dec(p["ig_token_enc"]))
            flash(request, f"Meta OK: conta @{r['username']}.")
        elif alvo == "llm":
            con = pipeline.conexao_do_perfil(p)
            if not con:
                raise RuntimeError("nenhuma conexão de LLM configurada (menu LLM)")
            r = await llm.testar(con)
            flash(request, f"LLM OK ({con['nome']} / {con['modelo']}): {r['segundos']} s." if r["ok"] else f"LLM: {r['erro']}",
                  "ok" if r["ok"] else "erro")
        elif alvo == "telegram":
            if not telegram.ativo() or not p["telegram_chat_id"]:
                raise RuntimeError("falta o token do bot (acima) ou o chat_id do perfil")
            await telegram._call("sendMessage", data={"chat_id": p["telegram_chat_id"], "text": f"Teste do ic-ap: perfil {p['nome']}."})
            flash(request, "Telegram OK: mensagem de teste enviada.")
        elif alvo == "tts":
            audio = await voz.narrar("Teste de voz do ic-ap.")
            try:
                dur = (await midia.sondar(audio))["duracao"]
            finally:
                audio.unlink(missing_ok=True)
            flash(request, f"Voz OK: áudio de {dur:.1f} s gerado.")
        elif alvo == "whisper":
            amostra = C.DATA / "tmp" / f"teste_{secrets.token_hex(6)}.wav"
            amostra.parent.mkdir(parents=True, exist_ok=True)
            await midia._run("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=1", str(amostra))
            try:
                await voz.transcrever(amostra)
            finally:
                amostra.unlink(missing_ok=True)
            flash(request, "Transcrição OK: o servidor respondeu ao áudio de teste (um tom, sem fala, então não volta texto).")
        elif alvo == "banco":
            tmp = C.DATA / "tmp" / f"teste_{secrets.token_hex(6)}.jpg"
            try:
                item = await banco.baixar_uma("mountain lake", tmp)
            finally:
                tmp.unlink(missing_ok=True)
            flash(request, f"Imagens OK: recebi uma imagem de {item['fonte']}.")
        elif alvo == "publico":
            base = settings.base_url()
            if not base:
                raise RuntimeError("URL pública não configurada")
            nome = f"_teste_{secrets.token_hex(8)}.txt"
            (C.PUBLIC / nome).write_text("ok")
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                    r = await c.get(f"{base}/{nome}")
            finally:
                (C.PUBLIC / nome).unlink(missing_ok=True)
            if r.status_code == 200 and r.text.strip() == "ok":
                flash(request, "URL pública OK: a internet consegue buscar as imagens por esse endereço.")
            else:
                flash(request, f"A URL pública respondeu HTTP {r.status_code}. Confira o túnel e a rota (Service URL http://localhost:{C.PUBLIC_PORT}).", "erro")
        else:
            raise HTTPException(404)
    except HTTPException:
        raise
    except Exception as e:
        flash(request, f"{alvo}: falhou — {(str(e) or type(e).__name__)[:250]}", "erro")
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
