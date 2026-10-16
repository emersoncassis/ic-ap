"""Mantém o bot do Telegram e o túnel alinhados com o que está salvo na interface (checa a cada 2 s)."""
import asyncio, contextlib, time

from . import db, pipeline, settings, telegram
from .tunnel import tunel


async def loop() -> None:
    tg_task: asyncio.Task | None = None
    tg_token = ""
    try:
        while True:
            try:
                t = settings.telegram_token()
                if t != tg_token or (t and tg_task and tg_task.done()):
                    if tg_task:
                        tg_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await tg_task
                    tg_task = asyncio.create_task(telegram.poll(pipeline.acao_telegram, pipeline.mensagem_telegram)) if t else None
                    tg_token = t

                tk = settings.tunnel_token()
                if not tk:
                    if tunel.proc or tunel.token:
                        await tunel.parar()
                        tunel.token = ""
                else:
                    morto = tunel.proc is None or tunel.proc.returncode is not None
                    if tk != tunel.token or (morto and time.time() >= tunel.retry_em):
                        await tunel.iniciar(tk)
                        tunel.retry_em = time.time() + 15
            except asyncio.CancelledError:
                raise
            except Exception as e:
                db.log(None, None, "supervisor_erro", str(e))
            await asyncio.sleep(2)
    finally:
        if tg_task:
            tg_task.cancel()
        await tunel.parar()
