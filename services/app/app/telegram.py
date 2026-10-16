"""Aprovação pelo celular: envia o card com botões e recebe os cliques (long polling)."""
import asyncio, json

import httpx

from . import config as C


def _url(metodo: str) -> str:
    return f"{C.TELEGRAM_API}/bot{C.TELEGRAM_TOKEN}/{metodo}"


async def _call(metodo: str, **kw):
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(_url(metodo), **kw)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram: {data.get('description', r.text[:100])}")
        return data["result"]


def ativo() -> bool:
    return bool(C.TELEGRAM_TOKEN)


async def enviar_card(chat_id: str, arquivo, post_id: int, legenda: str, aviso: str = "") -> str:
    teclado = {"inline_keyboard": [[
        {"text": "✅ Postar", "callback_data": f"ap:{post_id}"},
        {"text": "🔄 Refazer", "callback_data": f"rf:{post_id}"},
        {"text": "🗑 Descartar", "callback_data": f"ds:{post_id}"}]]}
    cap = (f"{aviso}\n\n" if aviso else "") + legenda
    with open(arquivo, "rb") as f:
        res = await _call("sendPhoto", data={"chat_id": chat_id, "caption": cap[:1024],
                                             "reply_markup": json.dumps(teclado)}, files={"photo": f})
    return str(res["message_id"])


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


async def poll(on_acao) -> None:
    """on_acao(acao, post_id, chat_id) é async. Roda até ser cancelada."""
    offset = 0
    while True:
        try:
            async with httpx.AsyncClient(timeout=45) as c:
                r = await c.post(_url("getUpdates"), data={"timeout": 25, "offset": offset,
                                                           "allowed_updates": json.dumps(["callback_query"])})
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
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
