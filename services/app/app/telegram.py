import asyncio, json, time

import httpx

from . import banco, config as C, db, settings, tarefas

_ultimo_chat_detectado: dict | None = None


def registrar_chat_recente(chat_id: str, nome: str = "", username: str = "") -> dict:
    global _ultimo_chat_detectado
    cid = str(chat_id).strip()
    nm = (nome or username or "Usuário").strip()
    un = (username or "").strip()
    dados = {
        "chat_id": cid,
        "nome": nm,
        "username": un,
        "timestamp": time.time(),
    }
    _ultimo_chat_detectado = dados
    try:
        db.set_setting("ultimo_chat_tg", json.dumps(dados))
    except Exception:
        pass
    return dados


def _url(metodo: str) -> str:
    return f"{C.TELEGRAM_API}/bot{settings.telegram_token()}/{metodo}"


async def _call(metodo: str, **kw):
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(_url(metodo), **kw)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram: {data.get('description', r.text[:100])}")
        return data["result"]


def ativo() -> bool:
    return bool(settings.telegram_token())


async def obter_me() -> dict | None:
    """Retorna dados do bot (username, nome) para conferir token."""
    if not ativo():
        return None
    try:
        return await _call("getMe")
    except Exception:
        return None


async def detectar_chat_recente() -> dict | None:
    """Lê as atualizações recentes do bot e identifica o último chat que mandou mensagem."""
    global _ultimo_chat_detectado
    # 1. Se já foi interceptado pelo polling na memória (< 2 horas)
    if _ultimo_chat_detectado and (time.time() - _ultimo_chat_detectado.get("timestamp", 0)) < 7200:
        return _ultimo_chat_detectado

    # 2. Se foi gravado no banco de dados
    try:
        salvo = db.get_setting("ultimo_chat_tg")
        if salvo:
            dados = json.loads(salvo)
            if dados.get("chat_id") and (time.time() - dados.get("timestamp", 0)) < 7200:
                _ultimo_chat_detectado = dados
                return dados
    except Exception:
        pass

    if not ativo():
        return None

    # 3. Tenta obter diretamente do Telegram se ainda houver update pendente
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(_url("getUpdates"), data={"limit": 20})
            data = r.json()
            if not data.get("ok"):
                return None
            updates = data.get("result", [])
            for u in reversed(updates):
                msg = u.get("message") or u.get("callback_query", {}).get("message")
                if msg and msg.get("chat"):
                    ch = msg["chat"]
                    cid = str(ch["id"])
                    nome = ch.get("first_name", "") + (" " + ch.get("last_name", "") if ch.get("last_name") else "")
                    user = ch.get("username", "")
                    return registrar_chat_recente(cid, nome, user)
    except Exception:
        pass
    return None


async def enviar_card(chat_id: str, arquivo, post_id: int, legenda: str, aviso: str = "") -> str:
    teclado = _TECLADO(post_id, str(arquivo).endswith(".jpg"))
    cap = (f"{aviso}\n\n" if aviso else "") + legenda
    video = str(arquivo).endswith(".mp4")
    with open(arquivo, "rb") as f:
        res = await _call("sendVideo" if video else "sendPhoto",
                          data={"chat_id": chat_id, "caption": cap[:1024], "reply_markup": json.dumps(teclado)},
                          files={"video" if video else "photo": f})
    return str(res["message_id"])


def _quando(utc: str) -> str:
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    return datetime.strptime(utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.tz())).strftime("%d/%m %H:%M")


async def enviar_foto(chat_id: str, arquivo, legenda: str = "") -> None:
    try:
        with open(arquivo, "rb") as f:
            await _call("sendPhoto", data={"chat_id": chat_id, "caption": legenda[:1024]}, files={"photo": f})
    except Exception:
        pass


def _TECLADO(post_id: int, imagem: bool = False) -> dict:
    linhas = [[{"text": "✅ Postar", "callback_data": f"ap:{post_id}"},
               {"text": "🕒 Agendar", "callback_data": f"ag:{post_id}"}],
              [{"text": "🔄 Refazer", "callback_data": f"rf:{post_id}"},
               {"text": "🗑 Descartar", "callback_data": f"ds:{post_id}"}]]
    sug = db.one("SELECT agendado_para FROM posts WHERE id=? AND estado='aguardando_aprovacao' AND agendado_para IS NOT NULL", (post_id,))
    if sug:  # esteira: um toque confirma o horário sugerido
        linhas.insert(0, [{"text": f"✅ Agendar {_quando(sug['agendado_para'])}", "callback_data": f"ak:{post_id}"}])
    po = db.one("SELECT formato FROM posts WHERE id=?", (post_id,)) if imagem else None
    if po and po["formato"] in ("feed", "story"):
        opcoes_extras = [
            {"text": "📐 Versão Story" if po["formato"] == "feed" else "📐 Versão Feed", "callback_data": f"ad:{post_id}"},
            {"text": "🎨 Mudar Estilo", "callback_data": f"tpl:{post_id}"},
        ]
        foto_sua = db.one("SELECT 1 FROM posts WHERE id=? AND fonte='Telegram'", (post_id,))
        if foto_sua and banco.higgs_chave():
            opcoes_extras.append({"text": "🎬 Vídeo por IA", "callback_data": f"ia:{post_id}"})
        linhas.append(opcoes_extras)
    return {"inline_keyboard": linhas}


async def enviar_carrossel(chat_id: str, arquivos: list, post_id: int, legenda: str, aviso: str = "") -> str:
    """Álbum com os slides + uma mensagem com a legenda e os botões. Devolve o id da mensagem com os botões."""
    abertos = {f"f{i}": open(a, "rb") for i, a in enumerate(arquivos[:10])}
    try:
        await _call("sendMediaGroup", data={"chat_id": chat_id, "media": json.dumps(
            [{"type": "photo", "media": f"attach://{k}"} for k in abertos])}, files=abertos)
    finally:
        for f in abertos.values():
            f.close()
    cab = (f"{aviso}\n\n" if aviso else "") + f"Carrossel de {len(abertos)} slides\n\n"
    res = await _call("sendMessage", data={"chat_id": chat_id, "text": (cab + legenda)[:4000],
                                           "reply_markup": json.dumps(_TECLADO(post_id))})
    return str(res["message_id"])


async def enviar_botoes(chat_id: str, texto: str, linhas: list[list[tuple[str, str]]]) -> str:
    teclado = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in linha] for linha in linhas]}
    res = await _call("sendMessage", data={"chat_id": chat_id, "text": texto[:4000], "reply_markup": json.dumps(teclado)})
    return str(res["message_id"])


async def digitando(chat_id: str) -> None:
    try:
        await _call("sendChatAction", data={"chat_id": chat_id, "action": "typing"})
    except Exception:
        pass


MAX_DOWNLOAD = 20 * 1024 * 1024  # limite do getFile na API padrão de bots


async def baixar(file_id: str, destino) -> None:
    info = await _call("getFile", data={"file_id": file_id})
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.get(f"{C.TELEGRAM_API}/file/bot{settings.telegram_token()}/{info['file_path']}")
        r.raise_for_status()
    destino.write_bytes(r.content)


async def avisar(chat_id: str, texto: str) -> None:
    try:
        await _call("sendMessage", data={"chat_id": chat_id, "text": texto[:4000]})
    except Exception:
        pass


async def marcar(chat_id: str, message_id: str, texto: str) -> None:
    """Remove os botões e anota o desfecho. Falha silenciosa."""
    try:
        await _call("editMessageReplyMarkup", data={"chat_id": chat_id, "message_id": message_id,
                                                    "reply_markup": json.dumps({"inline_keyboard": []})})
        await _call("sendMessage", data={"chat_id": chat_id, "text": texto, "reply_to_message_id": message_id})
    except Exception:
        pass


async def poll(on_acao, on_msg=None) -> None:
    """on_acao(acao, post_id, chat_id) e on_msg(mensagem) são async. Roda até ser cancelada."""
    offset = 0
    while True:
        try:
            async with httpx.AsyncClient(timeout=45) as c:
                r = await c.post(_url("getUpdates"), data={"timeout": 25, "offset": offset,
                                                           "allowed_updates": json.dumps(["callback_query", "message"])})
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or (u.get("callback_query") or {}).get("message")
                if msg and msg.get("chat"):
                    ch = msg["chat"]
                    cid = str(ch.get("id", ""))
                    nome = ch.get("first_name", "") + (" " + ch.get("last_name", "") if ch.get("last_name") else "")
                    user = ch.get("username", "")
                    registrar_chat_recente(cid, nome, user)

                if u.get("message") and on_msg:
                    tarefas.disparar(on_msg(u["message"]))
                    continue
                cq = u.get("callback_query")
                if not cq or ":" not in cq.get("data", ""):
                    continue
                acao, pid = cq["data"].split(":", 1)
                chat_id = str(cq["message"]["chat"]["id"])
                try:
                    await _call("answerCallbackQuery", data={"callback_query_id": cq["id"], "text": "Ok, processando…"})
                except Exception:
                    pass
                tarefas.disparar(on_acao(acao, int(pid), chat_id))
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(5)
