"""Fluxo de um post: capturar -> extrair -> reagir -> renderizar -> aprovar -> publicar."""
import asyncio, json, re, shutil, sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import config as C, crypto, db, feeds, ig, llm, midia, render, settings, telegram

RUNNING: set[int] = set()
MAX_FALHAS = 3
ESTADOS_ABERTOS = ("aguardando_aprovacao", "rascunho", "agendado", "falhou")
ANGULOS = ["opinião direta e provocativa, no formato 'Não é X, é Y'",
           "explicação simples para quem não é da área, com um exemplo do dia a dia",
           "impacto prático para empresários e gestores",
           "pergunta que provoque debate nos comentários"]


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
        if n and re.fullmatch(r"[0-9a-f]{32}\.(jpg|mp4)", n):
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


async def _processar(post_id: int, p: dict, temperature: float, destino: str = "aguardando_aprovacao",
                     com_print: bool = False) -> bool:
    po = post(post_id)
    formato = po["formato"] or "feed"
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
                res = await llm.reagir(con, p["contexto_md"], noticia, temperature, feedback, po["angulo"] or None)
            except ValueError as e:
                feedback = str(e)
                continue
            print_uri = await render.print_pagina(po["noticia_url"]) if (com_print and formato == "story") else None
            arquivo, estourou = await render.card(res["manchete_curta"], res["minha_reacao"], po["fonte"] or res["fonte"],
                                                  p["handle"], p["nome"], formato, print_uri)
            if estourou:
                _apagar(arquivo)
                feedback, arquivo = "minha_reacao não coube no card, encurte", None
                continue
            break
        if not arquivo:
            raise ValueError(f"o modelo não entregou uma saída válida em 3 tentativas ({feedback})")
        _set(post_id, destino, json_llm=json.dumps(res, ensure_ascii=False), manchete=res["manchete_curta"],
             reacao=res["minha_reacao"], legenda=res["legenda_instagram"], arquivo=arquivo, erro=None)
        db.log(p["id"], post_id, "gerado", f"confianca={res['confianca']}")
        if destino == "aguardando_aprovacao" and telegram.ativo() and p["telegram_chat_id"]:
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
        if destino == "aguardando_aprovacao" and telegram.ativo() and p["telegram_chat_id"]:
            await telegram.avisar(p["telegram_chat_id"], f"Falha ao gerar post #{post_id}: {msg[:200]}")
        return False


async def refazer(post_id: int) -> bool:
    po = post(post_id)
    if po and not po["noticia_url"]:  # mídia enviada por você: só a legenda muda
        return await _refazer_legenda(po)
    if not po or not _claim(post_id, ESTADOS_ABERTOS, "extraido"):
        return False
    old = po["arquivo"]
    p = perfil(po["perfil_id"])
    destino = "rascunho" if po["estado"] in ("rascunho", "agendado") else "aguardando_aprovacao"
    ok = await _processar(post_id, p, temperature=0.95, destino=destino)
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
    if not _claim(post_id, ESTADOS_ABERTOS, "publicando"):
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
        media = await ig.publicar(p["ig_user_id"], crypto.dec(p["ig_token_enc"]), f"{base}/{po['arquivo']}", po["legenda"], po["formato"])
        _set(post_id, "publicado", media_id=media, erro=None, agendado_para=None)
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
    if not po or not _claim(post_id, ESTADOS_ABERTOS, "descartado"):
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


# ---------------- pauta do dia e agenda local ----------------
async def pauta(perfil_id: int, n_noticias: int = 3, n_variacoes: int = 2, formato: str = "feed",
                com_print: bool = False, origem: str = "manual") -> int:
    """Pesquisa as notícias em alta dentro dos temas do perfil e cria n_variacoes rascunhos por notícia
    (ângulos diferentes). Nada é publicado: os rascunhos esperam você escolher e agendar. Devolve quantos criou."""
    if perfil_id in RUNNING:
        return 0
    RUNNING.add(perfil_id)
    try:
        p = perfil(perfil_id)
        if not p:
            return 0
        n_noticias, n_variacoes = max(1, min(n_noticias, 10)), max(1, min(n_variacoes, len(ANGULOS)))
        formato = formato if formato in ("feed", "story") else "feed"
        fl = db.q("SELECT * FROM feeds WHERE ativo=1 AND (perfil_id IS NULL OR perfil_id=?)", (perfil_id,))
        usadas = {r["noticia_url"] for r in db.q("SELECT noticia_url FROM posts WHERE perfil_id=? AND noticia_url IS NOT NULL", (perfil_id,))}
        palavras = [s.strip() for s in p["palavras_chave"].split(",") if s.strip()]
        cands = await feeds.candidatas(fl, palavras, p["max_idade_horas"], usadas)
        db.log(perfil_id, None, "pauta", f"{origem}: {len(cands)} candidatas")
        criados = noticias = falhas = 0
        for c in cands:
            if noticias >= n_noticias or falhas >= MAX_FALHAS:
                break
            grupo, texto, ok_noticia = None, "", False
            for v in range(1, n_variacoes + 1):
                try:
                    pid = db.x("INSERT INTO posts(perfil_id,estado,noticia_url,noticia_titulo,fonte,texto,variacao,grupo,formato,angulo,"
                               "criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                               (perfil_id, "capturado", c["url"], c["titulo"], c["fonte"], texto, v, grupo, formato,
                                ANGULOS[v - 1], db.now(), db.now()))
                except sqlite3.IntegrityError:
                    break
                if grupo is None:
                    grupo = pid
                    db.x("UPDATE posts SET grupo=? WHERE id=?", (pid, pid))
                if await _processar(pid, p, temperature=0.8, destino="rascunho", com_print=com_print and v == 1):
                    criados += 1
                    ok_noticia = True
                    texto = post(pid)["texto"]
                else:
                    falhas += 1
                    break
            if ok_noticia:
                noticias += 1
        if criados and telegram.ativo() and p["telegram_chat_id"]:
            await telegram.avisar(p["telegram_chat_id"], f"📝 Pauta pronta: {criados} rascunhos de {noticias} notícias. "
                                                         "Abra o painel (Pauta) para escolher e agendar.")
        return criados
    finally:
        RUNNING.discard(perfil_id)


def _utc(quando_local: str, tz: str) -> str | None:
    """'2026-10-17T09:30' (hora do fuso configurado) -> 'YYYY-MM-DD HH:MM:SS' em UTC."""
    try:
        d = datetime.strptime(quando_local, "%Y-%m-%dT%H:%M").replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        return None
    return d.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def agendar(ids: list[int], quando_local: str, intervalo_min: int = 60) -> int:
    """Marca os posts como agendados: o primeiro em quando_local, os seguintes com intervalo_min de distância."""
    from datetime import timedelta
    base = _utc(quando_local, settings.tz())
    if not base:
        return 0
    t0 = datetime.strptime(base, "%Y-%m-%d %H:%M:%S")
    feitos = 0
    for n, pid in enumerate(ids):
        quando = (t0 + timedelta(minutes=max(0, intervalo_min) * n)).strftime("%Y-%m-%d %H:%M:%S")
        feitos += db.x("UPDATE posts SET estado='agendado', agendado_para=?, atualizado_em=? "
                       "WHERE id=? AND estado IN ('rascunho','aguardando_aprovacao','agendado') AND arquivo IS NOT NULL",
                       (quando, db.now(), pid))
    return feitos


def desagendar(post_id: int) -> bool:
    return db.x("UPDATE posts SET estado='rascunho', agendado_para=NULL, atualizado_em=? WHERE id=? AND estado='agendado'",
                (db.now(), post_id)) == 1


def local(utc_str: str | None) -> str:
    """UTC do banco -> 'dd/mm HH:MM' no fuso configurado (para exibir)."""
    if not utc_str:
        return ""
    d = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return d.astimezone(ZoneInfo(settings.tz())).strftime("%d/%m %H:%M")


async def publicar_agendados() -> int:
    """Publica o que já passou da hora marcada. Chamado pelo agendador a cada ~30 s."""
    vencidos = db.q("SELECT id FROM posts WHERE estado='agendado' AND agendado_para<=? ORDER BY agendado_para", (db.now(),))
    for r in vencidos:
        asyncio.create_task(aprovar(r["id"], "agenda"))
    return len(vencidos)


# ---------------- foto/vídeo enviados pelo Telegram ----------------
AJUDA = ("Mande uma foto ou um vídeo com uma frase de contexto na legenda. Eu ajusto o formato, escrevo a legenda no seu tom "
         "e devolvo aqui para aprovar.\nPalavras que mudam o destino: story, reel, feed, “sem música”.")


async def _refazer_legenda(po: dict) -> bool:
    p = perfil(po["perfil_id"])
    if po["estado"] not in ESTADOS_ABERTOS or po["formato"] == "story" or not po["texto"]:
        return False
    con = conexao_do_perfil(p)
    try:
        leg = await llm.legenda_midia(con, p["contexto_md"], po["texto"], "vídeo" if po["arquivo"].endswith(".mp4") else "foto", 0.95)
    except Exception as e:
        db.log(p["id"], po["id"], "falhou_legenda", str(e))
        return False
    db.x("UPDATE posts SET legenda=?, atualizado_em=? WHERE id=?", (leg, db.now(), po["id"]))
    db.log(p["id"], po["id"], "legenda_refeita")
    if p["telegram_chat_id"]:
        await telegram.avisar(p["telegram_chat_id"], f"Nova legenda para #{po['id']}:\n\n{leg}")
    return True


def _destino(tipo: str, texto: str) -> tuple[str, str, bool]:
    """(formato, descricao_limpa, sem_musica) a partir das palavras-chave que o autor escreveu na legenda."""
    t = texto or ""
    sem = bool(re.search(r"(?i)\bsem\s+m[uú]sica\b", t))
    quer = re.search(r"(?i)\b(story|stories|reel|reels|feed)\b", t)
    t = re.sub(r"(?i)\b(sem\s+m[uú]sica|story|stories|reels?|feed)\b[:,.]?", "", t).strip()
    palavra = quer.group(1).lower() if quer else ""
    if palavra.startswith("stor"):
        formato = "story"
    else:
        formato = "reel" if tipo == "video" else "feed"
    return formato, re.sub(r"\s+", " ", t), sem


async def criar_de_midia(p: dict, tipo: str, src, texto: str) -> int:
    """Cria um post a partir de foto/vídeo seu: ajusta o formato (e a trilha), escreve a legenda e envia para aprovação."""
    formato, descricao, sem_musica = _destino(tipo, texto)
    musica, aviso = None, ""
    if tipo == "video" and p["musica_modo"] == "aleatoria" and not sem_musica:
        musica = midia.escolher_musica()
        if not musica:
            aviso = "ℹ️ Modo música ligado, mas não há músicas cadastradas (menu Músicas)."
    arquivo = await (midia.video(src, formato, musica) if tipo == "video" else midia.foto(src, formato))
    legenda = ""
    if formato != "story":
        con = conexao_do_perfil(p)
        if not descricao:
            aviso = (aviso + "\n" if aviso else "") + "ℹ️ Sem frase de contexto: legenda em branco. Edite no painel ou mande de novo com uma frase."
        elif not con or not con["modelo"]:
            aviso = (aviso + "\n" if aviso else "") + "⚠️ Nenhum LLM configurado: legenda em branco."
        else:
            legenda = await llm.legenda_midia(con, p["contexto_md"], descricao, "vídeo" if tipo == "video" else "foto")
    pid = db.x("INSERT INTO posts(perfil_id,estado,noticia_titulo,fonte,texto,legenda,arquivo,formato,criado_em,atualizado_em)"
               " VALUES(?,?,?,?,?,?,?,?,?,?)",
               (p["id"], "aguardando_aprovacao", (descricao or "Mídia do Telegram")[:120], "Telegram", descricao, legenda,
                arquivo, formato, db.now(), db.now()))
    db.log(p["id"], pid, "midia_recebida", f"{tipo} -> {formato}" + (f" musica={musica.name}" if musica else ""))
    if p["telegram_chat_id"]:
        resumo = f"{formato.upper()}" + (f" · trilha: {musica.stem}" if musica else "")
        mid = await telegram.enviar_card(p["telegram_chat_id"], C.CARDS / arquivo, pid,
                                         (legenda or "(sem legenda)") + f"\n\n[{resumo}]", aviso)
        db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, pid))
    return pid


async def mensagem_telegram(msg: dict) -> None:
    chat_id = str(msg.get("chat", {}).get("id", ""))
    p = db.one("SELECT * FROM perfis WHERE telegram_chat_id=? AND telegram_chat_id!='' ORDER BY ativo DESC, id LIMIT 1", (chat_id,))
    if not p:
        return  # só o dono do perfil manda conteúdo
    texto = msg.get("caption") or msg.get("text") or ""
    m = None
    if msg.get("photo"):
        m = ("foto", msg["photo"][-1], ".jpg")
    elif msg.get("video"):
        m = ("video", msg["video"], ".mp4")
    elif (msg.get("document") or {}).get("mime_type", "").startswith(("image/", "video/")):
        d = msg["document"]
        m = ("video" if d["mime_type"].startswith("video/") else "foto", d, ".bin")
    if not m:
        await telegram.avisar(chat_id, AJUDA)
        return
    tipo, arq, ext = m
    if (arq.get("file_size") or 0) > telegram.MAX_DOWNLOAD:
        await telegram.avisar(chat_id, "O Telegram só deixa o bot baixar arquivos de até 20 MB. Mande uma versão menor.")
        return
    tmp = C.DATA / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / f"{uuid_hex()}{ext}"
    try:
        await telegram.avisar(chat_id, "Recebi. Preparando…")
        await telegram.baixar(arq["file_id"], src)
        await criar_de_midia(p, tipo, src, texto)
    except Exception as e:
        db.log(p["id"], None, "midia_falhou", str(e))
        await telegram.avisar(chat_id, f"Não consegui preparar a mídia: {str(e)[:200]}")
    finally:
        src.unlink(missing_ok=True)


def uuid_hex() -> str:
    import uuid
    return uuid.uuid4().hex
