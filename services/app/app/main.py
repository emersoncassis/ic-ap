"""Painel web + ciclo de vida (agendador, supervisor do Telegram/túnel, servidor público, navegador do render)."""
import asyncio, json, re, secrets, time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import banco, config as C, crypto, db, distribuicao, escritorio, hardware, ig, llm, llm_local, marca as marca_mod, meta_ai, midia, pipeline, publico, render, scheduler, seed, settings, supervisor, tarefas, telegram, voz, vozes, wizard
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
    _tasks.clear()
    await render.stop()


app = FastAPI(title="ic-ap", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=crypto.secret_key(), same_site="lax", max_age=7 * 86400, session_cookie="icap")

if (WEB / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(WEB / "assets")), name="assets")



@app.middleware("http")
async def _bloquear_origem_cruzada(request: Request, call_next):
    """Defesa contra CSRF também nas rotas JSON (que não usam o token do formulário): se o navegador
    informa a origem de um POST e ela não é este mesmo site, a requisição é recusada."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origem = request.headers.get("origin")
        if origem and urlparse(origem).netloc != request.headers.get("host", ""):
            return PlainTextResponse("Origem não permitida", status_code=403)
    return await call_next(request)


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
    destino = "/llm" if db.q("SELECT 1 FROM perfis LIMIT 1") else "/wizard"
    return voltar(request, destino)


@app.get("/login")
def login_page(request: Request):
    if not configurado():
        raise NaoConfigurado()
    return render_page(request, "login.html", erro=None)


@app.post("/login")
async def login(request: Request):
    if not configurado():
        raise NaoConfigurado()
    # Limite de tentativas para TODOS os clientes: atrás de túnel/proxy toda requisição parece "local",
    # então isentar o localhost deixava a senha sem proteção contra força bruta.
    ip = request.client.host if request.client else "?"  # não confiar em cabeçalhos X-Forwarded (falsificáveis)
    agora = time.time()
    _falhas[ip] = [t for t in _falhas.get(ip, []) if agora - t < 300]
    if len(_falhas[ip]) >= 10:
        return render_page(request, "login.html", erro="Muitas tentativas. Espere 5 minutos.")
    f = dict((await request.form()).items())
    if crypto.check_password(str(f.get("senha", "")), db.get_setting("admin_hash")):
        request.session.clear()
        request.session["ok"] = True
        _falhas.pop(ip, None)
        return RedirectResponse("/", status_code=303)
    _falhas.setdefault(ip, []).append(agora)
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


# ---------- Wizard Inteligente de Criação de Perfil ----------
@app.get("/wizard")
def wizard_page(request: Request):
    logado(request)
    return render_page(request, "wizard.html", pacotes_feeds=wizard.PACOTES_FEEDS)


@app.post("/wizard/gerar-contexto")
async def wizard_gerar_contexto(request: Request):
    logado(request)
    dados = await request.json()
    tipo = dados.get("tipo", "entrevista")
    nome = dados.get("nome", "").strip() or "Criador"
    handle = dados.get("handle", "").strip() or "criador"
    
    if tipo == "meta":
        rel = dados.get("relatorio_meta", "").strip()
        analise = await wizard.analisar_relatorio_meta_ai(rel, nome, handle)
        return {
            "ok": True,
            "contexto": analise["contexto_md"],
            "palavras_chave": analise["palavras_chave"],
            "nicho": analise.get("nicho", ""),
            "feeds": analise.get("feeds_sugeridos", []),
            "pacote_id": analise.get("pacote_id", ""),
        }
    else:
        contexto = await wizard.gerar_contexto_da_entrevista(
            nome=nome,
            handle=handle,
            nicho=dados.get("nicho", "").strip(),
            estilo=dados.get("estilo", "").strip(),
            temas=dados.get("temas", "").strip(),
            inimigos=dados.get("inimigos", "").strip(),
        )
        return {"ok": True, "contexto": contexto}


@app.post("/wizard/telegram-detectar")
async def wizard_telegram_detectar(request: Request):
    logado(request)
    dados = await request.json()
    token = dados.get("token", "").strip()
    
    if token:
        settings.guardar_segredo("telegram_token", token)
    
    me = await telegram.obter_me()
    if not me:
        return {"ok": False, "erro": "Token do bot inválido ou o Telegram não respondeu. Confira o token no @BotFather."}
    
    chat = await telegram.detectar_chat_recente()
    if chat:
        await telegram.avisar(chat["chat_id"], f"🎉 Olá, {chat['nome']}! Seu Telegram foi conectado com sucesso ao ic-ap.")
        return {
            "ok": True,
            "chat_id": chat["chat_id"],
            "nome": chat["nome"],
            "username": chat.get("username", ""),
        }
    
    bot_user = me.get("username", "")
    return {
        "ok": False,
        "erro": f"Bot @{bot_user} conectado! Abra uma conversa com ele, envie um 'Oi' e clique aqui novamente.",
    }


@app.post("/wizard/concluir")
async def wizard_concluir(request: Request):
    logado(request)
    f = await form(request)
    nome = f.get("nome", "").strip()
    if not nome:
        flash(request, "Informe seu nome.", "erro")
        return voltar(request, "/wizard")
    
    tg_token = f.get("telegram_token", "").strip()
    if tg_token:
        settings.guardar_segredo("telegram_token", tg_token)

    pacote_feeds = f.get("pacote_feeds", "ia_privada_seguranca").strip()
    palavras_chave = f.get("palavras_chave", "").strip()
    custom_feed_url = f.get("custom_feed_url", "").strip()
    custom_feed_nome = f.get("custom_feed_nome", "").strip()
    feeds_custom = [(custom_feed_nome or custom_feed_url, custom_feed_url, "personalizado")] if custom_feed_url else []

    # Feeds sugeridos do Meta AI enviados pelo wizard
    feeds_meta_json = f.get("feeds_meta_json", "").strip()
    if feeds_meta_json:
        try:
            extra_meta = json.loads(feeds_meta_json)
            for item in extra_meta:
                if isinstance(item, dict) and item.get("url"):
                    feeds_custom.append((item.get("nome") or item["url"], item["url"], item.get("tema", "meta-ai")))
        except Exception:
            pass

    pid = wizard.criar_perfil_wizard(
        nome=nome,
        handle=f.get("handle", "").strip(),
        contexto_md=f.get("contexto_md", "").strip(),
        palavras_chave=palavras_chave,
        pacote_feeds=pacote_feeds,
        feeds_custom=feeds_custom,
        telegram_chat_id=f.get("telegram_chat_id", "").strip(),
        ativo=f.get("ativo", "1") == "1",
        meta_ai_analise=f.get("meta_ai_analise", "").strip(),
    )
    request.session["perfil_id"] = pid
    
    # Inicia captura de notícias relevantes para o perfil recém-configurado
    tarefas.disparar(pipeline.buscar_noticias(pid, "wizard_inicial", n=2))

    flash(request, f"🎉 Perfil '{nome}' criado e feeds vinculados com sucesso! Pautas e notícias relevantes estão sendo capturadas.")
    return voltar(request, "/")


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
        tarefas.disparar(pipeline.gerar(pid, 1, "manual"))
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
        tarefas.disparar(pipeline.pauta(pid, int(f.get("noticias") or 3), int(f.get("variacoes") or 2),
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
    if acao == "animar-ia":
        tarefas.disparar(pipeline.animar_post(post_id))
        flash(request, "Gerando o vídeo por IA em segundo plano (alguns minutos, gasta créditos). Ele aparece na fila quando terminar.", "aviso")
        return voltar(request)
    fn = {"aprovar": pipeline.aprovar, "refazer": pipeline.refazer, "descartar": pipeline.descartar}.get(acao)
    if not fn:
        raise HTTPException(404)
    flash(request, f"{acao.capitalize()}: {'ok' if await fn(post_id) else 'não foi possível (veja o erro no post)'}")
    return voltar(request)


# ---------- central de agentes & skills especialistas ----------
@app.get("/agentes")
def agentes_page(request: Request):
    logado(request)
    pid = perfil_atual_id(request)
    p = pipeline.perfil(pid) if pid else None
    conexoes = db.q("SELECT id, nome, tipo, modelo, padrao FROM llm_conexoes ORDER BY id")
    con_atual = pipeline.conexao_do_perfil(p) if p else None
    return render_page(request, "agentes.html", perfil=p,
                       llm_conexoes=conexoes, conexao_atual=con_atual,
                       sem_llm=not db.q("SELECT 1 FROM llm_conexoes WHERE modelo!=''"))


@app.get("/escritorio")
def escritorio_page(request: Request):
    logado(request)
    pid = perfil_atual_id(request)
    estado = escritorio.obter_estado_escritorio(pid)
    p = pipeline.perfil(pid) if pid else None
    conexoes = db.q("SELECT id, nome, tipo, modelo, padrao FROM llm_conexoes ORDER BY id")
    con_atual = pipeline.conexao_do_perfil(p) if p else None
    return render_page(request, "escritorio.html", llm_conexoes=conexoes, conexao_atual=con_atual, **estado)


@app.post("/api/perfil/definir-llm")
async def api_perfil_definir_llm(request: Request):
    logado(request)
    dados = await request.json()
    pid = int(dados.get("perfil_id") or perfil_atual_id(request) or 0)
    llm_id = dados.get("llm_conexao_id")
    if not pid:
        raise HTTPException(400, "Nenhum perfil selecionado.")
    if llm_id and str(llm_id).isdigit():
        db.x("UPDATE perfis SET llm_conexao_id=? WHERE id=?", (int(llm_id), pid))
    else:
        db.x("UPDATE perfis SET llm_conexao_id=NULL WHERE id=?", (pid,))
    db.log(pid, None, "perfil_llm_alterado", f"Modelo LLM dos agentes alterado para conexão #{llm_id}")
    return {"ok": True, "perfil_id": pid, "llm_conexao_id": llm_id}


@app.get("/api/escritorio/status")
def api_escritorio_status(request: Request, pid: int | None = None):
    logado(request)
    perfil_id = pid if pid is not None else perfil_atual_id(request)
    return escritorio.obter_estado_escritorio(perfil_id)


@app.post("/api/escritorio/disparar")
async def api_escritorio_disparar(request: Request):
    logado(request)
    dados = await form(request)
    pid = int(dados.get("perfil_id") or perfil_atual_id(request) or 0)
    if not pid:
        raise HTTPException(400, "Nenhum perfil selecionado.")
    if pid in pipeline.RUNNING:
        return {"ok": False, "mensagem": "Este perfil já está em processo de geração agora."}
    tarefas.disparar(pipeline.gerar(pid, 1, "escritorio"))
    db.log(pid, None, "escritorio_disparar", "Geração disparada pela central do escritório")
    return {"ok": True, "mensagem": "Geração disparada com sucesso! Observe os agentes no escritório."}


@app.post("/api/agentes/executar")
async def api_agentes_executar(request: Request):
    logado(request)
    dados = await request.json()
    agente_nome = dados.get("agente", "").strip().lower()
    entrada = dados.get("entrada", "").strip()
    pid = int(dados.get("perfil_id") or perfil_atual_id(request) or 0)

    # 1. Ativos visuais / vetoriais sem necessidade de LLM
    if agente_nome in ("vector_badge", "badge"):
        from .agentes.vector_art import VectorArtAgente
        from .vectorcraft import renderizar_svg_para_png
        art = VectorArtAgente()
        estilo = dados.get("estilo") or "neon_ciano"
        res = art.gerar_badge(texto=entrada or "DESTAQUE", estilo=estilo)
        C.CARDS.mkdir(parents=True, exist_ok=True)
        nome_base = f"badge_{secrets.token_hex(8)}"
        svg_path = C.CARDS / f"{nome_base}.svg"
        svg_path.write_text(res["svg"], encoding="utf-8")
        card_nome = svg_path.name
        try:
            png_path = C.CARDS / f"{nome_base}.png"
            final_path = await renderizar_svg_para_png(res["svg"], png_path, largura=res["largura"], altura=res["altura"])
            if final_path.exists() and final_path.stat().st_size > 0:
                card_nome = final_path.name
        except Exception:
            pass
        out_badge = {"png_url": f"/cards/{card_nome}", "svg": res["svg"]}
        return {"ok": True, "agente": "VectorCraft Badge", "resultado": out_badge, "saida": out_badge}

    if agente_nome in ("vector_overlay", "overlay"):
        from .agentes.vector_art import VectorArtAgente
        from .vectorcraft import renderizar_svg_para_png
        art = VectorArtAgente()
        res = art.gerar_overlay_reels(titulo=entrada or "GANCHO REELS 2026", subtitulo="Dicas Práticas", badge_texto="DESTAQUE")
        C.CARDS.mkdir(parents=True, exist_ok=True)
        nome_base = f"overlay_{secrets.token_hex(8)}"
        svg_path = C.CARDS / f"{nome_base}.svg"
        svg_path.write_text(res["svg"], encoding="utf-8")
        card_nome = svg_path.name
        try:
            png_path = C.CARDS / f"{nome_base}.png"
            final_path = await renderizar_svg_para_png(res["svg"], png_path, largura=1080, altura=1920)
            if final_path.exists() and final_path.stat().st_size > 0:
                card_nome = final_path.name
        except Exception:
            pass
        out_ov = {"png_url": f"/cards/{card_nome}", "svg": res["svg"]}
        return {"ok": True, "agente": "VectorCraft Overlay", "resultado": out_ov, "saida": out_ov}

    # 2. Agentes cognitivos via LLM
    p = pipeline.perfil(pid) if pid else None
    if not p:
        return {"ok": False, "erro": "Perfil não encontrado."}

    con = pipeline.conexao_do_perfil(p)
    if not con:
        return {"ok": False, "erro": "Nenhuma conexão LLM configurada para este perfil. Acesse Conexões."}

    try:
        from . import agentes
        if agente_nome in ("caption_writer", "redacao", "sala_redacao"):
            cw = agentes.CaptionWriterAgente()
            res = await cw.redigir(con, p, entrada or "3 tendências práticas sobre inteligência artificial")
            return {"ok": True, "agente": "Caption Writer", "resultado": res, "saida": res}
        elif agente_nome in ("humanizer", "qualidade", "sala_qualidade"):
            hum = agentes.HumanizerAgente()
            res = await hum.humanizar(con, p, entrada or "No mundo dinâmico de hoje, é crucial entender que esta jornada transformadora é um divisor de águas.")
            return {"ok": True, "agente": "Humanizer", "resultado": res, "saida": res}
        elif agente_nome in ("hook_extractor", "hook"):
            he = agentes.HookExtractorAgente()
            res = await he.analisar_gancho(con, p, entrada or "Pare de cometer esse erro se você quer crescer no digital.")
            return {"ok": True, "agente": "Hook Extractor", "resultado": res, "saida": res}
        elif agente_nome in ("carousel_planner", "carrossel", "sala_carrossel"):
            cp = agentes.CarouselPlannerAgente()
            res = await cp.planejar(con, p, entrada or "Guia prático de automação para criadores", n_slides=5)
            return {"ok": True, "agente": "Carousel Planner", "resultado": res, "saida": res}
        elif agente_nome in ("content_planner", "planejar", "semana"):
            plan = agentes.ContentPlannerAgente()
            res = await plan.planejar_semana(con, p, foco_estrategico=entrada or "crescimento e autoridade")
            return {"ok": True, "agente": "Content Planner", "resultado": res, "saida": res}
        elif agente_nome in ("audience_insights", "audiencia", "sala_radar"):
            ai = agentes.AudienceInsightsAgente()
            res = await ai.mapear_audiencia(con, p, sub_nicho=entrada)
            return {"ok": True, "agente": "Audience Insights", "resultado": res, "saida": res}
        elif agente_nome in ("hashtag_strategist", "hashtags"):
            hs = agentes.HashtagStrategistAgente()
            res = await hs.gerar(con, p, entrada or "Inteligência Artificial e Negócios")
            return {"ok": True, "agente": "Hashtag Strategist", "resultado": res, "saida": res}
        elif agente_nome in ("sala_orquestrador", "orquestrador"):
            orq = agentes.OrquestradorAgente()
            res = await orq.processar_mensagem(con, p, str(p.get("telegram_chat_id") or "0"), entrada or "Quero planejar a semana")
            return {"ok": True, "agente": "Orquestrador Central", "resultado": res, "saida": res}
        elif agente_nome in ("sala_render", "render"):
            from .agentes.vector_art import VectorArtAgente
            art = VectorArtAgente()
            res = art.gerar_badge(texto=(entrada or "DESTAQUE")[:18], estilo="neon_ciano")
            return {"ok": True, "agente": "Laboratório Gráfico", "resultado": res, "saida": res}
        elif agente_nome in ("sala_cafe", "sala_distribuicao"):
            est = escritorio.obter_estado_escritorio(pid)
            res = {"status": "operacional", "estatisticas": est.get("estatisticas"), "gargalos": est.get("gargalos")}
            return {"ok": True, "agente": agente_nome, "resultado": res, "saida": res}
        else:
            return {"ok": False, "erro": f"Agente '{agente_nome}' não suporta teste isolado."}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/escritorio/testar-agente")
async def api_escritorio_testar_agente(request: Request):
    return await api_agentes_executar(request)


@app.get("/cards/{nome}")
def card(request: Request, nome: str):
    logado(request)
    if not re.fullmatch(r"[a-zA-Z0-9_\-\.]+\.(jpg|jpeg|png|mp4|svg|webp)", nome) or not (C.CARDS / nome).exists():
        raise HTTPException(404)
    ext = nome.split(".")[-1].lower()
    media_map = {
        "mp4": "video/mp4",
        "png": "image/png",
        "svg": "image/svg+xml",
        "webp": "image/webp",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
    }
    return FileResponse(C.CARDS / nome, media_type=media_map.get(ext, "image/jpeg"))



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

# ---------- vozes (clonagem) ----------
def _csrf_ok(request: Request, dados) -> None:
    if not secrets.compare_digest(str(dados.get("csrf", "")), request.session.get("csrf", "-")):
        raise HTTPException(403, "CSRF inválido")


@app.get("/voz")
async def voz_page(request: Request):
    logado(request)
    return render_page(request, "voz.html", vozes=vozes.listar(), servidor=await vozes.estado_servidor(), texto_leitura=vozes.TEXTO_LEITURA,
                       url_local=vozes.URL_SERVIDOR_LOCAL, url_qwen=vozes.URL_SERVIDOR_QWEN, whisper_ok=voz.whisper_ok(), tts_ok=voz.tts_ok())


@app.post("/voz/adicionar")
async def voz_adicionar(request: Request):
    logado(request)
    dados = await request.form()
    _csrf_ok(request, dados)
    nome = str(dados.get("nome") or "")
    arqs = [a for a in dados.getlist("arquivo") if getattr(a, "filename", "")]
    if not arqs:
        flash(request, "Grave ou escolha pelo menos um áudio.", "erro")
        return voltar(request, "/voz")
    ok = 0
    for a in arqs:
        try:
            await vozes.adicionar(nome, await a.read(), a.filename, dono=str(dados.get("dono") or "propria"),
                                  autor=str(dados.get("autor") or ""), consentimento=bool(dados.get("consentimento")))
            ok += 1
        except vozes.VozesError as e:
            flash(request, f"{a.filename}: {e}.", "erro")
    if ok:
        m = vozes.obter(vozes.slug(nome)) or {}
        flash(request, f"{ok} gravação(ões) processada(s). Amostra de {m.get('dur_ref', 0):.0f} s.")
        for av in m.get("avisos", []):
            flash(request, av, "aviso")
        db.log(None, None, "voz_amostra", vozes.slug(nome))
    return voltar(request, "/voz")


@app.get("/voz/{sl}/amostra.wav")
def voz_amostra(request: Request, sl: str):
    logado(request)
    try:
        f = vozes.ref_path(sl)
    except vozes.VozesError:
        f = None
    if not f:
        raise HTTPException(404)
    return FileResponse(f, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/voz/{sl}/take/{n}/remover")
async def voz_take_remover(request: Request, sl: str, n: int):
    logado(request)
    await form(request)
    try:
        await vozes.remover_take(sl, n)
        flash(request, "Gravação removida.")
    except vozes.VozesError as e:
        flash(request, f"{e}.", "erro")
    return voltar(request, "/voz")


@app.post("/voz/{sl}/padrao")
async def voz_padrao(request: Request, sl: str):
    logado(request)
    await form(request)
    try:
        vozes.definir_padrao(sl)
        flash(request, "Voz padrão definida. As narrações novas usam essa voz.")
    except vozes.VozesError as e:
        flash(request, f"{e}.", "erro")
    return voltar(request, "/voz")


@app.post("/voz/{sl}/excluir")
async def voz_excluir(request: Request, sl: str):
    logado(request)
    await form(request)
    try:
        vozes.excluir(sl)
        flash(request, "Voz apagada (gravações e amostra).")
    except vozes.VozesError as e:
        flash(request, f"{e}.", "erro")
    return voltar(request, "/voz")


@app.post("/voz/{sl}/testar")
async def voz_testar(request: Request, sl: str):
    logado(request)
    f = await form(request)
    from fastapi.responses import JSONResponse, Response
    if not vozes.obter(sl):
        return JSONResponse({"erro": "voz não encontrada"}, status_code=404)
    texto = (f.get("texto") or "").strip()[:400] or "Olá! Essa é a minha voz clonada, falando direto do meu computador."
    def num(k):
        try:
            return float(f[k]) if f.get(k, "") != "" else None
        except ValueError:
            return None
    extra = {"cfg_weight": num("cfg"), "exaggeration": num("exag"), "temperature": num("temp")}
    try:
        audio = await voz.narrar(texto, voz=sl, extra=extra)
    except voz.VozError as e:
        return JSONResponse({"erro": str(e)}, status_code=502)
    try:
        return Response(audio.read_bytes(), media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
    finally:
        audio.unlink(missing_ok=True)


@app.post("/voz/servidor/usar")
async def voz_servidor_usar(request: Request):
    logado(request)
    f = await form(request)
    qwen = f.get("motor") == "qwen"
    url = vozes.URL_SERVIDOR_QWEN if qwen else vozes.URL_SERVIDOR_LOCAL
    db.set_setting("whisper_url", url)
    db.set_setting("whisper_model", "whisper-1")
    db.set_setting("tts_url", url)
    db.set_setting("tts_model", "qwen3-tts" if qwen else "chatterbox")
    perfil = "qwen" if qwen else "gpu"
    flash(request, f"Transcrição e voz apontadas para o servidor local ({'Qwen3-TTS' if qwen else 'Chatterbox'}). "
                   f"Suba-o com: docker compose --profile {perfil} up -d --build (e pare o outro motor, para não faltar memória da placa).")
    return voltar(request, "/voz")


@app.post("/voz/servidor/descarregar")
async def voz_servidor_descarregar(request: Request):
    logado(request)
    await form(request)
    try:
        await vozes.descarregar_servidor()
        flash(request, "Modelos descarregados: a placa de vídeo está livre. Eles recarregam sozinhos no próximo uso.")
    except vozes.VozesError as e:
        flash(request, f"{e}.", "erro")
    return voltar(request, "/voz")


@app.post("/voz/{sl}/limpeza")
async def voz_limpeza(request: Request, sl: str):
    logado(request)
    f = await form(request)
    try:
        await vozes.reprocessar(sl, f.get("modo", "leve"))
        flash(request, f"Amostra refeita com limpeza {'forte' if f.get('modo') == 'forte' else 'leve'}.")
    except (vozes.VozesError, midia.MidiaError) as e:
        flash(request, f"{e}.", "erro")
    return voltar(request, "/voz")


@app.post("/voz/{sl}/texto")
async def voz_texto(request: Request, sl: str):
    logado(request)
    f = await form(request)
    try:
        vozes.salvar_texto_ref(sl, f.get("texto", ""))
        flash(request, "Texto da amostra salvo.")
    except vozes.VozesError as e:
        flash(request, f"{e}.", "erro")
    return voltar(request, "/voz")


@app.post("/voz/{sl}/ajustes")
async def voz_ajustes(request: Request, sl: str):
    logado(request)
    f = await form(request)
    def num(k):
        try:
            return float(f[k]) if f.get(k, "") != "" else None
        except ValueError:
            return None
    try:
        if f.get("acao") == "padrao":
            vozes.definir_ajustes(sl, None, None, None)
            flash(request, "Ajustes voltaram ao padrão do servidor.")
        else:
            vozes.definir_ajustes(sl, num("cfg"), num("exag"), num("temp"))
            flash(request, "Ajustes salvos para essa voz (valem para todas as narrações).")
    except vozes.VozesError as e:
        flash(request, f"{e}.", "erro")
    return voltar(request, "/voz")


# ---------- perfis ----------
@app.get("/perfis")
def perfis_page(request: Request):
    logado(request)
    perfis = db.q("""
        SELECT p.*,
               (SELECT COUNT(*) FROM feeds f WHERE f.perfil_id=p.id AND f.ativo=1) AS total_feeds,
               (SELECT COUNT(*) FROM feeds f WHERE f.perfil_id=p.id) AS total_feeds_cadastrados
        FROM perfis p
        ORDER BY p.id
    """)
    return render_page(request, "perfis.html", lista=perfis)


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
    feeds_perfil = db.q("SELECT * FROM feeds WHERE perfil_id=? ORDER BY id", (pid,))
    return render_page(
        request,
        "perfil.html",
        p=p,
        marca=marca_mod.carregar(p),
        tem_logo=bool(marca_mod._logo_path(pid)),
        fontes=marca_mod.NOMES_FONTE,
        token_mask=crypto.mask(crypto.dec(p["ig_token_enc"])),
        conexoes=db.q("SELECT id, nome, modelo, padrao FROM llm_conexoes ORDER BY id"),
        paginas=[{k: v for k, v in pg.items() if k != "token"} for pg in _metatmp(pid)],
        feeds_perfil=feeds_perfil,
        pacotes=wizard.PACOTES_FEEDS,
        tem_meta_ai=bool(settings.meta_ai_cookies()),
    )


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
         "contexto_md=?,horarios=?,palavras_chave=?,max_idade_horas=?,musica_modo=?,esteira=? WHERE id=?",
         (f.get("nome", "").strip() or "Sem nome", f.get("handle", "").strip(), 1 if f.get("ativo") else 0,
          f.get("ig_user_id", "").strip(), f.get("telegram_chat_id", "").strip(), con,
          f.get("contexto_md", ""), horarios, f.get("palavras_chave", "").strip(),
          max(1, min(int(f.get("max_idade_horas") or 36), 720)),
          "aleatoria" if f.get("musica_modo") == "aleatoria" else "nenhuma",
          f.get("esteira") if f.get("esteira") in ("reel", "feed", "story", "off") else "reel", pid))
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


@app.post("/perfis/{pid}/excluir")
async def perfil_excluir(request: Request, pid: int):
    logado(request)
    await form(request)
    p = pipeline.perfil(pid)
    if not p:
        raise HTTPException(404)
    nome = p["nome"]
    pipeline.excluir_perfil(pid)
    if request.session.get("perfil_id") == pid:
        request.session.pop("perfil_id", None)
    flash(request, f"Perfil '{nome}' e todos os seus dados foram excluídos com sucesso.", "ok")
    return voltar(request, "/perfis")


# ---------- feeds exclusivos do perfil & sincronização com meta ai ----------
@app.post("/perfis/{pid}/feeds")
async def perfil_feed_novo(request: Request, pid: int):
    logado(request)
    if not pipeline.perfil(pid):
        raise HTTPException(404)
    f = await form(request)
    url = f.get("url", "").strip()
    if not url.startswith(("http://", "https://")):
        flash(request, "URL de RSS inválida.", "erro")
        return voltar(request, f"/perfis/{pid}#feeds")
    nome = f.get("nome", "").strip() or url
    tema = f.get("tema", "").strip()
    db.x("INSERT INTO feeds(perfil_id,nome,url,tema,ativo) VALUES(?,?,?,?,1)", (pid, nome, url, tema))
    db.log(pid, None, "feed_criado", f"Feed '{nome}' adicionado ao perfil")
    flash(request, f"Feed '{nome}' adicionado a este perfil com sucesso!", "ok")
    return voltar(request, f"/perfis/{pid}#feeds")


@app.post("/perfis/{pid}/feeds/{fid}/{acao}")
async def perfil_feed_acao(request: Request, pid: int, fid: int, acao: str):
    logado(request)
    if not pipeline.perfil(pid):
        raise HTTPException(404)
    await form(request)
    feed = db.one("SELECT * FROM feeds WHERE id=? AND perfil_id=?", (fid, pid))
    if not feed:
        flash(request, "Feed não encontrado para este perfil.", "erro")
        return voltar(request, f"/perfis/{pid}#feeds")
    if acao == "alternar":
        novo = 1 - feed["ativo"]
        db.x("UPDATE feeds SET ativo=? WHERE id=?", (novo, fid))
        st = "ativado" if novo else "desativado"
        flash(request, f"Feed '{feed['nome']}' {st}.", "ok")
    elif acao == "remover":
        db.x("DELETE FROM feeds WHERE id=?", (fid,))
        flash(request, f"Feed '{feed['nome']}' removido deste perfil.", "ok")
    return voltar(request, f"/perfis/{pid}#feeds")


@app.post("/perfis/{pid}/feeds/importar-pack")
async def perfil_feeds_importar_pack(request: Request, pid: int):
    logado(request)
    p = pipeline.perfil(pid)
    if not p:
        raise HTTPException(404)
    f = await form(request)
    pack_id = f.get("pack_id", "").strip()
    pack = wizard.PACOTES_FEEDS.get(pack_id)
    if not pack:
        flash(request, "Pacote de feeds não encontrado.", "erro")
        return voltar(request, f"/perfis/{pid}#feeds")
    total = wizard.vincular_feeds_perfil(pid, pack["feeds"])
    if not p.get("palavras_chave"):
        db.x("UPDATE perfis SET palavras_chave=? WHERE id=?", (pack["palavras_chave"], pid))
    flash(request, f"✨ {total} feeds do pacote '{pack['nome']}' vinculados ao perfil!", "ok")
    return voltar(request, f"/perfis/{pid}#feeds")


@app.post("/perfis/{pid}/feeds/buscar-agora")
async def perfil_feeds_buscar_agora(request: Request, pid: int):
    logado(request)
    if not pipeline.perfil(pid):
        raise HTTPException(404)
    await form(request)
    capturados = await pipeline.buscar_noticias(pid, "perfil_manual_feeds", n=3)
    if capturados > 0:
        flash(request, f"🚀 Sucesso! {capturados} matéria(s) capturada(s) para este perfil e já aguardam aprovação na Fila.", "ok")
    else:
        flash(request, "Varredura concluída. Todas as matérias recentes relevantes para este perfil já foram capturadas.", "aviso")
    return voltar(request, f"/perfis/{pid}#feeds")


@app.post("/perfis/{pid}/meta-analise")
async def perfil_meta_analise(request: Request, pid: int):
    logado(request)
    p = pipeline.perfil(pid)
    if not p:
        raise HTTPException(404)
    f = await form(request)
    relatorio = f.get("relatorio", "").strip()
    acao_remota = f.get("acao_remota") == "1"

    if acao_remota and not relatorio:
        identificador = p["handle"] or p["nome"]
        r = await meta_ai.analisar_perfil_remoto(identificador, p)
        if not r.get("ok"):
            flash(request, f"Falha na extração remota do Meta AI: {r.get('erro')}. Cole a análise manualmente abaixo.", "erro")
            return voltar(request, f"/perfis/{pid}#meta-ai")
        relatorio = r.get("relatorio", "")

    if not relatorio:
        flash(request, "Cole o relatório do Meta AI ou use a extração automática.", "erro")
        return voltar(request, f"/perfis/{pid}#meta-ai")

    substituir = f.get("substituir_feeds") == "1"
    try:
        res = await wizard.aplicar_analise_meta_ai_ao_perfil(pid, relatorio, substituir_feeds=substituir)
        flash(request, f"🤖 Sucesso! Tom de voz atualizado e {res.get('total_feeds', 0)} feeds em contexto vinculados ao perfil ({res.get('nicho', '')}).", "ok")
    except Exception as e:
        flash(request, f"Erro ao aplicar análise: {e}", "erro")
    return voltar(request, f"/perfis/{pid}#feeds")


# ---------- LLM ----------
def _con_form(f: dict) -> dict:
    return {"id": f.get("id", ""), "nome": f.get("nome", "").strip(), "tipo": f.get("tipo", "openrouter"),
            "base_url": f.get("base_url", "").strip(), "modelo": f.get("modelo", "").strip(), "padrao": bool(f.get("padrao"))}


@app.get("/llm")
async def llm_page(request: Request):
    logado(request)
    lista = db.q("SELECT * FROM llm_conexoes ORDER BY id")
    sel = request.query_params.get("editar")
    atual = next((c for c in lista if str(c["id"]) == sel), None)
    form_v = {**atual, "id": str(atual["id"]), "padrao": bool(atual["padrao"])} if atual else \
        {"id": "", "nome": "", "tipo": "openrouter", "base_url": "", "modelo": "", "padrao": not lista}
    status_local = await llm_local.status_servidor()
    roteamento = hardware.obter_roteamento()
    estado_voz = await vozes.estado_servidor()
    openrouter_con = next((c for c in lista if c["tipo"] == "openrouter" or "openrouter.ai" in (c.get("base_url") or "")), None)
    openrouter_key_mascarada = crypto.mask(crypto.dec(openrouter_con["api_key_enc"])) if openrouter_con else ""
    return render_page(
        request, "llm.html",
        lista=lista, f=form_v, modelos=[], tipos=llm.TIPOS, dicas=llm.DICAS_URL,
        local=status_local, roteamento=roteamento, servidor_voz=estado_voz,
        url_voz_local=vozes.URL_SERVIDOR_LOCAL, url_voz_qwen=vozes.URL_SERVIDOR_QWEN,
        openrouter_con=openrouter_con, openrouter_key_mascarada=openrouter_key_mascarada
    )


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

    async def pagina(modelos=None):
        status_local = await llm_local.status_servidor()
        roteamento = hardware.obter_roteamento()
        estado_voz = await vozes.estado_servidor()
        openrouter_con = next((c for c in lista if c["tipo"] == "openrouter" or "openrouter.ai" in (c.get("base_url") or "")), None)
        openrouter_key_mascarada = crypto.mask(crypto.dec(openrouter_con["api_key_enc"])) if openrouter_con else ""
        return render_page(
            request, "llm.html",
            lista=lista, f=v, modelos=modelos or [], tipos=llm.TIPOS, dicas=llm.DICAS_URL,
            local=status_local, roteamento=roteamento, servidor_voz=estado_voz,
            url_voz_local=vozes.URL_SERVIDOR_LOCAL, url_voz_qwen=vozes.URL_SERVIDOR_QWEN,
            openrouter_con=openrouter_con, openrouter_key_mascarada=openrouter_key_mascarada
        )

    if f.get("acao") == "detectar":
        try:
            modelos, base = await llm.listar_modelos(v["tipo"], v["base_url"], chave)
        except Exception as e:
            flash(request, f"Não consegui listar os modelos: {str(e)[:300]}", "erro")
            return await pagina()
        v["base_url"] = base or v["base_url"]
        if v["modelo"] not in modelos:
            v["modelo"] = modelos[0] if modelos else ""
        flash(request, f"{len(modelos)} modelo(s) encontrado(s). Escolha um e clique em Aplicar e testar." if modelos
              else "Conectou, mas nenhum modelo foi listado. Carregue um modelo no programa e tente de novo.",
              "ok" if modelos else "aviso")
        return await pagina(modelos)

    # aplicar e testar
    if not v["nome"] or not v["modelo"]:
        flash(request, "Informe um nome e escolha o modelo (use Detectar modelos).", "erro")
        return await pagina()
    if v["tipo"] == "openrouter" and not v["base_url"]:
        v["base_url"] = "https://openrouter.ai/api/v1"
    if v["tipo"] in ("openai", "ollama") and not v["base_url"].startswith(("http://", "https://")):
        flash(request, "Informe a URL do servidor (começa com http:// ou https://).", "erro")
        return await pagina()
    if v["tipo"] in ("gemini", "anthropic", "openrouter") and not chave:
        flash(request, "Informe a chave de API (OpenRouter, Gemini ou Anthropic exigem chave).", "erro")
        return await pagina()
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


@app.post("/llm/local/baixar")
async def llm_local_baixar(request: Request):
    logado(request)
    f = await form(request)
    modelo = f.get("modelo", "").strip()
    if not modelo or modelo not in llm_local.MODELOS_CATALOGO:
        flash(request, "Modelo inválido ou não disponível no catálogo.", "erro")
        return voltar(request, "/llm")
    
    iniciado = llm_local.iniciar_download(modelo)
    if iniciado:
        flash(request, f"Download de {modelo} iniciado no servidor Ollama! O modelo será configurado como padrão automaticamente ao terminar.")
    else:
        flash(request, "Já existe um download em andamento no servidor local. Aguarde concluir.", "aviso")
    return voltar(request, "/llm")


@app.get("/llm/local/status")
async def llm_local_status(request: Request):
    logado(request)
    return await llm_local.status_servidor()


@app.post("/llm/local/ativar")
async def llm_local_ativar(request: Request):
    logado(request)
    f = await form(request)
    modelo = f.get("modelo", "").strip()
    if not modelo:
        flash(request, "Modelo não informado.", "erro")
        return voltar(request, "/llm")
    
    base_url = await llm_local.detectar_base_url()
    cid = llm_local.apontar_como_padrao(modelo, base_url)
    modulo = f.get("modulo", "").strip()
    if modulo in hardware.MODULOS_IA:
        db.set_setting(f"llm_modulo_{modulo}", str(cid))
        flash(request, f"Modelo local {modelo} alocado com sucesso para o módulo {hardware.MODULOS_IA[modulo]['nome']}!")
    else:
        flash(request, f"Modelo local {modelo} ativado como conexão padrão do sistema (conexão #{cid})!")
    return voltar(request, "/llm")


@app.post("/llm/roteamento")
async def llm_roteamento(request: Request):
    logado(request)
    f = await form(request)
    hardware.salvar_roteamento_modulos(f)
    flash(request, "Roteamento inteligente de IA atualizado! Tarefas de texto e voz agora utilizam seus respectivos motores alocados.", "ok")
    return voltar(request, "/llm")


@app.post("/llm/perfil-custo-zero")
async def llm_perfil_custo_zero(request: Request):
    logado(request)
    await form(request)
    res = hardware.aplicar_perfil_custo_zero()
    flash(request, res["mensagem"], "ok")
    return voltar(request, "/llm")


@app.post("/llm/openrouter")
async def llm_openrouter(request: Request):
    logado(request)
    f = await form(request)
    chave = f.get("api_key", "").strip()
    
    con_existente = db.one("SELECT * FROM llm_conexoes WHERE tipo='openrouter' OR base_url LIKE '%openrouter.ai%' LIMIT 1")
    if not chave and con_existente:
        chave = crypto.dec(con_existente["api_key_enc"])
        
    if not chave:
        flash(request, "Informe sua chave de API da OpenRouter (obtenha em openrouter.ai/keys).", "erro")
        return voltar(request, "/llm#openrouter-box")
        
    base_url = "https://openrouter.ai/api/v1"
    
    try:
        modelos, _ = await llm.listar_modelos("openrouter", base_url, chave)
    except Exception as e:
        flash(request, f"Erro ao conectar com OpenRouter: {str(e)[:300]}", "erro")
        return voltar(request, "/llm#openrouter-box")
        
    if not modelos:
        flash(request, "Conectou à OpenRouter, mas nenhum modelo foi retornado. Verifique suas permissões de chave.", "aviso")
        return voltar(request, "/llm#openrouter-box")
        
    gratuitos = [m for m in modelos if ":free" in m]
    modelo_padrao = "meta-llama/llama-3.3-70b-instruct:free"
    if modelo_padrao not in modelos:
        modelo_padrao = gratuitos[0] if gratuitos else (
            "deepseek/deepseek-chat" if "deepseek/deepseek-chat" in modelos else modelos[0]
        )
    
    if con_existente:
        cid = con_existente["id"]
        mod_atual = con_existente["modelo"] if con_existente["modelo"] in modelos else modelo_padrao
        db.x("UPDATE llm_conexoes SET nome=?, tipo=?, base_url=?, api_key_enc=?, modelo=? WHERE id=?",
             ("OpenRouter", "openrouter", base_url, crypto.enc(chave), mod_atual, cid))
    else:
        cid = db.x(
            "INSERT INTO llm_conexoes(nome, tipo, base_url, api_key_enc, modelo, padrao, criado_em) "
            "VALUES(?, ?, ?, ?, ?, 0, ?)",
            ("OpenRouter", "openrouter", base_url, crypto.enc(chave), modelo_padrao, db.now())
        )
        if db.one("SELECT COUNT(*) n FROM llm_conexoes WHERE padrao=1")["n"] == 0:
            db.x("UPDATE llm_conexoes SET padrao=1 WHERE id=?", (cid,))

    n_free = len(gratuitos)
    info_free = f" ({n_free} modelos gratuitos :free disponíveis)" if n_free else ""
    flash(request, f"⚡ OpenRouter conectado com sucesso! {len(modelos)} modelos detectados{info_free}. Conexão #{cid} pronta para uso.", "ok")
    return voltar(request, f"/llm?editar={cid}")


@app.post("/voz/servidor/embutido")
async def voz_servidor_embutido(request: Request):
    logado(request)
    await form(request)
    db.set_setting("whisper_url", "")
    db.set_setting("whisper_model", "")
    db.set_setting("whisper_local", "1")
    db.set_setting("tts_url", "")
    db.set_setting("tts_model", "embutido")
    flash(request, "Voz e transcrição configuradas para o Whisper Local Embutido (CPU/NPU · Custo Zero & Zero Tokens)!", "ok")
    ref = request.headers.get("referer") or "/llm"
    return voltar(request, "/llm" if "/llm" in ref else "/voz")



# ---------- feeds ----------
@app.get("/feeds")
def feeds_page(request: Request):
    logado(request)
    pid = perfil_atual_id(request)
    feeds_perfil = db.q("SELECT * FROM feeds WHERE perfil_id=? ORDER BY id", (pid,)) if pid else []
    feeds_globais = db.q("SELECT * FROM feeds WHERE perfil_id IS NULL ORDER BY id")
    return render_page(
        request,
        "feeds.html",
        feeds_perfil=feeds_perfil,
        feeds_globais=feeds_globais,
        pacotes=wizard.PACOTES_FEEDS,
        perfil=pipeline.perfil(pid) if pid else None,
    )


@app.post("/feeds/buscar-agora")
async def feeds_buscar_agora(request: Request):
    logado(request)
    pid = perfil_atual_id(request)
    if not pid:
        flash(request, "Selecione um perfil primeiro.", "erro")
        return voltar(request, "/feeds")
    await form(request)
    capturados = await pipeline.buscar_noticias(pid, "manual_feeds", n=3)
    if capturados > 0:
        flash(request, f"🚀 Sucesso! {capturados} matéria(s) relevante(s) capturada(s) para seu perfil e já aguardam aprovação na Fila.", "ok")
    else:
        flash(request, "Varredura concluída. Todas as matérias recentes relevantes já foram capturadas.", "aviso")
    return voltar(request, "/feeds")


@app.post("/feeds/importar-pack")
async def feeds_importar_pack(request: Request):
    logado(request)
    pid = perfil_atual_id(request)
    if not pid:
        flash(request, "Selecione um perfil primeiro.", "erro")
        return voltar(request, "/feeds")
    f = await form(request)
    pack_id = f.get("pack_id", "").strip()
    pack = wizard.PACOTES_FEEDS.get(pack_id)
    if not pack:
        flash(request, "Pacote de feeds não encontrado.", "erro")
        return voltar(request, "/feeds")
    total = wizard.vincular_feeds_perfil(pid, pack["feeds"])
    
    # Também atualiza palavras-chave se o perfil estiver vazio
    p = pipeline.perfil(pid)
    if p and not p.get("palavras_chave"):
        db.x("UPDATE perfis SET palavras_chave=? WHERE id=?", (pack["palavras_chave"], pid))
        
    flash(request, f"✨ {total} feeds do pacote '{pack['nome']}' vinculados ao seu perfil com sucesso!", "ok")
    return voltar(request, "/feeds")


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
    canais_lista = distribuicao.listar_canais(pid) if pid else []
    canais_map = {c["canal"]: c for c in canais_lista}
    return render_page(request, "conexoes.html", perfil=pipeline.perfil(pid) if pid else None,
                       base=settings.base_url(), tunel=tunel, tem_tunel=bool(settings.tunnel_token()),
                       tg_token=crypto.mask(settings.telegram_token()), tz=settings.tz(),
                       tem_meta_ai=bool(settings.meta_ai_cookies()),
                       canais_distribuicao=canais_lista,
                       canais_map=canais_map,
                       canais_espec=distribuicao.CANAIS_SUPORTADOS,
                       hg_key=crypto.mask(banco.higgs_chave().split(':')[-1]),
                       wh={"url": db.get_setting("whisper_url"), "modelo": db.get_setting("whisper_model"), "chave": crypto.mask(settings.segredo("whisper_key"))},
                       tt={"url": db.get_setting("tts_url"), "modelo": db.get_setting("tts_model"), "voz": db.get_setting("tts_voz"), "chave": crypto.mask(settings.segredo("tts_key"))}, un_key=crypto.mask(settings.unsplash_key()), bancos_abertos=settings.bancos_abertos())


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
    elif secao == "meta_ai":
        if f.get("acao") == "remover":
            settings.guardar_meta_ai_cookies("")
            flash(request, "Cookies da sessão do Meta AI removidos.")
        elif f.get("cookies", "").strip():
            settings.guardar_meta_ai_cookies(f["cookies"].strip())
            flash(request, "Cookies da sessão do Meta AI salvos. O navegador utilizará a sessão para a técnica Blow Up.")
        else:
            flash(request, "Cole os cookies da sessão do Meta AI.", "aviso")
    elif secao.startswith("canal_"):
        canal = secao.replace("canal_", "").lower().strip()
        pid = perfil_atual_id(request)
        if not pid:
            flash(request, "Selecione um perfil primeiro.", "erro")
        elif f.get("acao") == "remover":
            distribuicao.remover_canal(pid, canal)
            flash(request, f"Canal {canal.capitalize()} removido deste perfil.")
        elif f.get("acao") == "alternar":
            distribuicao.alternar_canal(pid, canal)
            flash(request, f"Status do canal {canal.capitalize()} alternado.")
        else:
            token = f.get("token", "").strip()
            identificador = f.get("identificador", "").strip()
            ativo = f.get("ativo") == "1"
            extra = {}
            if f.get("privacy_status"):
                extra["privacy_status"] = f.get("privacy_status")
            if f.get("privacy_level"):
                extra["privacy_level"] = f.get("privacy_level")
            distribuicao.salvar_canal(pid, canal, identificador, token, ativo, extra)
            flash(request, f"Canal {canal.capitalize()} salvo com sucesso.")
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
    elif secao == "bancos_abertos":
        db.set_setting("bancos_abertos", "1" if f.get("ligado") == "on" else "0")
        flash(request, "Plano B de imagens sem chave " + ("ligado." if f.get("ligado") == "on" else "desligado: só Higgsfield, Unsplash e as suas fotos."))
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
        elif alvo == "meta_ai":
            r = await meta_ai.testar_sessao()
            flash(request, f"Meta AI OK: {r['detalhe']}" if r["ok"] else f"Meta AI: {r['erro']}", "ok" if r["ok"] else "erro")
        elif alvo.startswith("canal_"):
            canal = alvo.replace("canal_", "").lower().strip()
            r = await distribuicao.testar_canal(p["id"], canal)
            flash(request, f"{canal.capitalize()} OK: {r['detalhe']}" if r["ok"] else f"{canal.capitalize()}: {r['erro']}", "ok" if r["ok"] else "erro")
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
