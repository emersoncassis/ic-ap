"""Fluxo de um post: capturar -> extrair -> reagir -> renderizar -> aprovar -> publicar."""
import asyncio, json, logging, re, shutil, sqlite3, threading, time
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import banco, config as C, crypto, db, distribuicao, feeds, ig, llm, marca as marca_mod, meta_ai, midia, render, settings, tarefas, telegram, vectorcraft, voz
from .agentes import OrquestradorAgente

orquestrador = OrquestradorAgente()

RUNNING: set[int] = set()
MAX_FALHAS = 3
FONTE_TEXTO = "Texto"  # posts criados a partir de uma ideia (conversa do Telegram)
FONTE_CITACAO = "Citação"
FONTE_MEME = "Meme"
_GERACAO = asyncio.Lock()  # uma geração por vez: poupa a GPU local
ESTADOS_ABERTOS = ("aguardando_aprovacao", "rascunho", "agendado", "falhou")
ANGULOS = ["opinião direta e provocativa, no formato 'Não é X, é Y'",
           "explicação simples para quem não é da área, com um exemplo do dia a dia",
           "impacto prático para empresários e gestores",
           "pergunta que provoque debate nos comentários"]


def perfil(pid: int) -> dict | None:
    return db.one("SELECT * FROM perfis WHERE id=?", (pid,))


def excluir_perfil(pid: int) -> bool:
    """Exclui um perfil e todos os seus dados associados (posts, feeds exclusivos, arquivos de mídia, logo e configurações)."""
    p = perfil(pid)
    if not p:
        return False

    RUNNING.discard(pid)

    # Remove arquivos de mídia gerados para os posts deste perfil
    posts = db.q("SELECT arquivo, arquivos, capa FROM posts WHERE perfil_id=?", (pid,))
    for po in posts:
        for arq in [po.get("arquivo"), po.get("capa")]:
            if arq:
                try:
                    (C.CARDS / arq).unlink(missing_ok=True)
                    (C.PUBLIC / arq).unlink(missing_ok=True)
                except Exception:
                    pass
        if po.get("arquivos"):
            try:
                for arq in json.loads(po["arquivos"]):
                    (C.CARDS / arq).unlink(missing_ok=True)
                    (C.PUBLIC / arq).unlink(missing_ok=True)
            except Exception:
                pass

    # Remove logotipo associado ao perfil
    try:
        marca_mod.remover_logo(pid)
    except Exception:
        pass

    # Limpa registros no banco de dados vinculados ao perfil
    db.x("DELETE FROM publicacoes_canais WHERE post_id IN (SELECT id FROM posts WHERE perfil_id=?)", (pid,))
    db.x("DELETE FROM aprendizados WHERE perfil_id=?", (pid,))
    db.x("DELETE FROM canais_distribuicao WHERE perfil_id=?", (pid,))
    db.x("DELETE FROM eventos WHERE perfil_id=?", (pid,))
    db.x("DELETE FROM feeds WHERE perfil_id=?", (pid,))
    db.x("DELETE FROM posts WHERE perfil_id=?", (pid,))
    db.x("DELETE FROM settings WHERE k=?", (f"metatmp:{pid}",))
    db.x("DELETE FROM perfis WHERE id=?", (pid,))

    return True



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


def conexao_do_modulo(modulo: str, p: dict | None = None) -> dict | None:
    """Conexão de LLM configurada especificamente para o módulo funcional ('chat', 'legenda', 'noticias', 'roteiro').
    Permite rodar múltiplos modelos simultâneos alocados por tarefa funcional.
    """
    from . import hardware
    return hardware.obter_conexao_modulo(modulo, p)


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


def _tentar_apagar(caminho: Path, tentativas: int, intervalo: float) -> bool:
    for i in range(tentativas):
        try:
            caminho.unlink(missing_ok=True)
            return True
        except PermissionError:  # Windows não apaga arquivo ainda aberto (antivírus, indexador, ffmpeg acabando de soltar)
            if i < tentativas - 1:
                time.sleep(intervalo)
    return False


def _apagar(*nomes) -> None:
    """Apaga arquivos de CARDS. Síncrona e com espera: em código assíncrono chame por `_apagar_async` (thread).
    Se o Windows ainda estiver com o arquivo preso depois de ≈5 s, uma thread de fundo continua tentando por 2 min."""
    for n in nomes:
        if n and re.fullmatch(r"[0-9a-f]{32}\.(jpg|mp4)", n):
            caminho = C.CARDS / n
            if not _tentar_apagar(caminho, 10, 0.5):
                logging.getLogger(__name__).warning("arquivo %s em uso: vou tentar apagar em segundo plano", n)
                threading.Thread(target=_tentar_apagar, args=(caminho, 60, 2.0), daemon=True).start()


async def _apagar_async(*nomes) -> None:
    await asyncio.to_thread(_apagar, *nomes)


def arquivos_do_post(po: dict) -> list[str]:
    """Todos os arquivos do post: os slides do carrossel, ou o arquivo único."""
    try:
        lst = json.loads(po.get("arquivos") or "[]")
    except ValueError:
        lst = []
    return [a for a in lst if isinstance(a, str)] or ([po["arquivo"]] if po.get("arquivo") else [])


def _apagar_post(po: dict) -> None:
    _apagar(*arquivos_do_post(po), po.get("capa"))


async def gerar(perfil_id: int, n: int = 1, origem: str = "manual") -> int:
    """Gera até n posts aguardando aprovação (prioriza Meta AI + Técnica Blow Up no Instagram quando configurado)."""
    if perfil_id in RUNNING:
        return 0
    RUNNING.add(perfil_id)
    try:
        p = perfil(perfil_id)
        if not p:
            return 0
        if settings.segredo("meta_ai_cookies"):
            con = conexao_do_perfil(p) or {}
            feitos = 0
            for _ in range(max(1, n)):
                try:
                    pedido_auto = (
                        f"Pesquise no Instagram para @{p['handle'].lstrip('@')} a tendência mais quente de hoje "
                        f"em {p.get('palavras_chave') or 'Private AI, Segurança Eletrônica e Infraestrutura'} "
                        f"e crie 1 post viral completo usando a Técnica Blow Up."
                    )
                    res_est = await orquestrador.estudio.criar_post(
                        con=con,
                        perfil=p,
                        pedido=pedido_auto,
                        formato_forcado="feed",
                    )
                    res_orq = {
                        "acao": res_est.get("formato", "feed"),
                        "dados": res_est,
                        "resposta_telegram": res_est.get("legenda", ""),
                    }
                    chat_id_tg = str(p.get("telegram_chat_id") or "")
                    if chat_id_tg and telegram.ativo():
                        await _criar_e_enviar_post_agente(p, chat_id_tg, res_orq)
                    else:
                        db.x(
                            "INSERT INTO posts(perfil_id, estado, noticia_titulo, fonte, texto, json_llm, manchete, reacao, legenda, arquivo, formato, criado_em, atualizado_em) "
                            "VALUES(?, 'aguardando_aprovacao', ?, 'Meta AI Blow Up', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                p["id"],
                                (res_est.get("manchete") or "Post Blow Up")[:120],
                                res_est.get("corpo") or "",
                                json.dumps(res_est, ensure_ascii=False),
                                res_est.get("manchete") or "",
                                res_est.get("corpo") or "",
                                res_est.get("legenda") or "",
                                res_est.get("arquivo_card") or "",
                                res_est.get("formato", "feed"),
                                db.now(),
                                db.now(),
                            ),
                        )
                    feitos += 1
                except Exception as e:
                    db.log(perfil_id, None, "falhou", str(e)[:300])
            return feitos

        fl = db.q("SELECT * FROM feeds WHERE ativo=1 AND perfil_id=?", (perfil_id,))
        if not fl:
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
        modulo = "noticias" if po.get("noticia_url") else "legenda"
        con = conexao_do_modulo(modulo, p)
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
                                                  p["handle"], p["nome"], formato, print_uri, p)
            if estourou:
                await _apagar_async(arquivo)
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
    if po and po["fonte"] == FONTE_TEXTO:
        return await _refazer_texto(po)
    if po and po["fonte"] in (FONTE_CITACAO, FONTE_MEME):
        return await _refazer_visual(po)
    if po and not po["noticia_url"]:  # mídia enviada por você: só a legenda muda
        return await _refazer_legenda(po)
    if not po or not _claim(post_id, ESTADOS_ABERTOS, "extraido"):
        return False
    p = perfil(po["perfil_id"])
    destino = "rascunho" if po["estado"] in ("rascunho", "agendado") else "aguardando_aprovacao"
    ok = await _processar(post_id, p, temperature=0.95, destino=destino)
    if ok:
        await asyncio.to_thread(_apagar_post, po)
        db.log(p["id"], post_id, "refeito")
        if po["tg_message_id"] and p["telegram_chat_id"]:
            await telegram.marcar(p["telegram_chat_id"], po["tg_message_id"], "Refeito. Nova versão abaixo.")
    return ok


async def aprovar(post_id: int, origem: str = "painel") -> bool:
    po = post(post_id)
    arqs = arquivos_do_post(po) if po else []
    if not arqs or not all((C.CARDS / a).exists() for a in arqs):
        return False
    if not _claim(post_id, ESTADOS_ABERTOS, "publicando"):
        return False
    p = perfil(po["perfil_id"])
    pubs: list = []
    try:
        base = settings.base_url()
        if not base:
            raise ig.MetaError("URL pública não configurada (menu Conexões)")
        if not p["ig_user_id"] or not p["ig_token_enc"]:
            raise ig.MetaError("perfil sem ig_user_id ou token")
        for a in arqs:
            shutil.copyfile(C.CARDS / a, C.PUBLIC / a)
            pubs.append(C.PUBLIC / a)
        capa = po.get("capa") or ""
        if capa and (C.CARDS / capa).exists() and po["formato"] == "reel":
            shutil.copyfile(C.CARDS / capa, C.PUBLIC / capa)  # thumb do Reel (cover_url)
            pubs.append(C.PUBLIC / capa)
        else:
            capa = ""
        token = crypto.dec(p["ig_token_enc"])
        if po["formato"] == "carrossel":
            media = await ig.publicar_carrossel(p["ig_user_id"], token, [f"{base}/{a}" for a in arqs], po["legenda"])
        else:
            media = await ig.publicar(p["ig_user_id"], token, f"{base}/{arqs[0]}", po["legenda"], po["formato"],
                                      [m for m in (po["mencoes"] or "").split(",") if m], f"{base}/{capa}" if capa else "")
        _set(post_id, "publicado", media_id=media, erro=None, agendado_para=None)
        db.log(p["id"], post_id, "publicado", f"{origem} media={media}")
        resultado = "✅ Publicado no Instagram."

        # Distribuição Multiplataforma Local (Threads, YouTube Shorts, LinkedIn, TikTok)
        try:
            res_multi = await distribuicao.publicar_multiplataforma(post_id, p["id"], base)
            if res_multi.get("sucessos"):
                resultado = f"✅ Publicado no Instagram, {', '.join(res_multi['sucessos'])}."
            if res_multi.get("falhas"):
                resultado += f" (⚠️ Falhas: {'; '.join(res_multi['falhas'])})"
        except Exception as e_dist:
            resultado += f" (⚠️ Falha na distribuição multi: {str(e_dist)[:100]})"
    except Exception as e:
        _set(post_id, "falhou", erro=str(e)[:400])
        db.log(p["id"], post_id, "falhou_publicar", str(e))
        resultado = f"❌ Falha ao publicar: {str(e)[:200]}"
    finally:
        for f in pubs:
            f.unlink(missing_ok=True)  # a imagem só fica pública durante o publish
    if po["tg_message_id"] and p["telegram_chat_id"]:
        await telegram.marcar(p["telegram_chat_id"], po["tg_message_id"], resultado)
    return resultado.startswith("✅")


async def descartar(post_id: int, origem: str = "painel") -> bool:
    po = post(post_id)
    if not po or not _claim(post_id, ESTADOS_ABERTOS, "descartado"):
        return False
    await asyncio.to_thread(_apagar_post, po)
    p = perfil(po["perfil_id"])
    db.log(p["id"], post_id, "descartado", origem)
    if po["tg_message_id"] and p["telegram_chat_id"]:
        await telegram.marcar(p["telegram_chat_id"], po["tg_message_id"], "🗑 Descartado.")
    return True


async def acao_telegram(acao: str, post_id: int, chat_id: str) -> None:
    if acao in ("sp", "np"):  # confirmar / ajustar o perfil proposto na conversa (post_id é o id do perfil)
        await _acao_perfil(acao, post_id, chat_id)
        return
    if acao == "as":  # horário escolhido: post_id vem como id*10 + posição do horário
        post_id, pos = divmod(post_id, 10)
        po = post(post_id)
        p = perfil(po["perfil_id"]) if po else None
        if not p or str(p["telegram_chat_id"]) != chat_id:
            return
        slots = proximos_horarios(p)
        if pos >= len(slots) or po["estado"] not in ESTADOS_ABERTOS:
            await telegram.avisar(chat_id, "Esse horário já não está livre ou o post mudou. Toque em 🕒 Agendar de novo.")
            return
        if agendar([post_id], slots[pos], 0):
            quando = local(post(post_id)["agendado_para"])
            db.log(p["id"], post_id, "agendado", f"telegram {quando}")
            if po["tg_message_id"]:
                await telegram.marcar(chat_id, po["tg_message_id"], f"🕒 Agendado para {quando}.")
        return
    if acao == "at":  # agenda todos os pendentes da esteira nos horários sugeridos
        pf = db.one("SELECT * FROM perfis WHERE telegram_chat_id=? AND telegram_chat_id!='' ORDER BY ativo DESC, id LIMIT 1", (chat_id,))
        if not pf:
            return
        feitos = []
        for r in db.q("SELECT * FROM posts WHERE perfil_id=? AND estado='aguardando_aprovacao' AND fonte='Telegram' ORDER BY agendado_para, id", (pf["id"],)):
            quando = _agendar_sugerido(r, pf)
            if quando:
                feitos.append(f"• #{r['id']} → {quando}")
                if r["tg_message_id"]:
                    await telegram.marcar(chat_id, r["tg_message_id"], f"🕒 Agendado para {quando}.")
        await telegram.avisar(chat_id, ("✅ Agendados:\n" + "\n".join(feitos)) if feitos else "Não há posts pendentes para agendar.")
        return
    po = post(post_id)
    p = perfil(po["perfil_id"]) if po else None
    if not p or str(p["telegram_chat_id"]) != chat_id:
        return  # só o dono do perfil aprova os posts dele
    if acao == "ak":  # confirma o horário sugerido no card
        quando = _agendar_sugerido(po, p)
        if quando and po["tg_message_id"]:
            await telegram.marcar(chat_id, po["tg_message_id"], f"🕒 Agendado para {quando}.")
        elif not quando:
            await telegram.avisar(chat_id, "Esse post não pode ser agendado agora.")
        return
    if acao == "ap":
        await aprovar(post_id, "telegram")
    elif acao == "rf":
        await refazer(post_id)
    elif acao == "ds":
        await descartar(post_id, "telegram")
    elif acao == "ag":  # menu de horários livres
        slots = proximos_horarios(p)
        if not slots or po["estado"] not in ESTADOS_ABERTOS:
            await telegram.avisar(chat_id, "Esse post não pode ser agendado agora.")
            return
        rot = lambda q: datetime.strptime(q, "%Y-%m-%dT%H:%M").strftime("%d/%m %H:%M")
        await telegram.enviar_botoes(chat_id, f"Quando publicar o post #{post_id}? (fuso {settings.tz()})",
                                     [[(rot(q), f"as:{post_id * 10 + i}")] for i, q in enumerate(slots)])
    elif acao == "ia":  # versão em vídeo por IA (demora minutos: roda em segundo plano)
        tarefas.disparar(animar_post(post_id))
    elif acao == "ad":  # copia o post para o outro formato (feed <-> story)
        destino = "story" if po["formato"] == "feed" else "feed"
        try:
            if not await adaptar(post_id, destino):
                await telegram.avisar(chat_id, "Esse post não pode ser adaptado (só imagens de feed ou story).")
        except Exception as e:
            db.log(p["id"], post_id, "adaptar_falhou", str(e))
            await telegram.avisar(chat_id, f"Não consegui adaptar: {str(e)[:200]}")
    elif acao == "tpl":  # alternar estilo visual do template (cyber_glass -> editorial_bold -> alerta_critico -> clean_minimalist)
        await alternar_estilo_post(post_id, chat_id)


async def alternar_estilo_post(post_id: int, chat_id: str, estilo_forcado: str | None = None) -> bool:
    """Alterna o layout do post entre os 6 novos layouts dinâmicos (editorial, impacto_foto, lista, dado, alerta, citacao)
    e re-renderiza o card imediatamente com o novo design."""
    import base64
    po = post(post_id)
    if not po or po["formato"] not in ("feed", "story"):
        return False
    p = perfil(po["perfil_id"])
    if not p:
        return False

    ordem = ["editorial", "impacto_foto", "lista", "dado", "alerta", "citacao"]
    layout_atual = po.get("angulo") or "editorial"
    if layout_atual not in ordem:
        layout_atual = "editorial"

    if estilo_forcado and estilo_forcado in ordem:
        proximo_layout = estilo_forcado
    else:
        proximo_layout = ordem[(ordem.index(layout_atual) + 1) % len(ordem)]

    manchete = po["manchete"] or po["noticia_titulo"] or po["texto"] or "Destaque"
    reacao = po["reacao"] or po["texto"] or ""
    formato = po["formato"]

    # Cores e selos contextualizados ao layout
    paletas_layout = {
        "editorial": {"fundo": "#0d1117", "texto_primario": "#f8fafc", "texto_secundario": "#94a3b8", "destaque": "#f59e0b", "acento": "rgba(245, 158, 11, 0.12)", "borda": "rgba(255, 255, 255, 0.1)"},
        "impacto_foto": {"fundo": "#080a0f", "texto_primario": "#ffffff", "texto_secundario": "#94a3b8", "destaque": "#00f0ff", "acento": "rgba(0, 240, 255, 0.15)", "borda": "rgba(255, 255, 255, 0.12)"},
        "lista": {"fundo": "#080a0f", "texto_primario": "#ffffff", "texto_secundario": "#94a3b8", "destaque": "#10b981", "acento": "rgba(16, 185, 129, 0.12)", "borda": "rgba(255, 255, 255, 0.1)"},
        "dado": {"fundo": "#080a0f", "texto_primario": "#ffffff", "texto_secundario": "#94a3b8", "destaque": "#00f0ff", "acento": "rgba(0, 240, 255, 0.15)", "borda": "rgba(255, 255, 255, 0.12)"},
        "alerta": {"fundo": "#0a0709", "texto_primario": "#ffffff", "texto_secundario": "#cbd5e1", "destaque": "#ef4444", "acento": "rgba(239, 68, 68, 0.16)", "borda": "rgba(239, 68, 68, 0.28)"},
        "citacao": {"fundo": "#0a0d14", "texto_primario": "#ffffff", "texto_secundario": "#94a3b8", "destaque": "#38bdf8", "acento": "rgba(56, 189, 248, 0.12)", "borda": "rgba(255, 255, 255, 0.1)"},
    }
    paleta = paletas_layout.get(proximo_layout, paletas_layout["editorial"])

    selo_uri = None
    if proximo_layout == "alerta":
        svg_s = vectorcraft.criar_badge_vetorial("ALERTA", "alerta_vermelho", "URGENTE", 560 if formato == "story" else 480, 130)
        selo_uri = f"data:image/svg+xml;base64,{base64.b64encode(svg_s.encode('utf-8')).decode('ascii')}"

    meta_llm = {}
    if po.get("json_llm"):
        try:
            meta_llm = json.loads(po["json_llm"])
        except Exception:
            meta_llm = {}
    copy_meta = meta_llm.get("copy") if isinstance(meta_llm.get("copy"), dict) else {}
    cta_padrao = "Responda no Direct" if formato == "story" else "Salve este post"
    cta_final = copy_meta.get("cta_texto") or cta_padrao
    if formato == "story" and "legenda" in cta_final.lower():
        cta_final = "Responda no Direct"

    try:
        novo_arq, _ = await render.render_design(
            layout=proximo_layout,
            formato=formato,
            manchete=manchete,
            paragrafos=reacao,
            handle=p["handle"],
            nome=p["nome"],
            palavras_destaque=copy_meta.get("palavras_destaque"),
            itens=copy_meta.get("itens_card"),
            dado=copy_meta.get("dado_destaque"),
            dado_legenda=copy_meta.get("dado_legenda"),
            frase_impacto=copy_meta.get("frase_impacto"),
            cta_texto=cta_final,
            post_tipo_label="Story" if formato == "story" else "Post de Feed",
            selo_uri=selo_uri,
            paleta=paleta,
            p=p,
            pid=post_id,
        )
    except Exception as e:
        await telegram.avisar(chat_id, f"Não foi possível trocar o estilo: {str(e)[:200]}")
        return False

    db.x("UPDATE posts SET arquivo=?, angulo=?, atualizado_em=? WHERE id=?",
         (novo_arq, proximo_layout, db.now(), post_id))
    db.log(p["id"], post_id, "estilo_alterado", proximo_layout)

    nomes_formatados = {
        "editorial": "Editorial Bold (Tipografia & Sofisticação)",
        "impacto_foto": "Impacto Visual (Foto & Manchete Gigante)",
        "lista": "Lista Estratégica (Passos & Alta Retenção)",
        "dado": "Dado de Impacto (Estatística Central)",
        "alerta": "Alerta Crítico (Breaking News / Urgência)",
        "citacao": "Citação Autoral (Frase Forte & Assinatura)",
    }
    aviso = f"🎨 *Layout Atualizado:* `{nomes_formatados.get(proximo_layout, proximo_layout.upper())}`\n• Novo design renderizado com sucesso!"
    legenda = "" if formato == "story" else (po["legenda"] or "")
    try:
        mid = await telegram.enviar_card(chat_id, C.CARDS / novo_arq, post_id, legenda or f"({formato.title()} {proximo_layout})", aviso)
        db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, post_id))
    except Exception as e:
        db.log(p["id"], post_id, "telegram_falhou", str(e))
    return True


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
        fl = db.q("SELECT * FROM feeds WHERE ativo=1 AND perfil_id=?", (perfil_id,))
        if not fl:
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


def proximos_horarios(p: dict, n: int = 4) -> list[str]:
    """Próximos n horários livres do perfil ('YYYY-MM-DDTHH:MM', fuso configurado), pelos horários de postagem dele, sem repetir horário já agendado."""
    from datetime import timedelta
    tz = ZoneInfo(settings.tz())
    horas = [h for h in (p.get("horarios") or "").split(",") if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h.strip())] or ["09:00", "18:00"]
    ocupados = {r["agendado_para"] for r in db.q("SELECT agendado_para FROM posts WHERE estado IN ('agendado','aguardando_aprovacao','rascunho') AND agendado_para IS NOT NULL AND perfil_id=?", (p["id"],))}
    agora = datetime.now(tz) + timedelta(minutes=5)
    out = []
    for dia in range(0, 15):
        for h in sorted(x.strip() for x in horas):
            d = datetime.strptime(f"{(agora + timedelta(days=dia)).strftime('%Y-%m-%d')} {h}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
            quando = f"{d.strftime('%Y-%m-%dT%H:%M')}"
            if d > agora and _utc(quando, settings.tz()) not in ocupados:
                out.append(quando)
                if len(out) == n:
                    return out
    return out


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
        tarefas.disparar(aprovar(r["id"], "agenda"))
    return len(vencidos)


# ---------------- foto/vídeo enviados pelo Telegram ----------------
AJUDA = ("Eu sou seu assistente de conteúdo e orquestrador de agentes. Converse comigo em texto livre:\n"
         "• Técnica Blow Up: envie qualquer link do Instagram (ou /blowup <link>) para o Meta AI no navegador dissecar o gancho e recriar o post para você\n"
         "• Montar/rever o perfil: /perfil (eu faço perguntas e proponho o texto; você confirma)\n"
         "• Ideias de posts: /ideias, ou peça um tema\n"
         "• Carrossel: /carrossel <ideia> (planeja sequência com capa, loops e CTA)\n"
         "• Selos e Badges (VectorCraft): /badge <texto> [estilo] (ex: /badge NOVO neon_ciano | Exclusivo)\n"
         "• Overlays Seguros (VectorCraft): /overlay <titulo> | <subtitulo> (respeita safe-zones de Reels/Shorts)\n"
         "• Arte Vetorial Livre (VectorCraft): /arte <descrição> (cria composições visuais com formas e brilho)\n"
         "• Extrair Gancho Viral: /hook <texto_ou_roteiro> (desconstrói a fórmula e adapta para você)\n"
         "• Hashtags SEO: /hashtags <tema_ou_texto> (conjunto de 3 a 5 tags calibradas)\n"
         "• Auditar texto: /auditar <texto> (score de robô/IA e clichês)\n"
         "• Humanizar texto: /humanizar <texto> (remove vícios de IA e emojis excessivos)\n"
         "• Gerar: “faz um carrossel de 6 slides sobre X”, “um story sobre Y”, “2 versões para testar”\n"
         "• Foto: é só mandar (pode ser um monte de uma vez). Eu olho a imagem, escrevo a legenda e uma frase sobre a foto, ponho trilha e sugiro o horário; você só dá OK. Escrever “feed”, “story” ou “reel” na legenda troca o formato\n"
         "• Vídeo com mais de 30 s: eu entrego um Reel e um Story, os dois legendados, com thumb e legenda do Instagram prontas (escrever story/reel/feed na legenda faz só um)\n"
         "• Foto ou vídeo: escreva o pedido na legenda. Ex.: “story animado com música e um texto sério, tom de CEO”, “reel sem música”, “feed: treino de hoje”\n"
         "• Vídeo: “corta os silêncios”, “legenda animada” (precisa de Transcrição em Conexões). Foto: “narra: …” ou só “com narração” (precisa de Voz em Conexões)\n"
         "• Marca: “meu fundo é azul escuro #0b1f3a e o destaque é amarelo”; logotipo: envie o arquivo com a legenda “logo”\n"
         "• Citação: “faz uma citação sobre X” (com “foto de fundo” usa banco de imagens); meme: “meme sobre X”, ou envie sua foto com a legenda “meme: …”\n"
         "• Postagem simultânea: /canais (vê os canais ativos: Threads, YouTube Shorts, LinkedIn, TikTok)\n"
         "• Botão 🕒 Agendar em cada card escolhe o próximo horário livre do perfil\n"
         "• Botão 📐 em cada card copia o post para Story/Feed sem cortar a imagem; 🎬 transforma a sua foto em vídeo por IA (Higgsfield, gasta créditos). Na legenda da foto: “vídeo com IA”\n"
         "• /novo zera a conversa")


async def _refazer_legenda(po: dict) -> bool:
    p = perfil(po["perfil_id"])
    if po["estado"] not in ESTADOS_ABERTOS or po["formato"] == "story" or not po["texto"]:
        return False
    con = conexao_do_modulo("legenda", p)
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


def _pedidos(texto: str) -> dict:
    """O que o autor pediu em linguagem livre na legenda da mídia: animação, música, texto na tela, corte de silêncio, legendas animadas, narração."""
    t = re.sub(r"(?i)\bsem\s+m[uú]sica\b", "", texto or "")
    legendar = bool(re.search(r"(?i)\blegendas?\s+animad\w+|\blegendar\b|\bkaraok\w+", t))
    t2 = re.sub(r"(?i)\blegendas?\s+animad\w+|\blegendar\b|\bkaraok\w+", "", t)
    return {"animar": bool(re.search(r"(?i)\banim\w*|\bmovimento\b|\bzoom\b", t2)),
            "musica": bool(re.search(r"(?i)\bm[uú]sica\b|\btrilha\b", t2)),
            "texto": bool(re.search(r"(?i)\b(legenda|texto|frase|escrev\w+)\b", t2)),
            "cortar": bool(re.search(r"(?i)\b(sil[eê]ncios?|pausas?)\b", t2)),
            "legendar": legendar,
            "narrar": bool(re.search(r"(?i)\b(narr\w+|locu[cç]\w+|voz\s+em\s+off)\b", t2)),
            "ia": bool(re.search(r"(?i)\bhiggs\w*|\b(anim\w+|v[ií]deo|movimento)\s+(com|por|via|de)\s+(ia|intelig[eê]ncia\s+artificial)\b", t2))}


_IA_EM_CURSO: set[int] = set()


async def _video_ia(p: dict, imagem, pedido: str) -> Path:
    """Foto -> vídeo de ~5 s pelo Higgsfield (gasta créditos). A foto fica pública só durante a geração. Devolve o MP4 em data/tmp."""
    base = settings.base_url()
    if not base:
        raise banco.BancoError("URL pública não configurada (Conexões): o Higgsfield precisa buscar a foto por ela")
    con = conexao_do_modulo("roteiro", p)
    if con and con["modelo"]:
        try:
            prompt = await llm.prompt_movimento(con, pedido or "movimento sutil e cinematográfico")
        except ValueError:
            prompt = "Slow cinematic push-in, subtle natural motion, realistic, vertical 9:16"
    else:
        prompt = "Slow cinematic push-in, subtle natural motion, realistic, vertical 9:16"
    nome = f"{uuid_hex()}.jpg"
    publico = await midia.preparar_publico(Path(imagem), nome)
    destino = C.DATA / "tmp" / f"{uuid_hex()}.mp4"
    try:
        await banco.animar_foto(f"{base}/{nome}", prompt, destino)
    finally:
        publico.unlink(missing_ok=True)
    return destino


async def animar_post(post_id: int) -> int | None:
    """Botão 🎬: cria uma versão em vídeo 9:16 (.mp4) de um post.
    Se o Higgsfield estiver configurado, usa IA image-to-video; caso contrário, usa o motor local de Motion & Áudio (Ken Burns + Overlay + Trilha)."""
    po = post(post_id)
    arq_atual = po["arquivo"] if po else ""
    if not po or not arq_atual or not arq_atual.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        return None
    if post_id in _IA_EM_CURSO or not (C.CARDS / arq_atual).exists():
        return None
    p = perfil(po["perfil_id"])
    _IA_EM_CURSO.add(post_id)
    video_tmp = None
    fundo_tmp = None
    overlay_tmp = None
    try:
        formato = "story" if po["formato"] == "story" else "reel"
        usa_higgs = bool(banco.higgs_chave() and settings.base_url())
        if usa_higgs:
            if p["telegram_chat_id"] and telegram.ativo():
                await telegram.avisar(p["telegram_chat_id"], f"🎬 Gerando o vídeo por IA (Higgsfield) do post #{post_id}...")
            video_tmp = await _video_ia(p, C.CARDS / arq_atual, po["texto"] or po["noticia_titulo"] or "")
            arquivo = await midia.video(video_tmp, formato)
        else:
            if p["telegram_chat_id"] and telegram.ativo():
                await telegram.avisar(p["telegram_chat_id"], f"🎬 Renderizando Vídeo Animado 9:16 (Motion + Trilha Sonora) do post #{post_id}...")
            musica_v = midia.escolher_musica() or await midia.trilha_padrao()
            manchete_v = po["manchete"] or po["noticia_titulo"] or po["texto"] or "Destaque"
            # Tenta buscar uma fotografia limpa do tema para animar no fundo e sobrepor o título com fade
            src_animar = C.CARDS / arq_atual
            try:
                fundo_tmp = C.DATA / "tmp" / f"anim_bg_{uuid_hex()}.jpg"
                await banco.baixar_uma(manchete_v, fundo_tmp, orientacao="portrait")
                if fundo_tmp.exists():
                    src_animar = fundo_tmp
                    overlay_tmp = await render.overlay_story(manchete_v, p["handle"], p, altura=1920)
            except Exception:
                src_animar = C.CARDS / arq_atual
                overlay_tmp = None
            arquivo = await midia.story_animado(src_animar, musica=musica_v, overlay=overlay_tmp, dur=8.0)
    except Exception as e:
        db.log(p["id"], post_id, "video_ia_falhou", str(e))
        if p["telegram_chat_id"] and telegram.ativo():
            await telegram.avisar(p["telegram_chat_id"], f"Não consegui gerar o vídeo: {str(e)[:200]}")
        return None
    finally:
        _IA_EM_CURSO.discard(post_id)
        for t in (video_tmp, fundo_tmp, Path(overlay_tmp) if overlay_tmp else None):
            if t:
                t.unlink(missing_ok=True)
    legenda = "" if formato == "story" else po["legenda"]
    pid = db.x("INSERT INTO posts(perfil_id,estado,noticia_titulo,fonte,texto,reacao,manchete,legenda,arquivo,formato,mencoes,criado_em,atualizado_em)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (po["perfil_id"], "aguardando_aprovacao", po["noticia_titulo"], "Telegram", po["texto"], po["reacao"], po["manchete"], legenda, arquivo, formato,
                po["mencoes"], db.now(), db.now()))
    db.log(po["perfil_id"], pid, "video_ia", f"#{post_id} -> {formato}")
    if p["telegram_chat_id"] and telegram.ativo():
        mid = await telegram.enviar_card(p["telegram_chat_id"], C.CARDS / arquivo, pid, legenda or "(Story Animado)",
                                         (f"🎬 Vídeo por IA do post #{post_id} pronto!" if usa_higgs else f"🎬 Vídeo animado 9:16 do post #{post_id} pronto!"))
        db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, pid))
    return pid


def _roteiro_literal(texto: str) -> str:
    """Texto que o autor mandou falar: entre aspas, ou depois de 'narra:'. Vazio se ele só pediu narração."""
    m = re.search(r"[\"“”«]([^\"“”»]{20,})[\"“”»]", texto or "") or re.search(r"(?is)\bnarr\w*\s*:\s*(.{20,})$", texto or "")
    return m.group(1).strip() if m else ""


async def criar_de_midia(p: dict, tipo: str, src, texto: str) -> int:
    """Cria um post a partir de foto/vídeo seu. Entende pedidos em texto livre: story/reel/feed, animação, música, texto na tela, tom,
    corte de silêncio, legendas animadas (Whisper) e narração (voz local). Ajusta o formato, escreve a legenda e envia para aprovação."""
    formato, descricao, sem_musica = _destino(tipo, texto)
    ped = _pedidos(texto)
    con = conexao_do_modulo("roteiro" if formato in ("reel", "story") else "legenda", p)
    # esteira: toda foto sai pronta (legenda, frase sobre a imagem, trilha). O padrão do perfil vale quando o autor não escreveu story/reel/feed.
    auto = tipo == "foto" and p["esteira"] in ("reel", "feed", "story")
    if auto and not re.search(r"(?i)\b(story|stories|reels?|feed)\b", texto or ""):
        formato = p["esteira"]
    if auto and formato in ("reel", "story"):
        ped = {**ped, "animar": True}
    avisos: list[str] = []
    extras: list[str] = []
    tmp: list = []  # arquivos temporários a apagar no fim
    palavras: list[dict] = []
    animado = tipo == "foto" and (formato == "story" or (auto and formato == "reel")) and (ped["animar"] or ped["musica"])
    quer_musica = not sem_musica and ((auto and animado) or (tipo == "video" and (p["musica_modo"] == "aleatoria" or ped["musica"]))
                                      or (tipo == "foto" and (animado or ped["narrar"] or ped["ia"]) and (ped["musica"] or p["musica_modo"] == "aleatoria")))
    musica = None
    if quer_musica:
        musica = midia.escolher_musica()
        if not musica and auto:
            musica = await midia.trilha_padrao()  # sem músicas cadastradas: trilha suave própria
        elif not musica:
            avisos.append("ℹ️ Pediu música, mas não há músicas cadastradas (menu Músicas do painel).")
    mencoes = list(dict.fromkeys(m.rstrip(".") for m in re.findall(r"@[A-Za-z0-9_.]{2,30}", texto or "")))
    texto_tela, overlay, audio_fala, dur_fala = "", None, None, 7.0
    fonte_ia = None
    analise: dict | None = None
    try:
        # --- esteira: o modelo olha a foto e escreve legenda e frase sobre a imagem ---
        if auto:
            if not con or not con["modelo"]:
                avisos.append("⚠️ Nenhum LLM configurado: sem legenda nem frase na imagem (menu LLM do painel).")
            else:
                try:
                    analise = await llm.analisar_foto(con, p["contexto_md"], await midia.miniatura_b64(src), descricao)
                    descricao = descricao or analise["descricao"]
                    texto_tela = analise["texto_tela"]
                except Exception as e:
                    db.log(p["id"], None, "analise_foto_falhou", str(e))
                    avisos.append(f"⚠️ Não consegui analisar a foto: {str(e)[:200]}")
        # --- vídeo por IA (Higgsfield): a foto vira um clipe curto; daqui em diante segue como vídeo ---
        if ped["ia"] and tipo == "foto":
            try:
                fonte_ia = await _video_ia(p, src, descricao or texto)
                tmp.append(fonte_ia)
                tipo, animado = "video", False
                formato = "story" if formato == "story" else "reel"
                extras.append("vídeo por IA")
            except Exception as e:
                db.log(p["id"], None, "video_ia_falhou", str(e))
                avisos.append(f"⚠️ Vídeo por IA falhou ({str(e)[:150]}); segui com a foto.")
        # --- narração (foto): roteiro -> voz -> áudio final; a foto vira vídeo vertical ---
        if ped["narrar"]:
            if tipo == "video":
                avisos.append("ℹ️ Narração por cima de vídeo ainda não é suportada; vale só para foto.")
            elif not voz.tts_ok():
                avisos.append("ℹ️ Pediu narração, mas a voz não está configurada (Conexões → Voz).")
            elif not con or not con["modelo"]:
                avisos.append("⚠️ Nenhum LLM configurado: sem narração.")
            else:
                try:
                    roteiro = _roteiro_literal(texto) or await llm.roteiro_narracao(con, p["contexto_md"], descricao or texto)
                    fala = await voz.narrar(roteiro)
                    tmp.append(fala)
                    audio_fala, dur_fala = await midia.misturar_voz(fala, musica)
                    tmp.append(audio_fala)
                    if dur_fala > midia.MAX_STORY_S:
                        raise voz.VozError("a narração passa de 60 s; peça um texto mais curto")
                    texto_tela = ""
                    palavras = (await voz.transcrever(fala)) if voz.whisper_ok() else voz.estimar(roteiro, dur_fala - 1.0)
                    animado = True
                    formato = "story" if formato == "story" else "reel"
                    extras.append("narrado")
                except Exception as e:
                    audio_fala = None
                    db.log(p["id"], None, "narracao_falhou", str(e))
                    avisos.append(f"⚠️ Não consegui narrar: {str(e)[:150]}")
        # --- vídeo: corte de silêncio e transcrição (antes do ajuste de formato) ---
        fonte = fonte_ia or src
        if tipo == "video" and ped["cortar"]:
            try:
                fonte, removido = await midia.cortar_silencio(fonte)
                if removido:
                    tmp.append(fonte)
                    extras.append(f"silêncio cortado (−{removido:.1f} s)")
                else:
                    avisos.append("ℹ️ Não encontrei pausas longas para cortar.")
            except midia.MidiaError as e:
                fonte = fonte_ia or src
                avisos.append(f"⚠️ Não consegui cortar o silêncio: {str(e)[:150]}")
        if tipo == "video" and ped["legendar"]:
            if not voz.whisper_ok():
                avisos.append("ℹ️ Pediu legendas animadas, mas a transcrição não está configurada (Conexões → Transcrição).")
            else:
                try:
                    palavras = await voz.transcrever(fonte)
                    if not palavras:
                        avisos.append("ℹ️ Não ouvi fala no vídeo: sem legendas animadas.")
                except voz.VozError as e:
                    avisos.append(f"⚠️ Legendas animadas falharam: {str(e)[:150]}")
        if tipo == "foto" and ped["legendar"] and not audio_fala:
            avisos.append("ℹ️ Legendas animadas precisam de fala: use em vídeo com voz ou junto com “narração”.")
        # --- texto na tela (Story) e menções ---
        if formato == "story" and ped["texto"] and not audio_fala and not texto_tela:
            if not con or not con["modelo"]:
                avisos.append("⚠️ Nenhum LLM configurado: Story sem texto na tela.")
            else:
                try:
                    texto_tela = await llm.texto_story(con, p["contexto_md"], descricao or texto)
                except Exception as e:
                    db.log(p["id"], None, "texto_story_falhou", str(e))
                    avisos.append(f"⚠️ Não consegui escrever o texto da tela: {str(e)[:120]}")
        if (formato == "story" or (auto and tipo == "foto")) and (texto_tela or mencoes):
            overlay = await render.overlay_story(texto_tela, "", p, mencoes, altura=1350 if formato == "feed" else 1920)
        # --- montagem ---
        if tipo == "video":
            arquivo = await midia.video(fonte, formato, musica, overlay)
        elif animado:
            arquivo = await midia.story_animado(src, audio_fala or musica, overlay, dur_fala if audio_fala else 7.0)
        else:
            arquivo = await midia.foto(src, formato)
            if overlay:
                arquivo = await midia.sobrepor(arquivo, overlay)
        if palavras and ped["legendar"] and arquivo.endswith(".mp4"):
            try:
                com_legenda = await midia.legendar(arquivo, palavras, marca_mod.carregar(p)["acento"])
                await _apagar_async(arquivo)
                arquivo = com_legenda
                extras.append("legendas animadas")
            except midia.MidiaError as e:
                avisos.append(f"⚠️ Não consegui gravar as legendas: {str(e)[:150]}")
    finally:
        for t in tmp + ([overlay] if overlay else []):
            Path(t).unlink(missing_ok=True)
    if formato == "story" and mencoes:
        avisos.append("ℹ️ Menção: vai escrita na imagem e também como menção real pela API (a pessoa é notificada). Não dá para criar adesivos de link/enquete pela API.")
    legenda = ""
    if formato != "story":
        if analise:
            legenda = analise["legenda_instagram"]
        elif not descricao:
            avisos.append("ℹ️ Sem frase de contexto: legenda em branco. Edite no painel ou mande de novo com uma frase.")
        elif not con or not con["modelo"]:
            avisos.append("⚠️ Nenhum LLM configurado: legenda em branco.")
        else:
            legenda = await llm.legenda_midia(con, p["contexto_md"], descricao, "vídeo" if arquivo.endswith(".mp4") else "foto")
        falta = [m for m in mencoes if legenda and m.lower() not in legenda.lower()]
        if falta:
            legenda += "\n\n" + " ".join(falta)
    pid = db.x("INSERT INTO posts(perfil_id,estado,noticia_titulo,fonte,texto,reacao,legenda,arquivo,formato,mencoes,criado_em,atualizado_em)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (p["id"], "aguardando_aprovacao", (descricao or "Mídia do Telegram")[:120], "Telegram", descricao, texto_tela, legenda,
                arquivo, formato, ",".join(mencoes), db.now(), db.now()))
    sugestao = _sugerir_horario(p, pid) if auto else ""
    db.log(p["id"], pid, "midia_recebida", f"{tipo} -> {formato}" + (" animado" if animado else "") +
           (f" musica={musica.name}" if musica else "") + (" texto" if texto_tela else "") + (" " + ",".join(extras) if extras else ""))
    if p["telegram_chat_id"]:
        if auto and formato == "feed":
            avisos.append("ℹ️ Feed de foto não leva música (o Instagram só aceita trilha em vídeo). Use “reel” para ter trilha.")
        resumo = formato.upper() + (" · animado" if animado and "narrado" not in extras else "") + (f" · trilha: {musica.stem}" if musica else "") + \
            (f" · texto na tela: “{texto_tela}”" if texto_tela else "") + "".join(f" · {x}" for x in extras) + \
            (f" · horário sugerido: {local(sugestao)}" if sugestao else "")
        mid = await telegram.enviar_card(p["telegram_chat_id"], C.CARDS / arquivo, pid,
                                         (legenda or "(sem legenda)") + f"\n\n[{resumo}]", "\n".join(avisos))
        db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, pid))
        if auto:
            _resumo_do_lote(p)
    return pid


# ---------------- esteira: horário sugerido e resumo do lote ----------------
def _sugerir_horario(p: dict, post_id: int) -> str:
    """Reserva o próximo horário livre do perfil como SUGESTÃO do post (o post continua aguardando aprovação)."""
    slots = proximos_horarios(p, 1)
    quando = _utc(slots[0], settings.tz()) if slots else None
    if quando:
        db.x("UPDATE posts SET agendado_para=? WHERE id=? AND estado='aguardando_aprovacao'", (quando, post_id))
    return quando or ""


def _agendar_sugerido(po: dict, p: dict) -> str:
    """Confirma o horário sugerido (ou o próximo livre, se o sugerido já passou). Devolve 'dd/mm HH:MM' ou ''."""
    if po["estado"] not in ESTADOS_ABERTOS or not po["arquivo"]:
        return ""
    quando = po["agendado_para"]
    if not quando or quando <= db.now():
        slots = proximos_horarios(p, 1)
        quando = _utc(slots[0], settings.tz()) if slots else None
    if not quando:
        return ""
    db.x("UPDATE posts SET estado='agendado', agendado_para=?, atualizado_em=? WHERE id=?", (quando, db.now(), po["id"]))
    db.log(p["id"], po["id"], "agendado", f"telegram {local(quando)}")
    return local(quando)


LOTE_ESPERA_S = 20
_LOTE_N: dict[str, int] = {}
_LOTE_TASK: dict[str, asyncio.Task] = {}
_MIDIA_SEM = asyncio.Semaphore(2)  # fotos em lote: duas por vez, para não afogar o LLM/ffmpeg


def _resumo_do_lote(p: dict) -> None:
    """Quando chegam várias fotos seguidas, depois de ~20 s sem novas manda UMA mensagem com o botão 'agendar todos'."""
    chat = str(p["telegram_chat_id"])
    _LOTE_N[chat] = _LOTE_N.get(chat, 0) + 1
    antiga = _LOTE_TASK.get(chat)
    if antiga and not antiga.done():
        antiga.cancel()
    _LOTE_TASK[chat] = asyncio.create_task(_enviar_resumo(p, chat))


async def _enviar_resumo(p: dict, chat: str) -> None:
    try:
        await asyncio.sleep(LOTE_ESPERA_S)
    except asyncio.CancelledError:
        return
    n = _LOTE_N.pop(chat, 0)
    if n < 2:
        return
    prontos = db.q("SELECT id, agendado_para FROM posts WHERE perfil_id=? AND estado='aguardando_aprovacao' AND fonte='Telegram' ORDER BY id", (p["id"],))
    if len(prontos) < 2:
        return
    horas = "\n".join(f"• #{r['id']} → {local(r['agendado_para'])}" for r in prontos if r["agendado_para"])
    await telegram.enviar_botoes(chat, f"📦 {len(prontos)} posts prontos nos cards acima. Horários sugeridos:\n{horas}\n\nSe estiver tudo certo, é só um toque:",
                                 [[(f"🕒 Agendar os {len(prontos)} nos horários sugeridos", "at:0")]])


LIMITE_VIDEO_LONGO_S = 30


async def criar_video_longo(p: dict, src, texto: str) -> list[int]:
    """Vídeo com mais de 30 s: gera DOIS posts prontos, um Reel (completo, até 90 s) e um Story (até 60 s), os dois com legendas animadas
    (se houver Transcrição), mais a thumb do Reel com um título que faz sentido com o vídeo, e a legenda do Instagram escrita a partir da fala."""
    ped = _pedidos(texto)
    _, descricao, sem_musica = _destino("video", texto)
    con = conexao_do_modulo("roteiro", p)
    avisos: list[str] = []
    info = await midia.sondar(src)
    dur = info["duracao"]
    palavras: list[dict] = []
    if not info["audio"]:
        avisos.append("ℹ️ O vídeo não tem áudio: sem legendas animadas.")
    elif not voz.whisper_ok():
        avisos.append("ℹ️ Transcrição desligada: sem legendas animadas e a legenda sai só pelo quadro do vídeo.")
    else:
        try:
            if voz.usa_local() and not voz.modelo_baixado() and p["telegram_chat_id"]:
                await telegram.avisar(str(p["telegram_chat_id"]), "Primeira transcrição: baixando o modelo de voz (~460 MB). Só nesta vez; pode demorar alguns minutos.")
            palavras = await voz.transcrever(src)
            if not palavras:
                avisos.append("ℹ️ Não ouvi fala no vídeo: sem legendas animadas.")
        except voz.VozError as e:
            avisos.append(f"⚠️ Transcrição falhou ({str(e)[:200]}): sem legendas animadas.")
    transcr = " ".join(w["w"] for w in palavras)[:2500]
    # --- legenda do post e título da thumb, a partir de um quadro + fala ---
    quadro = await midia.quadro(src, min(dur * 0.3, max(dur - 1, 0)))
    analise = None
    capa, musica = "", None
    try:
        if not con or not con["modelo"]:
            avisos.append("⚠️ Nenhum LLM configurado: sem legenda nem título na thumb (menu LLM do painel).")
        else:
            try:
                dica = "; ".join(x for x in (descricao, f"transcrição da fala: {transcr}" if transcr else "") if x)
                analise = await llm.analisar_foto(con, p["contexto_md"], await midia.miniatura_b64(quadro), dica, capa=True)
            except Exception as e:
                db.log(p["id"], None, "analise_video_falhou", str(e))
                avisos.append(f"⚠️ Não consegui analisar o vídeo: {str(e)[:200]}")
        if not sem_musica and (p["musica_modo"] == "aleatoria" or ped["musica"]):
            musica = midia.escolher_musica()
        acento = marca_mod.carregar(p)["acento"]
        feitos: dict[str, str] = {}
        for fmt in ("reel", "story"):
            if fmt == "story" and dur <= midia.MAX_STORY_S:  # igual ao Reel: só copia (poupa a renderização)
                nome = f"{uuid_hex()}.mp4"
                shutil.copyfile(C.CARDS / feitos["reel"], C.CARDS / nome)
                feitos["story"] = nome
                continue
            arq = await midia.video(src, fmt, musica, None)
            if palavras:
                try:
                    com = await midia.legendar(arq, palavras, acento)
                    await _apagar_async(arq)
                    arq = com
                except midia.MidiaError as e:
                    avisos.append(f"⚠️ Legendas animadas falharam no {fmt}: {str(e)[:120]}")
            feitos[fmt] = arq
        # --- thumb 9:16 do Reel: o quadro com o título ---
        titulo = (analise or {}).get("texto_tela", "")
        base = await midia.foto(quadro, "story")
        if titulo:
            ov = await render.overlay_story(titulo, "", p, None)
            try:
                capa = await midia.sobrepor(base, ov)
            finally:
                Path(ov).unlink(missing_ok=True)
        else:
            capa = base
    finally:
        quadro.unlink(missing_ok=True)
    legenda = (analise or {}).get("legenda_instagram", "")
    resumo_tema = descricao or (analise or {}).get("descricao", "") or "Vídeo do Telegram"
    ids: list[int] = []
    for fmt in ("reel", "story"):
        pid = db.x("INSERT INTO posts(perfil_id,estado,noticia_titulo,fonte,texto,reacao,legenda,arquivo,formato,capa,criado_em,atualizado_em)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (p["id"], "aguardando_aprovacao", resumo_tema[:120], "Telegram", resumo_tema, titulo, legenda if fmt == "reel" else "",
                    feitos[fmt], fmt, capa if fmt == "reel" else "", db.now(), db.now()))
        _sugerir_horario(p, pid)
        db.log(p["id"], pid, "video_longo", f"{fmt} {dur:.0f}s" + (" legendado" if palavras else "") + (" thumb" if capa else ""))
        ids.append(pid)
    if p["telegram_chat_id"]:
        chat = str(p["telegram_chat_id"])
        if capa:
            await telegram.enviar_foto(chat, C.CARDS / capa, f"🖼 Thumb do Reel #{ids[0]}" + (f": “{titulo}”" if titulo else ""))
        extra = " · legendas animadas" if palavras else ""
        for pid, fmt in zip(ids, ("reel", "story")):
            aviso = "\n".join(avisos) + (f"\nℹ️ Story de {min(dur, midia.MAX_STORY_S):.0f} s (máx. 60 s)." if fmt == "story" and dur > midia.MAX_STORY_S else "")
            if fmt == "reel" and dur > midia.MAX_REEL_S:
                aviso += f"\nℹ️ O vídeo tem {dur:.0f} s: o Reel foi cortado em {midia.MAX_REEL_S} s."
            mid = await telegram.enviar_card(chat, C.CARDS / feitos[fmt], pid,
                                             (legenda if fmt == "reel" else "(Story sem legenda)") + f"\n\n[{fmt.upper()}{extra}" + (" · com thumb" if fmt == "reel" and capa else "") + "]",
                                             aviso.strip())
            db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, pid))
            _resumo_do_lote(p)
    return ids


async def mensagem_telegram(msg: dict) -> None:
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    nome = chat.get("first_name", "") + (" " + chat.get("last_name", "") if chat.get("last_name") else "")
    username = chat.get("username", "")
    if chat_id:
        telegram.registrar_chat_recente(chat_id, nome, username)

    p = db.one("SELECT * FROM perfis WHERE telegram_chat_id=? AND telegram_chat_id!='' ORDER BY ativo DESC, id LIMIT 1", (chat_id,))
    if not p:
        # Só responde com o Chat ID durante o onboarding (quando nenhum perfil tem Chat ID vinculado ainda)
        algum_vinculado = db.one("SELECT 1 FROM perfis WHERE telegram_chat_id!='' LIMIT 1")
        if not algum_vinculado:
            nome_exibir = (nome or username or "Criador").strip()
            saudacao = (
                f"👋 Olá, {nome_exibir}!\n\n"
                f"Recebi seu contato no bot do ic-ap.\n"
                f"✅ *Seu Chat ID é:* `{chat_id}`\n\n"
                f"👉 No painel de configuração, clique no botão *⚡ Detectar Meu Usuário Automaticamente* "
                f"(ou cole o Chat ID `{chat_id}` no campo correspondente) para concluir sua conexão!"
            )
            try:
                await telegram.avisar(chat_id, saudacao)
            except Exception:
                pass
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
        await _texto_telegram(p, chat_id, texto.strip())
        return
    tipo, arq, ext = m
    eh_logo = tipo == "foto" and bool(re.search(r"(?i)\blogo(tipo)?\b", texto))
    eh_meme = tipo == "foto" and not eh_logo and bool(re.match(r"(?i)\s*meme\b", texto))
    if (arq.get("file_size") or 0) > telegram.MAX_DOWNLOAD:
        await telegram.avisar(chat_id, "O Telegram só deixa o bot baixar arquivos de até 20 MB. Mande uma versão menor.")
        return
    tmp = C.DATA / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / f"{uuid_hex()}{ext}"
    try:
        await telegram.avisar(chat_id, "Recebi. Preparando…")
        await telegram.baixar(arq["file_id"], src)
        if eh_logo:
            marca_mod.salvar_logo(p["id"], src.read_bytes())
            aviso = "" if msg.get("document") else " Dica: mande o logo como ARQUIVO (sem comprimir) para manter o fundo transparente."
            await telegram.avisar(chat_id, f"✅ Logotipo salvo. Ele aparece nos próximos cards.{aviso}")
        elif eh_meme:
            await criar_meme_foto(p, src, texto)
        else:
            async with _MIDIA_SEM:
                longo = (tipo == "video" and p["esteira"] != "off" and not re.search(r"(?i)\b(story|stories|reels?|feed)\b", texto)
                         and (await midia.sondar(src))["duracao"] > LIMITE_VIDEO_LONGO_S)
                if longo:
                    await telegram.avisar(chat_id, "Vídeo com mais de 30 s: gerando Reel + Story + thumb + legenda…")
                    await criar_video_longo(p, src, texto)
                else:
                    await criar_de_midia(p, tipo, src, texto)
    except Exception as e:
        db.log(p["id"], None, "midia_falhou", str(e))
        await telegram.avisar(chat_id, f"Não consegui preparar a mídia: {str(e)[:200]}")
    finally:
        src.unlink(missing_ok=True)


def uuid_hex() -> str:
    import uuid
    return uuid.uuid4().hex



# ---------------- ideia (texto) -> post / carrossel ----------------
async def _processar_texto(post_id: int, p: dict, temperature: float, destino: str = "aguardando_aprovacao",
                           n_slides: int | None = None, aviso: str = "") -> bool:
    po = post(post_id)
    formato = po["formato"]
    novos: list[str] = []
    try:
        con = conexao_do_modulo("roteiro" if formato in ("carrossel", "reels") else "legenda", p)
        if not con or not con["modelo"]:
            raise ValueError("nenhuma conexão de LLM com modelo escolhido: configure em LLM")
        ideia, estrategia = po["texto"], po["angulo"] or None
        n = n_slides or len(arquivos_do_post(po)) or 6
        feedback, res = None, None
        for _ in range(3):
            await _apagar_async(*novos)
            novos = []
            try:
                if formato == "carrossel":
                    res = await llm.carrossel_de_texto(con, p["contexto_md"], ideia, n, temperature, estrategia, feedback)
                    total, longo = len(res["slides"]), None
                    for i, sl in enumerate(res["slides"], 1):
                        tipo = "capa" if i == 1 else ("cta" if i == total else "conteudo")
                        nome, estourou = await render.slide(sl["titulo"], sl["texto"], i, total, p["handle"], p["nome"], tipo, p)
                        novos.append(nome)
                        if estourou and longo is None:
                            longo = i
                    if longo:
                        feedback = f"o slide {longo} não coube na imagem, encurte titulo e texto de todos os slides"
                        continue
                else:
                    res = await llm.post_de_texto(con, p["contexto_md"], ideia, temperature, estrategia, feedback)
                    nome, estourou = await render.card(res["manchete_curta"], res["texto_card"], "", p["handle"], p["nome"], formato, None, p)
                    novos = [nome]
                    if estourou:
                        feedback = "texto_card não coube no card, encurte"
                        continue
            except ValueError as e:
                feedback = str(e)
                continue
            break
        else:
            res = None  # as 3 tentativas falharam
        if not res or not novos:
            raise ValueError(f"o modelo não entregou uma saída válida em 3 tentativas ({feedback})")
        if formato == "carrossel":
            manchete, reacao = res["slides"][0]["titulo"], "\n\n".join(f"{x['titulo']}: {x['texto']}".strip(": ") for x in res["slides"][1:])
        else:
            manchete, reacao = res["manchete_curta"], res["texto_card"]
        _set(post_id, destino, json_llm=json.dumps(res, ensure_ascii=False), manchete=manchete, reacao=reacao,
             legenda=res["legenda"], arquivo=novos[0], arquivos=json.dumps(novos) if formato == "carrossel" else "", erro=None)
        db.log(p["id"], post_id, "gerado_texto", f"{formato} v{po['variacao']}")
        if destino == "aguardando_aprovacao" and telegram.ativo() and p["telegram_chat_id"]:
            try:
                caminhos = [C.CARDS / a for a in novos]
                if formato == "carrossel":
                    mid = await telegram.enviar_carrossel(p["telegram_chat_id"], caminhos, post_id, res["legenda"], aviso)
                else:
                    mid = await telegram.enviar_card(p["telegram_chat_id"], caminhos[0], post_id, res["legenda"], aviso)
                db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, post_id))
            except Exception as e:
                db.log(p["id"], post_id, "telegram_falhou", str(e))
        return True
    except Exception as e:
        await _apagar_async(*novos)
        msg = (str(e) or type(e).__name__)[:400]
        _set(post_id, "falhou", erro=msg)
        db.log(p["id"], post_id, "falhou", msg)
        if destino == "aguardando_aprovacao" and telegram.ativo() and p["telegram_chat_id"]:
            await telegram.avisar(p["telegram_chat_id"], f"Falha ao gerar post #{post_id}: {msg[:200]}")
        return False


async def criar_de_texto(perfil_id: int, ideia: str, formato: str = "feed", n_slides: int = 6, variacoes: int = 1,
                         destino: str = "aguardando_aprovacao") -> list[int]:
    """Cria o post (ou as variações de teste A/B, com manchete e chamada diferentes) a partir de uma ideia. Devolve os ids que deram certo."""
    p = perfil(perfil_id)
    ideia = (ideia or "").strip()
    if not p or len(ideia) < 8:
        return []
    formato = formato if formato in ("feed", "story", "carrossel") else "feed"
    variacoes = max(1, min(int(variacoes), len(llm.ESTRATEGIAS_AB)))
    ids: list[int] = []
    grupo = None
    async with _GERACAO:
        for v in range(1, variacoes + 1):
            est = llm.ESTRATEGIAS_AB[v - 1] if variacoes > 1 else ""
            pid = db.x("INSERT INTO posts(perfil_id,estado,noticia_titulo,fonte,texto,variacao,grupo,formato,angulo,criado_em,atualizado_em)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (perfil_id, "capturado", ideia[:120], FONTE_TEXTO, ideia, v, grupo, formato, est, db.now(), db.now()))
            if grupo is None:
                grupo = pid
                db.x("UPDATE posts SET grupo=? WHERE id=?", (pid, pid))
            aviso = f"🅰️ Versão {v} de {variacoes}: {est}" if est else ""
            if await _processar_texto(pid, p, 0.8, destino, n_slides, aviso):
                ids.append(pid)
    return ids


async def _refazer_texto(po: dict) -> bool:
    if not _claim(po["id"], ESTADOS_ABERTOS, "extraido"):
        return False
    p = perfil(po["perfil_id"])
    destino = "rascunho" if po["estado"] in ("rascunho", "agendado") else "aguardando_aprovacao"
    ok = await _processar_texto(po["id"], p, 0.95, destino)
    if ok:
        await asyncio.to_thread(_apagar_post, po)
        db.log(p["id"], po["id"], "refeito")
        if po["tg_message_id"] and p["telegram_chat_id"]:
            await telegram.marcar(p["telegram_chat_id"], po["tg_message_id"], "Refeito. Nova versão abaixo.")
    return ok


async def novas_hashtags(post_id: int) -> bool:
    """Troca as hashtags da legenda por um conjunto novo (nicho + médias + amplas)."""
    po = post(post_id)
    if not po or po["estado"] not in ESTADOS_ABERTOS:
        return False
    p = perfil(po["perfil_id"])
    con = conexao_do_modulo("legenda", p)
    base = re.sub(r"(?:\s*#\w+)+\s*$", "", po["legenda"] or "").rstrip()
    try:
        tags = await llm.hashtags_para(con, p["contexto_md"], po["reacao"] or po["texto"] or base or po["manchete"] or "")
    except Exception as e:
        db.log(p["id"], post_id, "falhou_hashtags", str(e))
        return False
    db.x("UPDATE posts SET legenda=?, atualizado_em=? WHERE id=?", ((base + "\n\n" + " ".join(tags)).strip(), db.now(), post_id))
    db.log(p["id"], post_id, "hashtags_novas")
    return True


# ---------------- conversa de brainstorming pelo Telegram ----------------
HIST_MAX = 24


def _historico(chat_id: str) -> list[dict]:
    rows = db.q("SELECT papel, texto FROM conversas WHERE chat_id=? ORDER BY id DESC LIMIT ?", (chat_id, HIST_MAX))
    return [{"role": r["papel"], "content": r["texto"]} for r in reversed(rows)]


def _guardar(chat_id: str, papel: str, texto: str) -> None:
    db.x("INSERT INTO conversas(chat_id,papel,texto,criado_em) VALUES(?,?,?,?)", (chat_id, papel, texto[:4000], db.now()))
    db.x("DELETE FROM conversas WHERE chat_id=? AND id NOT IN (SELECT id FROM conversas WHERE chat_id=? ORDER BY id DESC LIMIT 200)",
         (chat_id, chat_id))


ATALHOS = {"/start": "Oi! Acabei de abrir o bot.",
           "/perfil": "Quero montar ou revisar o meu perfil. Me entreviste.",
           "/ideias": "Me dê ideias de posts para hoje, com base no meu perfil."}


async def aplicar_skills_no_post(p: dict, chat_id: str, instrucao: str = "", post_id: int | None = None) -> bool:
    """Aplica as skills do VectorCraft (selo/badge vetorial de alta conversão) e copy diretamente
    no story ou post pendente, atualizando o card visualmente e reenviando para aprovação no Telegram."""
    import base64

    # 1. Localizar o post alvo
    po = None
    if post_id:
        po = post(post_id)
    if not po:
        mencionou_story = bool(re.search(r"(?i)\bstor(y|ies)\b", instrucao))
        if mencionou_story:
            po = db.one("SELECT * FROM posts WHERE perfil_id=? AND formato='story' AND estado='aguardando_aprovacao' ORDER BY id DESC LIMIT 1", (p["id"],))
            if not po:
                po = db.one("SELECT * FROM posts WHERE perfil_id=? AND formato='story' ORDER BY id DESC LIMIT 1", (p["id"],))
        if not po:
            po = db.one("SELECT * FROM posts WHERE perfil_id=? AND estado='aguardando_aprovacao' ORDER BY id DESC LIMIT 1", (p["id"],))
        if not po:
            po = db.one("SELECT * FROM posts WHERE perfil_id=? ORDER BY id DESC LIMIT 1", (p["id"],))

    if not po:
        await telegram.avisar(chat_id, "Não encontrei nenhum post ou story recente para editar com as skills. Crie um post primeiro ou envie uma foto/ideia!")
        return False

    pid = po["id"]
    formato = po["formato"] or "story"
    manchete = po["manchete"] or po["noticia_titulo"] or po["texto"] or "Destaque"
    reacao = po["reacao"] or po["texto"] or ""
    fonte = po["fonte"] if po["fonte"] != "Texto" else ""

    await telegram.digitando(chat_id)
    await telegram.avisar(chat_id, f"🛠️ *Aplicando Skills no {formato.upper()} #{pid}*\n• Desenhando selo vetorial VectorCraft com tipografia de alta retenção...\n• Renderizando card em alta definição...")

    # 2. Escolha e calibração do selo
    conteudo_full = f"{instrucao} {manchete} {reacao}".lower()
    if any(k in conteudo_full for k in ("alerta", "risco", "perigo", "lgpd", "jurídico", "juridico", "vazar", "urgente", "vazamento", "processo")):
        estilo_badge = "alerta_vermelho"
        if "lgpd" in conteudo_full:
            badge_texto = "ALERTA LGPD"
        elif "jurídico" in conteudo_full or "juridico" in conteudo_full or "processo" in conteudo_full:
            badge_texto = "RISCO JURÍDICO"
        elif "vaz" in conteudo_full:
            badge_texto = "DADOS VAZADOS"
        else:
            badge_texto = "ALERTA CRÍTICO"
        subtexto_badge = "RISCO REAL"
    elif any(k in conteudo_full for k in ("ouro", "gold", "vip", "exclusivo", "premium", "faturamento", "dinheiro", "lucro", "empresa")):
        estilo_badge = "neon_ouro"
        badge_texto = "CONTEÚDO VIP"
        subtexto_badge = "EXCLUSIVO"
    elif any(k in conteudo_full for k in ("limpo", "clean", "minimalista", "pill")):
        estilo_badge = "pill_clean"
        badge_texto = "DESTAQUE"
        subtexto_badge = "ESSENCIAL"
    else:
        estilo_badge = "neon_ciano"
        if any(k in conteudo_full for k in ("ia local", "local", "privada", "privacidade")):
            badge_texto = "IA PRIVADA"
            subtexto_badge = "100% LOCAL"
        elif "chatgpt" in conteudo_full:
            badge_texto = "ALERTA CHATGPT"
            subtexto_badge = "SEGURANÇA"
        else:
            badge_texto = "DESTAQUE 2026"
            subtexto_badge = "ALTA RETENÇÃO"

    # Se instrução tiver estilo explícito
    for e in ("neon_ciano", "neon_ouro", "alerta_vermelho", "pill_clean"):
        if e in instrucao.lower():
            estilo_badge = e
            break

    # Se instrução tiver texto explícito após "badge" ou entre aspas
    m_badge = re.search(r"badge\s*[:\s]\s*[\"']?([^\"'\n,]+)[\"']?", instrucao, re.IGNORECASE)
    if m_badge:
        badge_texto = m_badge.group(1).strip().upper()[:24]

    # 3. Gerar SVG VectorCraft e converter para Data URI
    larg_badge = 620 if formato == "story" else 540
    alt_badge = 140
    svg_badge = vectorcraft.criar_badge_vetorial(
        texto=badge_texto,
        estilo=estilo_badge,
        subtexto=subtexto_badge,
        largura=larg_badge,
        altura=alt_badge,
    )
    b64_svg = base64.b64encode(svg_badge.encode("utf-8")).decode("ascii")
    selo_uri = f"data:image/svg+xml;base64,{b64_svg}"

    # 4. Renderizar o novo card com o selo e estilo de design correspondente
    mapa_card_estilo = {
        "alerta_vermelho": "alerta_critico",
        "neon_ciano": "cyber_glass",
        "neon_ouro": "editorial_bold",
        "pill_clean": "clean_minimalist",
    }
    card_estilo = mapa_card_estilo.get(estilo_badge, "editorial_bold")

    try:
        novo_arquivo, estourou = await render.card(
            manchete=manchete,
            reacao=reacao,
            fonte=fonte,
            handle=p["handle"],
            nome=p["nome"],
            formato=formato,
            print_uri=None,
            p=p,
            selo_uri=selo_uri,
            estilo=card_estilo,
        )
    except Exception as e:
        await telegram.avisar(chat_id, f"Não foi possível renderizar o card com o selo: {str(e)[:200]}")
        return False

    # 5. Atualizar registro no banco
    db.x("UPDATE posts SET arquivo=?, angulo=?, estado='aguardando_aprovacao', atualizado_em=? WHERE id=?",
         (novo_arquivo, card_estilo, db.now(), pid))
    db.log(p["id"], pid, "skills_aplicadas", f"badge:{estilo_badge}:{badge_texto}:{card_estilo}")

    # 6. Enviar card atualizado para o Telegram com botões interativos
    legenda = "" if formato == "story" else (po["legenda"] or "")
    aviso = f"✨ *{formato.upper()} #{pid} Editado com Skills VectorCraft!*\n• Tema: `{card_estilo.upper()}`\n• Selo: `{badge_texto}` ({estilo_badge})\n• Use o botão '🎨 Mudar Estilo' para alternar o layout!"
    try:
        mid = await telegram.enviar_card(chat_id, C.CARDS / novo_arquivo, pid, legenda or "(Story com Selo Vetorial)", aviso)
        db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, pid))
    except Exception as e:
        db.log(p["id"], pid, "telegram_falhou", str(e))
        await telegram.avisar(chat_id, f"Card gerado com sucesso ({novo_arquivo}), mas falhou ao enviar botões: {str(e)[:200]}")
    return True


async def _criar_e_enviar_post_agente(p: dict, chat_id: str, res: dict) -> bool:
    """Transforma a saída estruturada dos agentes em posts no banco e cards com botões interativos no Telegram."""
    acao = res.get("acao", "")
    dados = res.get("dados") or {}
    if not isinstance(dados, dict):
        return False

    # 1. CARROSSEL
    if acao == "carrossel" and dados.get("slides"):
        titulo = dados.get("titulo_carrossel", "Carrossel Estratégico")
        slides = dados["slides"]
        total = len(slides)
        novos = []
        for i, sl in enumerate(slides, 1):
            tipo = "capa" if i == 1 else ("cta" if i == total else "conteudo")
            try:
                nome, estourou = await render.slide(sl["titulo"], sl.get("texto", ""), i, total, p["handle"], p["nome"], tipo, p)
            except Exception:
                svg_sl = vectorcraft.criar_slide_vetorial_carrossel(sl["titulo"], sl.get("texto", ""), i, total)
                nome = f"slide_{p['id']}_{i}_{int(time.time()*1000)}.png"
                await vectorcraft.renderizar_svg_para_png(svg_sl, C.CARDS / nome)
            novos.append(nome)

        legenda = dados.get("legenda_instagram", "")
        pid = db.x(
            "INSERT INTO posts(perfil_id, estado, noticia_titulo, fonte, texto, json_llm, manchete, reacao, legenda, arquivo, arquivos, formato, criado_em, atualizado_em) "
            "VALUES(?, 'aguardando_aprovacao', ?, 'Telegram', ?, ?, ?, ?, ?, ?, ?, 'carrossel', ?, ?)",
            (
                p["id"],
                titulo[:120],
                titulo,
                json.dumps(dados, ensure_ascii=False),
                titulo,
                "\n\n".join(f"{s['titulo']}: {s.get('texto','')}" for s in slides[1:]),
                legenda,
                novos[0] if novos else "",
                json.dumps(novos),
                db.now(),
                db.now(),
            )
        )
        caminhos = [C.CARDS / f for f in novos]
        aviso = f"📑 *Carrossel #{pid} Gerado pelo Time de Especialistas!*\n• Total: {len(novos)} slides\n• Toque abaixo para postar ou agendar:"
        mid = await telegram.enviar_carrossel(chat_id, caminhos, pid, legenda, aviso)
        db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, pid))
        db.log(p["id"], pid, "gerado_agente", f"carrossel:{len(novos)}_slides")
        return True

    # 2. REELS (Gera Vídeo .MP4 1080x1920 com Motion, Fundo Contextual, Overlay e Trilha Sonora)
    elif acao in ("reels", "reel"):
        cap = dados.get("caption") or {}
        hook = cap.get("hook_125") or dados.get("manchete") or "Reels em Destaque"
        cenas = cap.get("cenas_reels") or []
        legenda = dados.get("legenda_final") or cap.get("legenda_completa") or dados.get("legenda") or ""
        roteiro_txt = f"🎯 HOOK (0-3s): {hook}\n\n" + "\n".join(
            f"🎬 Cena {c.get('cena', i+1)}: {c.get('fala', '')} (Visual: _{c.get('busca_visual', '')}_)"
            for i, c in enumerate(cenas)
        )
        arq = dados.get("arquivo_png")
        nome_overlay = Path(arq).name if arq else f"overlay_{int(time.time()*1000)}.png"
        if not arq or not Path(arq).exists():
            overlay_res = orquestrador.vector_art.gerar_overlay_reels(titulo=hook[:55], subtitulo="ROTEIRO & CENAS")
            caminho_overlay = C.CARDS / nome_overlay
            await orquestrador.vector_art.salvar_e_renderizar(overlay_res["svg"], caminho_overlay.stem, largura=1080, altura=1920)
        else:
            caminho_overlay = Path(arq)
            if caminho_overlay.parent != C.CARDS:
                shutil.copy2(caminho_overlay, C.CARDS / nome_overlay)

        # Renderiza vídeo MP4 9:16 com fundo fotográfico contextualizado em movimento + overlay + trilha musical
        arquivo_final_reel = nome_overlay
        formato_db_reel = "reel"
        fundo_reel_tmp = C.DATA / "tmp" / f"reel_bg_{uuid_hex()}.jpg"
        ov_reel_tmp = None
        try:
            busca_v = (cenas[0].get("busca_visual") if cenas and isinstance(cenas[0], dict) else "") or hook
            await banco.baixar_uma(busca_v, fundo_reel_tmp, orientacao="portrait")
            ov_reel_tmp = await render.overlay_story(hook[:90], p["handle"], p, altura=1920)
            musica_r = midia.escolher_musica() or await midia.trilha_padrao()
            arquivo_final_reel = await midia.story_animado(
                fundo_reel_tmp if fundo_reel_tmp.exists() else (C.CARDS / nome_overlay),
                musica=musica_r,
                overlay=ov_reel_tmp,
                dur=8.5,
            )
        except Exception as e_vid:
            db.log(p["id"], None, "reel_video_fallback", str(e_vid)[:180])
            arquivo_final_reel = nome_overlay
        finally:
            fundo_reel_tmp.unlink(missing_ok=True)
            if ov_reel_tmp:
                Path(ov_reel_tmp).unlink(missing_ok=True)

        pid = db.x(
            "INSERT INTO posts(perfil_id, estado, noticia_titulo, fonte, texto, json_llm, manchete, reacao, legenda, arquivo, capa, formato, criado_em, atualizado_em) "
            "VALUES(?, 'aguardando_aprovacao', ?, 'Telegram', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                p["id"],
                hook[:120],
                hook,
                json.dumps(dados, ensure_ascii=False),
                hook,
                roteiro_txt,
                legenda,
                arquivo_final_reel,
                nome_overlay if arquivo_final_reel.endswith(".mp4") else "",
                formato_db_reel,
                db.now(),
                db.now(),
            )
        )
        aviso = f"🎬 *Reels #{pid} (Vídeo 9:16 + Trilha + Motion) Pronto!*\n• Gancho: _{hook}_\n• Roteiro cena a cena + Legenda"
        mid = await telegram.enviar_card(chat_id, C.CARDS / arquivo_final_reel, pid, f"{roteiro_txt}\n\n📝 Legenda:\n{legenda}", aviso)
        db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, pid))
        db.log(p["id"], pid, "gerado_agente", "reels")
        return True

    # 3. STORY ou FEED gerado pelo Estúdio Criativo (novo fluxo agêntico com 6 layouts e crítico visual)
    elif acao in ("story", "feed") and dados.get("arquivo_card"):
        nome_card = dados["arquivo_card"]
        layout = dados.get("layout", "editorial")
        manchete = dados.get("manchete") or dados.get("copy", {}).get("hook_125") or "Destaque"
        corpo = dados.get("corpo") or manchete
        legenda = dados.get("legenda") or dados.get("copy", {}).get("legenda_completa") or ""
        score = dados.get("avaliacao_critico", {}).get("score", 8)
        fmt_label = "Story (9:16)" if acao == "story" else "Post de Feed (4:5)"

        pid = db.x(
            "INSERT INTO posts(perfil_id, estado, noticia_titulo, fonte, texto, json_llm, manchete, reacao, legenda, arquivo, angulo, formato, criado_em, atualizado_em) "
            "VALUES(?, 'aguardando_aprovacao', ?, 'Telegram', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                p["id"],
                manchete[:120],
                manchete,
                json.dumps(dados, ensure_ascii=False),
                manchete,
                corpo,
                legenda,
                nome_card,
                layout,
                acao,
                db.now(),
                db.now(),
            ),
        )
        aviso = (
            f"🎨 *{fmt_label} #{pid} Criado pelo Estúdio Agêntico!*\n"
            f"• Layout: `{layout.upper()}` | Avaliação Visual: *{score}/10*\n"
            f"• Toque em '🎨 Mudar Estilo' para alternar o design ou '✅ Postar' para publicar:"
        )
        legenda_envio = legenda if acao != "story" else (legenda or "(Story 9:16)")
        mid = await telegram.enviar_card(chat_id, C.CARDS / nome_card, pid, legenda_envio, aviso)
        db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, pid))
        db.log(p["id"], pid, "gerado_agente", f"{acao}:{layout}")
        return True

    # 4. STORY (fallback legado se não vier do Estúdio)
    elif acao == "story":
        cap = dados.get("caption") or {}
        hook = cap.get("hook_125") or "Story em Destaque"
        legenda = dados.get("legenda_final") or cap.get("legenda_completa") or ""
        corpo = cap.get("corpo") or hook
        cta = cap.get("cta") or "Toque no link da bio para saber mais"
        prox_id = (db.valor("SELECT MAX(id) FROM posts") or 0) + 1
        try:
            nome_card, estourou = await render.card(
                hook, corpo, "Story", p["handle"], p["nome"],
                formato="story", p=p, pid=prox_id, cta_texto=cta, post_tipo_label="Story"
            )
        except Exception:
            badge_res = orquestrador.vector_art.gerar_badge(texto="DESTAQUE", estilo="neon_ciano")
            nome_card = f"story_{int(time.time()*1000)}.png"
            await orquestrador.vector_art.salvar_e_renderizar(badge_res["svg"], Path(nome_card).stem, largura=1080, altura=1920)

        pid = db.x(
            "INSERT INTO posts(perfil_id, estado, noticia_titulo, fonte, texto, json_llm, manchete, reacao, legenda, arquivo, formato, criado_em, atualizado_em) "
            "VALUES(?, 'aguardando_aprovacao', ?, 'Telegram', ?, ?, ?, ?, ?, ?, 'story', ?, ?)",
            (p["id"], hook[:120], hook, json.dumps(dados, ensure_ascii=False), hook, corpo, legenda, nome_card, db.now(), db.now())
        )
        aviso = f"📱 *Story #{pid} (9:16) Gerado pelo Time de Especialistas!*\n• Visual 9:16 com Safe Zones\n• Toque abaixo para postar ou agendar:"
        mid = await telegram.enviar_card(chat_id, C.CARDS / nome_card, pid, legenda or "(Story 9:16)", aviso)
        db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, pid))
        db.log(p["id"], pid, "gerado_agente", "story")
        return True

    # 5. FEED (fallback legado se não vier do Estúdio)
    elif acao == "feed":
        cap = dados.get("caption") or {}
        hook = cap.get("hook_125") or "Insight em Destaque"
        legenda = dados.get("legenda_final") or cap.get("legenda_completa") or ""
        corpo = cap.get("corpo") or hook
        cta = cap.get("cta") or "Toque no link da bio para saber mais"
        prox_id = (db.valor("SELECT MAX(id) FROM posts") or 0) + 1
        try:
            nome_card, estourou = await render.card(
                hook, corpo, "Feed", p["handle"], p["nome"],
                formato="feed", p=p, pid=prox_id, cta_texto=cta, post_tipo_label="Post de Feed"
            )
        except Exception:
            badge_res = orquestrador.vector_art.gerar_badge(texto="INSIGHT", estilo="neon_ouro")
            nome_card = f"feed_{int(time.time()*1000)}.png"
            await orquestrador.vector_art.salvar_e_renderizar(badge_res["svg"], Path(nome_card).stem, largura=1080, altura=1350)

        pid = db.x(
            "INSERT INTO posts(perfil_id, estado, noticia_titulo, fonte, texto, json_llm, manchete, reacao, legenda, arquivo, formato, criado_em, atualizado_em) "
            "VALUES(?, 'aguardando_aprovacao', ?, 'Telegram', ?, ?, ?, ?, ?, ?, 'feed', ?, ?)",
            (p["id"], hook[:120], hook, json.dumps(dados, ensure_ascii=False), hook, corpo, legenda, nome_card, db.now(), db.now())
        )
        aviso = f"📌 *Post de Feed #{pid} (4:5) Gerado pelo Time de Especialistas!*\n• Enquadramento 4:5\n• Copy com Gancho <125 chars e CTA único"
        mid = await telegram.enviar_card(chat_id, C.CARDS / nome_card, pid, legenda, aviso)
        db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, pid))
        db.log(p["id"], pid, "gerado_agente", "feed")
        return True

    return False


async def _texto_telegram(p: dict, chat_id: str, texto: str) -> None:
    cmd = texto.split()[0].lower().split("@")[0] if texto.startswith("/") else ""
    t_lower = texto.lower()

    if cmd in ("/ajuda", "/help") or not texto:
        await telegram.avisar(chat_id, AJUDA)
        return
    elif cmd in ("/skills", "/skill"):
        await telegram.avisar(chat_id, (
            "🛠️ *Skills e Especialistas VectorCraft Integrados:*\n\n"
            "• *Conversa Livre / Criação Direta:* Envie qualquer ideia, ex: `Faz um reels sobre automação com IA local` ou `Crie um carrossel de 6 slides sobre segurança em TI`.\n"
            "• *Reels (9:16):* `/reels <ideia>` (Roteiro cena a cena, gancho 3s, overlay de safe-zone).\n"
            "• *Story (9:16):* `/story <ideia>` (Card vertical, copy direto, selo de conversão).\n"
            "• *Carrossel (4:5):* `/carrossel <ideia>` (Sequência de slides com retenção e payoff).\n"
            "• *Feed (4:5):* `/feed <ideia>` (Card com manchete e copy no seu tom).\n"
            "• *Selos e Badges:* `/badge <texto> [estilo]` (neon_ciano, neon_ouro, alerta_vermelho, pill_clean).\n"
            "• *Overlay Vídeo:* `/overlay <titulo> | <subtitulo>` (Overlay 1080x1920 com safe-zones).\n"
            "• *Planejamento Semanal:* `/planejar` ou `/semana` (Cronograma estratégico).\n"
            "• *Auditar Texto:* `/auditar <texto>` (Score anti-IA e detecção de clichês).\n"
            "• *Humanizar Texto:* `/humanizar <texto>` (Limpeza de termos robóticos de IA).\n"
            "• *Desmontar Gancho:* `/hook <texto>` (Engenharia reversa de ganchos virais).\n"
            "• *Hashtags SEO:* `/hashtags <tema>` (Hashtags nichadas 2026)."
        ))
        return
    elif cmd == "/novo":
        db.x("DELETE FROM conversas WHERE chat_id=?", (chat_id,))
        await telegram.avisar(chat_id, "Conversa zerada. Pode começar de novo.")
        return
    elif cmd == "/canais":
        canais = distribuicao.canais_ativos(p["id"])
        if not canais:
            await telegram.avisar(chat_id, "📡 *Distribuição Multiplataforma Local*\n\nNenhum canal adicional ativo no momento.\nConfigure no painel web (menu Conexões) para publicar simultaneamente no Threads, YouTube Shorts, LinkedIn ou TikTok sem custos.")
        else:
            nomes = [distribuicao.CANAIS_SUPORTADOS.get(c["canal"], {}).get("nome", c["canal"]) for c in canais]
            await telegram.avisar(chat_id, "📡 *Canais Ativos para Postagem Simultânea:*\n\n• Instagram (Principal)\n" + "\n".join(f"• {n}" for n in nomes) + "\n\nAo aprovar qualquer post, ele será publicado automaticamente nestas redes.")
        return

    link_ig = meta_ai.extrair_link_instagram(texto)
    if link_ig or cmd == "/blowup":
        url_alvo = link_ig or texto.replace("/blowup", "").strip()
        if not url_alvo:
            await telegram.avisar(chat_id, "Envie o link do post ou Reel do Instagram (ou tema) que deseja transformar em post com a técnica Blow Up.")
            return
        await telegram.digitando(chat_id)
        try:
            async def _notificar_blow(msg_status: str):
                try:
                    await telegram.avisar(chat_id, msg_status)
                except Exception:
                    pass

            fmt_blow = "story" if re.search(r"\b(story|stories)\b", t_lower) else "feed"
            con_blow = conexao_do_perfil(p) or {}
            res_est = await orquestrador.estudio.criar_post(
                con=con_blow,
                perfil=p,
                pedido=f"Analise no Instagram com a Técnica Blow Up e recrie para meu perfil: {url_alvo} | {texto}",
                formato_forcado=fmt_blow,
                on_status=_notificar_blow,
            )
            res_orq = {
                "acao": res_est.get("formato", fmt_blow),
                "dados": res_est,
                "resposta_telegram": res_est.get("legenda", ""),
            }
            await _criar_e_enviar_post_agente(p, chat_id, res_orq)
            _guardar(chat_id, "user", texto)
            _guardar(chat_id, "assistant", res_est.get("legenda", "")[:4000])
        except Exception as e:
            await telegram.avisar(chat_id, f"Não foi possível concluir o Blow Up: {str(e)[:250]}")
        return

    # Gatilhos em linguagem natural para editar post/story existente com skills VectorCraft
    gatilhos_edicao = (
        "editar story", "editar o story", "edite o story", "melhorar o story", "melhore o story",
        "editar post", "editar o post", "edite o post", "melhorar o post", "melhore o post",
        "adicione badge", "colocar badge", "coloque badge", "coloca badge", "adicionar badge",
        "adicione selo", "colocar selo", "coloque selo", "coloca selo", "adicionar selo",
    )
    quer_edicao_skills = any(g in t_lower for g in gatilhos_edicao) or \
                         (any(s in t_lower for s in ("skill", "skills", "vectorcraft", "badge", "selo")) and
                          any(alvo in t_lower for alvo in ("story", "post", "card", "esse", "este", "último", "ultimo")))

    if quer_edicao_skills:
        _guardar(chat_id, "user", texto)
        ok = await aplicar_skills_no_post(p, chat_id, texto)
        if ok:
            _guardar(chat_id, "assistant", "Skills VectorCraft aplicadas com sucesso ao card.")
        return

    # Comandos diretos do time de especialistas e Estúdio Criativo
    comandos_orquestrador = (
        "/reels", "/reel", "/story", "/stories", "/feed", "/post", "/carrossel",
        "/badge", "/overlay", "/arte", "/vetor", "/planejar", "/semana",
        "/audiencia", "/auditar", "/humanizar", "/hook", "/hashtags",
    )
    meta_ai_ativo = bool(settings.segredo("meta_ai_cookies"))
    eh_pedido_orquestrador_natural = bool(
        (meta_ai_ativo and cmd not in ATALHOS) or
        re.search(r"\b(story|stories)\b", t_lower) or
        any(k in t_lower for k in ("notícia", "notícias", "noticia", "noticias", "últimas notícias", "ultimas noticias", "matéria", "materia"))
    )

    if cmd in comandos_orquestrador or eh_pedido_orquestrador_natural:
        cmd_mod = "roteiro" if any(k in t_lower for k in ("carrossel", "overlay", "arte", "vetor", "reels", "reel", "story", "stories")) else "legenda"
        con = conexao_do_modulo(cmd_mod, p)
        if not meta_ai_ativo and cmd not in ("/auditar", "/badge", "/overlay") and (not con or not con.get("modelo")):
            await telegram.avisar(chat_id, "Ainda não há um modelo de linguagem configurado. Configure no painel (menu LLM).")
            return
        await telegram.digitando(chat_id)
        try:
            async def _notificar_telegram(msg_status: str):
                try:
                    await telegram.avisar(chat_id, msg_status)
                except Exception:
                    pass

            res = await orquestrador.processar_mensagem(
                con or {}, p, chat_id, texto, _historico(chat_id), on_status=_notificar_telegram
            )

            post_criado = await _criar_e_enviar_post_agente(p, chat_id, res)
            if not post_criado:
                await telegram.avisar(chat_id, res["resposta_telegram"])
                dados = res.get("dados") or {}
                if isinstance(dados, dict):
                    arq = dados.get("arquivo_png") or dados.get("arquivo_svg")
                    if arq and Path(arq).exists():
                        try:
                            await telegram.enviar_foto(chat_id, arq, f"🎨 {res.get('acao', 'arte').upper()}")
                        except Exception:
                            pass

            _guardar(chat_id, "user", texto)
            _guardar(chat_id, "assistant", res["resposta_telegram"])
        except Exception as e:
            await telegram.avisar(chat_id, f"Não consegui processar: {str(e)[:200]}")
        return

    await _conversar(p, chat_id, ATALHOS.get(cmd, texto))


async def _conversar(p: dict, chat_id: str, texto: str) -> None:
    p = perfil(p["id"])  # perfil atualizado (o contexto pode ter mudado na conversa)
    con = conexao_do_modulo("chat", p)
    if not con or not con["modelo"]:
        await telegram.avisar(chat_id, "Ainda não há um modelo de linguagem configurado. Configure no painel (menu LLM).")
        return
    await telegram.digitando(chat_id)
    try:
        r = await llm.conversar(con, p, _historico(chat_id), texto)
    except Exception as e:
        db.log(p["id"], None, "conversa_falhou", str(e))
        await telegram.avisar(chat_id, f"Não consegui responder agora: {str(e)[:200]}")
        return
    _guardar(chat_id, "user", texto)
    _guardar(chat_id, "assistant", r["resposta"])
    await telegram.avisar(chat_id, r["resposta"])
    if r["acao"] == "propor_perfil":
        await _propor_perfil(p, chat_id, r)
    elif r["acao"] == "definir_marca":
        nova, avisos = marca_mod.definir(p["id"], **r["marca"])
        extra = ("\n" + "\n".join("⚠️ " + a for a in avisos)) if avisos else ""
        await telegram.avisar(chat_id, f"🎨 Marca: fundo {nova['fundo']}, texto {nova['texto']}, destaque {nova['acento']}, fonte {marca_mod.NOMES_FONTE[nova['fonte']]}.{extra}")
        db.log(p["id"], None, "marca_definida_telegram")
    elif r["acao"] == "gerar" and r["gerar"]["formato"] in ("citacao", "meme"):
        g = r["gerar"]
        if g["formato"] == "citacao":
            ids = await criar_citacao(p["id"], g["ideia"], g["fundo"] == "banco")
        else:
            ids = await criar_meme_banco(p["id"], g["ideia"])
        db.log(p["id"], None, "gerado_da_conversa", f"{g['formato']} -> {len(ids)}")
    elif r["acao"] == "gerar":
        g = r["gerar"]
        ids = await criar_de_texto(p["id"], g["ideia"], g["formato"], g["n_slides"], g["variacoes"], "aguardando_aprovacao")
        db.log(p["id"], None, "gerado_da_conversa", f"{g['formato']} x{g['variacoes']} -> {len(ids)}")


def _horarios_validos(txt: str) -> str:
    return ",".join(h.strip() for h in (txt or "").split(",") if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h.strip()))


async def _propor_perfil(p: dict, chat_id: str, r: dict) -> None:
    prop = {"perfil_md": r["perfil_md"], "palavras_chave": r["palavras_chave"], "horarios": _horarios_validos(r["horarios"])}
    db.set_setting(f"propostaperfil:{p['id']}", json.dumps(prop, ensure_ascii=False))
    previa = r["perfil_md"] if len(r["perfil_md"]) <= 3200 else r["perfil_md"][:3200] + "\n[…]"
    extra = (f"\n\nTemas para buscar notícias: {prop['palavras_chave']}" if prop["palavras_chave"] else "") + \
            (f"\nHorários: {prop['horarios']}" if prop["horarios"] else "")
    await telegram.enviar_botoes(chat_id, f"Proposta de perfil:\n\n{previa}{extra}",
                                 [[("✅ Salvar perfil", f"sp:{p['id']}"), ("✏️ Ajustar", f"np:{p['id']}")]])


async def _acao_perfil(acao: str, perfil_id: int, chat_id: str) -> None:
    p = perfil(perfil_id)
    if not p or str(p["telegram_chat_id"]) != chat_id:
        return  # só o dono do perfil mexe nele
    chave = f"propostaperfil:{perfil_id}"
    raw = db.get_setting(chave)
    if not raw:
        await telegram.avisar(chat_id, "Essa proposta já foi tratada ou expirou. Peça /perfil de novo.")
        return
    if acao == "np":
        db.x("DELETE FROM settings WHERE k=?", (chave,))
        _guardar(chat_id, "user", "Quero ajustar a proposta de perfil.")
        await telegram.avisar(chat_id, "Ok, não salvei. O que você quer mudar?")
        return
    prop = json.loads(raw)
    db.x("UPDATE perfis SET contexto_md=? WHERE id=?", (prop["perfil_md"], perfil_id))
    if prop.get("palavras_chave"):
        db.x("UPDATE perfis SET palavras_chave=? WHERE id=?", (prop["palavras_chave"], perfil_id))
    if prop.get("horarios"):
        db.x("UPDATE perfis SET horarios=? WHERE id=?", (prop["horarios"], perfil_id))
    db.x("DELETE FROM settings WHERE k=?", (chave,))
    db.log(perfil_id, None, "perfil_salvo_telegram")
    _guardar(chat_id, "user", "Salvei a proposta de perfil.")
    await telegram.avisar(chat_id, "✅ Perfil salvo. A partir de agora escrevo com ele. Quer ideias de posts? Mande /ideias.")


# ---------------- citação, meme e adaptação de formato ----------------
ESTILOS_CITACAO = ("escuro", "claro", "acento")


def _fundo_tmp() -> Path:
    t = C.DATA / "tmp"
    t.mkdir(parents=True, exist_ok=True)
    return t / f"{uuid_hex()}.jpg"


async def _processar_visual(post_id: int, p: dict, destino: str = "aguardando_aprovacao", aviso: str = "") -> bool:
    """Gera (ou refaz) um post de citação/meme a partir do tema guardado em po['texto']."""
    po = post(post_id)
    novo, tmp = None, None
    try:
        con = conexao_do_modulo("legenda", p)
        if not con or not con["modelo"]:
            raise ValueError("nenhuma conexão de LLM com modelo escolhido: configure em LLM")
        usa_banco = (po["angulo"] or "") == "banco"
        if usa_banco and po["fonte"] == FONTE_CITACAO and not banco.disponivel():
            usa_banco = False
            aviso = (aviso + "\n" if aviso else "") + "ℹ️ Sem chave de banco de imagens (Conexões): citação sem foto de fundo."
        credito = ""
        feedback, res = None, None
        for _ in range(3):
            await _apagar_async(novo)
            novo = None
            try:
                if po["fonte"] == FONTE_CITACAO:
                    res = await llm.citacao_de_texto(con, p["contexto_md"], po["texto"])
                    if usa_banco and not tmp:
                        tmp = _fundo_tmp()
                        credito = banco.credito(await banco.baixar_uma(res["busca"], tmp, "portrait"))
                    novo, estourou = await render.citacao(res["frase"], res["autor"], p["handle"], p["nome"], p,
                                                          None if usa_banco else ESTILOS_CITACAO[post_id % len(ESTILOS_CITACAO)],
                                                          tmp, credito)
                    manchete, reacao = res["frase"], res["autor"]
                else:
                    res = await llm.meme_de_texto(con, p["contexto_md"], po["texto"])
                    if not tmp:
                        tmp = _fundo_tmp()
                        credito = banco.credito(await banco.baixar_uma(res["busca"], tmp, "portrait"))
                    novo, estourou = await render.meme(tmp, res["topo"], res["base"], p)
                    manchete, reacao = res["topo"] or res["base"], res["base"]
                if estourou:
                    feedback = "o texto não coube no card, encurte"
                    continue
            except ValueError as e:
                feedback = str(e)
                continue
            break
        else:
            res = None
        if not res or not novo:
            raise ValueError(f"o modelo não entregou uma saída válida em 3 tentativas ({feedback})")
        legenda = res["legenda"] + (f"\n\n{credito}" if credito else "")
        _set(post_id, destino, json_llm=json.dumps(res, ensure_ascii=False), manchete=manchete, reacao=reacao,
             legenda=legenda, arquivo=novo, erro=None)
        db.log(p["id"], post_id, "gerado_visual", po["fonte"])
        if destino == "aguardando_aprovacao" and telegram.ativo() and p["telegram_chat_id"]:
            try:
                mid = await telegram.enviar_card(p["telegram_chat_id"], C.CARDS / novo, post_id, legenda, aviso)
                db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, post_id))
            except Exception as e:
                db.log(p["id"], post_id, "telegram_falhou", str(e))
        return True
    except Exception as e:
        await _apagar_async(novo)
        msg = (str(e) or type(e).__name__)[:400]
        _set(post_id, "falhou", erro=msg)
        db.log(p["id"], post_id, "falhou", msg)
        if destino == "aguardando_aprovacao" and telegram.ativo() and p["telegram_chat_id"]:
            await telegram.avisar(p["telegram_chat_id"], f"Falha ao gerar post #{post_id}: {msg[:200]}")
        return False
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)


def _existe(nome) -> bool:
    return bool(nome) and (C.CARDS / nome).exists()


async def _criar_visual(perfil_id: int, tema: str, fonte: str, banco_img: bool) -> list[int]:
    p = perfil(perfil_id)
    tema = (tema or "").strip()
    if not p or len(tema) < 4:
        return []
    async with _GERACAO:
        pid = db.x("INSERT INTO posts(perfil_id,estado,noticia_titulo,fonte,texto,formato,angulo,criado_em,atualizado_em)"
                   " VALUES(?,?,?,?,?,?,?,?,?)",
                   (perfil_id, "capturado", tema[:120], fonte, tema, "feed", "banco" if banco_img else "", db.now(), db.now()))
        return [pid] if await _processar_visual(pid, p) else []


async def criar_citacao(perfil_id: int, tema: str, com_foto: bool = False) -> list[int]:
    """Card de citação com as cores da marca; com_foto usa uma foto do banco de imagens (Higgsfield ou Unsplash) como fundo."""
    return await _criar_visual(perfil_id, tema, FONTE_CITACAO, com_foto)


async def criar_meme_banco(perfil_id: int, situacao: str) -> list[int]:
    """Meme com texto em cima/embaixo sobre uma foto do banco de imagens."""
    return await _criar_visual(perfil_id, situacao, FONTE_MEME, True)


async def _refazer_visual(po: dict) -> bool:
    if not _claim(po["id"], ESTADOS_ABERTOS, "extraido"):
        return False
    p = perfil(po["perfil_id"])
    destino = "rascunho" if po["estado"] in ("rascunho", "agendado") else "aguardando_aprovacao"
    async with _GERACAO:
        ok = await _processar_visual(po["id"], p, destino)
    if ok:
        await asyncio.to_thread(_apagar_post, po)
        db.log(p["id"], po["id"], "refeito")
        if po["tg_message_id"] and p["telegram_chat_id"]:
            await telegram.marcar(p["telegram_chat_id"], po["tg_message_id"], "Refeito. Nova versão abaixo.")
    return ok


async def criar_meme_foto(p: dict, src, texto: str) -> int:
    """Meme com a SUA foto: os textos de cima/baixo vêm da descrição que você escreveu na legenda (“meme: …”)."""
    con = conexao_do_modulo("legenda", p)
    if not con or not con["modelo"]:
        raise ValueError("nenhum LLM configurado: o meme precisa dele para escrever o texto")
    descricao = re.sub(r"(?i)^\s*meme\b[:,.\s-]*", "", texto or "").strip() or "situação engraçada"
    res = await llm.meme_de_texto(con, p["contexto_md"], descricao)
    nome, estourou = await render.meme(src, res["topo"], res["base"], p)
    if estourou:
        await _apagar_async(nome)
        raise ValueError("o texto do meme não coube na imagem; peça de novo com uma ideia mais curta")
    pid = db.x("INSERT INTO posts(perfil_id,estado,noticia_titulo,fonte,texto,reacao,legenda,arquivo,formato,criado_em,atualizado_em)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (p["id"], "aguardando_aprovacao", descricao[:120], "Telegram", descricao, res["base"], res["legenda"], nome, "feed", db.now(), db.now()))
    db.log(p["id"], pid, "meme_criado")
    if p["telegram_chat_id"]:
        mid = await telegram.enviar_card(p["telegram_chat_id"], C.CARDS / nome, pid, res["legenda"], "")
        db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, pid))
    return pid


async def adaptar(post_id: int, formato: str) -> int | None:
    """Cria uma cópia do post em outro formato (feed <-> story) sem cortar a imagem. O original continua como está."""
    po = post(post_id)
    if not po or formato not in ("feed", "story") or po["formato"] == formato or po["formato"] == "carrossel":
        return None
    arq = po["arquivo"]
    if not arq or not (C.CARDS / arq).exists() or not arq.endswith(".jpg"):
        return None
    p = perfil(po["perfil_id"])
    novo = await midia.adaptar(arq, formato)
    legenda = "" if formato == "story" else po["legenda"]
    pid = db.x("INSERT INTO posts(perfil_id,estado,noticia_titulo,noticia_url,fonte,texto,reacao,manchete,legenda,arquivo,formato,criado_em,atualizado_em)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (po["perfil_id"], "aguardando_aprovacao", po["noticia_titulo"], po["noticia_url"], "Telegram" if not po["noticia_url"] else po["fonte"],
                po["texto"], po["reacao"], po["manchete"], legenda, novo, formato, db.now(), db.now()))
    db.log(po["perfil_id"], pid, "adaptado", f"#{post_id} -> {formato}")
    if p["telegram_chat_id"] and telegram.ativo():
        try:
            mid = await telegram.enviar_card(p["telegram_chat_id"], C.CARDS / novo, pid, legenda or "(Story sem legenda)", f"📐 Versão {formato.upper()} do post #{post_id}")
            db.x("UPDATE posts SET tg_message_id=? WHERE id=?", (mid, pid))
        except Exception as e:
            db.log(po["perfil_id"], pid, "telegram_falhou", str(e))
    return pid
