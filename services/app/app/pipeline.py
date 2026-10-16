"""Fluxo de um post: capturar -> extrair -> reagir -> renderizar -> aprovar -> publicar."""
import json, re, shutil, sqlite3

from . import config as C, crypto, db, feeds, ig, llm, render, settings, telegram

RUNNING: set[int] = set()
MAX_FALHAS = 3


def perfil(pid: int) -> dict | None:
    return db.one("SELECT * FROM perfis WHERE id=?", (pid,))


def conexao_do_perfil(p: dict) -> dict | None:
    """Conexão de LLM do perfil; sem escolha própria, usa a padrão. A chave volta descriptografada."""
    con = db.one("SELECT * FROM llm_conexoes WHERE id=?", (p["llm_conexao_id"],)) if p.get("llm_conexao_id") else None
    con = con or db.one("SELECT * FROM llm_conexoes WHERE padrao=1") or db.one("SELECT * FROM llm_conexoes ORDER BY id LIMIT 1")
    if con:
        try:
            con = {**con, "api_key": crypto.dec(con["api_key_enc"])}
        except Exception:
            con = {**con, "api_key": ""}
    return con


def post(post_id: int) -> dict | None:
    return db.one("SELECT * FROM posts WHERE id=?", (post_id,))


def _set(post_id: int, estado: str, **campos) -> None:
    extra = "".join(f", {k}=?" for k in campos)
    db.x(f"UPDATE posts SET estado=?, atualizado_em=?{extra} WHERE id=?",
         (estado, db.now(), *campos.values(), post_id))


def _claim(post_id: int, de: tuple, para: str) -> bool:
    marks = ",".join("?" * len(de))
    return db.x(f"UPDATE posts SET estado=?, atualizado_em=? WHERE id=? AND estado IN ({marks})",
                (para, db.now(), post_id, *de)) == 1


def _apagar(*nomes) -> None:
    for n in nomes:
        if n and re.fullmatch(r"[0-9a-f]{32}\.jpg", n):
            (C.CARDS / n).unlink(missing_ok=True)


async def gerar(perfil_id: int, n: int = 1, origem: str = "manual") -> int:
    """Busca notícias novas e cria até n posts aguardando aprovação. Devolve quantos deram certo."""
    if perfil_id in RUNNING:
        return 0
    RUNNING.add(perfil_id)
    try:
        p = perfil(perfil_id)
        if not p:
            return 0
        fl = db.q("SELECT * FROM feeds WHERE ativo=1 AND (perfil_id IS NULL OR perfil_id=?)", (perfil_id,))
        usadas = {r["noticia_url"] for r in db.q("SELECT noticia_url FROM posts WHERE perfil_id=?", (perfil_id,))}
        palavras = [s.strip() for s in p["palavras_chave"].split(",") if s.strip()]
        cands = await feeds.candidatas(fl, palavras, p["max_idade_horas"], usadas)
        db.log(perfil_id, None, "busca", f"{origem}: {len(cands)} candidatas")
        feitos, falhas = 0, 0
        for c in cands:
            if feitos >= n or falhas >= MAX_FALHAS:
                break  # com o modelo/Meta fora do ar, não varrer o feed inteiro nem inundar o Telegram
            try:
                pid = db.x("INSERT INTO posts(perfil_id,estado,noticia_url,noticia_titulo,fonte,criado_em,atualizado_em)"
                           " VALUES(?,?,?,?,?,?,?)",
                           (perfil_id, "capturado", c["url"], c["titulo"], c["fonte"], db.now(), db.now()))
            except sqlite3.IntegrityError:
                continue
            if await _processar(pid, p, temperature=0.7):
                feitos += 1
            else:
                falhas += 1
        return feitos
    finally:
        RUNNING.discard(perfil_id)


async def _processar(post_id: int, p: dict, temperature: float) -> bool:
    po = post(post_id)
    try:
        if not po["texto"]:
            ex = await feeds.extrair(po["noticia_url"])
            _set(post_id, "extraido", texto=ex["texto"], noticia_titulo=po["noticia_titulo"] or ex["titulo"])
            po = post(post_id)
        con = conexao_do_perfil(p)
        if not con or not con["modelo"]:
            raise ValueError("nenhuma conexão de LLM com modelo escolhido: configure em LLM")
        noticia = {"titulo": po["noticia_titulo"], "fonte": po["fonte"], "url": po["noticia_url"], "texto": po["texto"]}
        feedback, res, arquivo = None, None, None
        for tentativa in range(3):
            try:
                res = await llm.reagir(con, p["contexto_md"], noticia, temperature, feedback)
            except ValueError as e:
                feedback = str(e)
                continue
            arquivo, estourou = await render.card(res["manchete_curta"], res["minha_reacao"], po["fonte"] or res["fonte"],
                                                  p["handle"], p["nome"])
            if estourou:
                _apagar(arquivo)
                feedback, arquivo = "minha_reacao não coube no card, encurte", None
                continue
            break
        if not arquivo:
            raise ValueError(f"o modelo não entregou uma saída válida em 3 tentativas ({feedback})")
        _set(post_id, "aguardando_aprovacao", json_llm=json.dumps(res, ensure_ascii=False), manchete=res["manchete_curta"],
             reacao=res["minha_reacao"], legenda=res["legenda_instagram"], arquivo=arquivo, erro=None)
        db.log(p["id"], post_id, "gerado", f"confianca={res['confianca']}")
        if telegram.ativo() and p["telegram_chat_id"]:
            try:
                aviso = "⚠️ Confiança baixa: confira o fato antes de postar." if res["confianca"] == "baixa" else ""
                mid = await telegram.enviar_card(p["telegram_chat_id"], C.CARDS / arquivo, post_id, res["legenda_instagram"], aviso)
                db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, post_id))
            except Exception as e:
                db.log(p["id"], post_id, "telegram_falhou", str(e))
        return True
    except Exception as e:
        msg = (str(e) or type(e).__name__)[:400]
        _set(post_id, "falhou", erro=msg)
        db.log(p["id"], post_id, "falhou", msg)
        if telegram.ativo() and p["telegram_chat_id"]:
            await telegram.avisar(p["telegram_chat_id"], f"Falha ao gerar post #{post_id}: {msg[:200]}")
        return False


async def refazer(post_id: int) -> bool:
    po = post(post_id)
    if not po or not _claim(post_id, ("aguardando_aprovacao", "falhou"), "extraido"):
        return False
    old = po["arquivo"]
    p = perfil(po["perfil_id"])
    ok = await _processar(post_id, p, temperature=0.95)
    if ok:
        _apagar(old)
        db.log(p["id"], post_id, "refeito")
        if po["tg_message_id"] and p["telegram_chat_id"]:
            await telegram.marcar(p["telegram_chat_id"], po["tg_message_id"], "Refeito. Nova versão abaixo.")
    return ok


async def aprovar(post_id: int, origem: str = "painel") -> bool:
    po = post(post_id)
    if not po or not po["arquivo"] or not (C.CARDS / po["arquivo"]).exists():
        return False
    if not _claim(post_id, ("aguardando_aprovacao", "falhou"), "publicando"):
        return False
    p = perfil(po["perfil_id"])
    pub = C.PUBLIC / po["arquivo"]
    try:
        base = settings.base_url()
        if not base:
            raise ig.MetaError("URL pública não configurada (menu Conexões)")
        if not p["ig_user_id"] or not p["ig_token_enc"]:
            raise ig.MetaError("perfil sem ig_user_id ou token")
        shutil.copyfile(C.CARDS / po["arquivo"], pub)
        media = await ig.publicar(p["ig_user_id"], crypto.dec(p["ig_token_enc"]), f"{base}/{po['arquivo']}", po["legenda"])
        _set(post_id, "publicado", media_id=media, erro=None)
        db.log(p["id"], post_id, "publicado", f"{origem} media={media}")
        resultado = "✅ Publicado."
    except Exception as e:
        _set(post_id, "falhou", erro=str(e)[:400])
        db.log(p["id"], post_id, "falhou_publicar", str(e))
        resultado = f"❌ Falha ao publicar: {str(e)[:200]}"
    finally:
        pub.unlink(missing_ok=True)  # a imagem só fica pública durante o publish
    if po["tg_message_id"] and p["telegram_chat_id"]:
        await telegram.marcar(p["telegram_chat_id"], po["tg_message_id"], resultado)
    return resultado.startswith("✅")


async def descartar(post_id: int, origem: str = "painel") -> bool:
    po = post(post_id)
    if not po or not _claim(post_id, ("aguardando_aprovacao", "falhou"), "descartado"):
        return False
    _apagar(po["arquivo"])
    p = perfil(po["perfil_id"])
    db.log(p["id"], post_id, "descartado", origem)
    if po["tg_message_id"] and p["telegram_chat_id"]:
        await telegram.marcar(p["telegram_chat_id"], po["tg_message_id"], "🗑 Descartado.")
    return True


async def acao_telegram(acao: str, post_id: int, chat_id: str) -> None:
    po = post(post_id)
    p = perfil(po["perfil_id"]) if po else None
    if not p or str(p["telegram_chat_id"]) != chat_id:
        return  # só o dono do perfil aprova os posts dele
    if acao == "ap":
        await aprovar(post_id, "telegram")
    elif acao == "rf":
        await refazer(post_id)
    elif acao == "ds":
        await descartar(post_id, "telegram")
