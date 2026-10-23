"""Tarefas em segundo plano (disparar e esquecer) sem o risco de serem coletadas pelo lixo no meio da execução.

O asyncio guarda só referência FRACA às tarefas: `asyncio.create_task(...)` sem guardar o retorno pode cancelar
silenciosamente a geração de um post. Aqui mantemos a referência até o fim e registramos qualquer exceção."""
import asyncio, logging
from typing import Coroutine

log = logging.getLogger("icap.tarefas")
_vivas: set[asyncio.Task] = set()


def disparar(coro: Coroutine, nome: str = "") -> asyncio.Task:
    t = asyncio.create_task(coro, name=nome or None)
    _vivas.add(t)
    t.add_done_callback(_terminou)
    return t


def _terminou(t: asyncio.Task) -> None:
    _vivas.discard(t)
    if not t.cancelled() and t.exception() is not None:
        log.error("tarefa %s falhou", t.get_name(), exc_info=t.exception())
