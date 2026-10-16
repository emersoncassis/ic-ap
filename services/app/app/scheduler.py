"""Agendador: a cada ~30 s verifica os horários de cada perfil ativo e dispara a geração."""
import asyncio, re
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config as C, db, pipeline, settings

JANELA_MIN = 90  # slot perdido há mais que isso (ex.: app desligado) é descartado, não disparado atrasado


def slots_devidos(agora: datetime) -> list[tuple[int, str]]:
    hoje, devidos = agora.strftime("%Y-%m-%d"), []
    for p in db.q("SELECT id, horarios FROM perfis WHERE ativo=1"):
        for hh in (h.strip() for h in p["horarios"].split(",")):
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hh):
                continue
            h, m = map(int, hh.split(":"))
            atraso = (agora.hour * 60 + agora.minute) - (h * 60 + m)
            if atraso < 0:
                continue
            chave = f"slot:{p['id']}:{hoje}:{hh}"
            if db.get_setting(chave):
                continue
            db.set_setting(chave, "1")
            if atraso <= JANELA_MIN:
                devidos.append((p["id"], hh))
    return devidos


async def loop() -> None:
    while True:
        try:
            await pipeline.publicar_agendados()
            for pid, _ in slots_devidos(datetime.now(ZoneInfo(settings.tz()))):
                asyncio.create_task(pipeline.gerar(pid, 1, "agenda"))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            db.log(None, None, "scheduler_erro", str(e))
        await asyncio.sleep(C.TICK_SECONDS)
