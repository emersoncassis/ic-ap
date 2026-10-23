"""Gerencia o processo `cloudflared` com o token informado na interface."""
import asyncio, os
from collections import deque

from . import config as C


class Tunel:
    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.token = ""
        self.status = "parado"      # parado | iniciando | conectado | caiu | erro
        self.linhas: deque[str] = deque(maxlen=12)
        self.retry_em = 0.0
        self._leitor: asyncio.Task | None = None

    async def iniciar(self, token: str) -> None:
        await self.parar()
        self.token, self.status = token, "iniciando"
        self.linhas.clear()
        try:
            self.proc = await asyncio.create_subprocess_exec(
                C.CLOUDFLARED_BIN, "tunnel", "--no-autoupdate", "run",
                env={**os.environ, "TUNNEL_TOKEN": token},  # por env, para não aparecer na lista de processos
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        except FileNotFoundError:
            self.proc, self.status = None, "erro"
            self.linhas.append("cloudflared não encontrado neste container")
            return
        self._leitor = asyncio.create_task(self._ler(self.proc, token))

    async def _ler(self, proc, token: str) -> None:
        async for raw in proc.stdout:
            linha = raw.decode(errors="replace").strip().replace(token, "***")
            self.linhas.append(linha[:300])
            if "Registered tunnel connection" in linha:
                self.status = "conectado"
        if self.status != "parado":
            self.status = "caiu"

    async def parar(self) -> None:
        self.status = "parado"
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except asyncio.TimeoutError:
                self.proc.kill()
        if self._leitor:
            self._leitor.cancel()
        self.proc = self._leitor = None


tunel = Tunel()
