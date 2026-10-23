"""Servidor mínimo só para a pasta de imagens temporárias (127.0.0.1:PUBLIC_PORT).
É isto que o túnel da Cloudflare expõe. O painel NÃO está nesta porta."""
import contextlib

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from . import config as C

_server: uvicorn.Server | None = None


async def servir() -> None:
    global _server
    C.PUBLIC.mkdir(parents=True, exist_ok=True)
    app = Starlette(routes=[Mount("/", StaticFiles(directory=str(C.PUBLIC), html=False))])  # sem listagem; 404 limpo
    _server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=C.PUBLIC_PORT, log_level="warning", access_log=False))
    _server.capture_signals = contextlib.nullcontext  # não roubar os sinais do servidor principal
    await _server.serve()


def parar() -> None:
    if _server:
        _server.should_exit = True
