"""Aprovação pelo celular: envia o card com botões e recebe os cliques (long polling)."""
import asyncio, json

import httpx

from . import config as C, settings


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


async def enviar_card(chat_id: str, arquivo, post_id: int, legenda: str, aviso: str = "") -> str:
    teclado = {"inline_keyboard": [[
        {"text": "✅ Postar", "callback_data": f"ap:{post_id}"},
        {"text": "🔄 Refazer", "callback_data": f"rf:{post_id}"},
        {"text": "🗑 Descartar", "callback_data": f"ds:{post_id}"}]]}
    cap = (f"{aviso}\n\n" if aviso else "") + legenda
    video = str(arquivo).endswith(".mp4")
    with open(arquivo, "rb") as f:
        res = await _call("sendVideo" if video else "sendPhoto",
                          data={"chat_id": chat_id, "caption": cap[:1024], "reply_markup": json.dumps(teclado)},
                          files={"video" if video else "photo": f})
    return str(res["message_id"])


_TECLADO = lambda post_id: {"inline_keyboard": [[
    {"text": "✅ Postar", "callback_data": f"ap:{post_id}"},
    {"text": "🔄 Refazer", "callback_data": f"rf:{post_id}"},
    {"text": "🗑 Descartar", "callback_data": f"ds:{post_id}"}]]}


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
                if u.get("message") and on_msg:
                    asyncio.create_task(on_msg(u["message"]))
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
                asyncio.create_task(on_acao(acao, int(pid), chat_id))
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(5)
