"""pipeline._apagar no Windows: arquivo preso não trava o loop de eventos e acaba apagado (T7)."""
import asyncio
import threading
import time
import uuid
from pathlib import Path

from app import config as C, pipeline

_sleep_real = time.sleep


def _novo_card() -> tuple[str, Path]:
    C.CARDS.mkdir(parents=True, exist_ok=True)
    nome = f"{uuid.uuid4().hex}.jpg"
    (C.CARDS / nome).write_bytes(b"x")
    return nome, C.CARDS / nome


def _preso_por(monkeypatch, caminho: Path, falhas: int) -> dict:
    """Faz Path.unlink de `caminho` levantar PermissionError (WinError 32) nas primeiras `falhas` chamadas; esperas viram 10 ms."""
    orig, estado, trava = Path.unlink, {"chamadas": 0}, threading.Lock()

    def unlink(self, *a, **k):
        if self == caminho:
            with trava:
                estado["chamadas"] += 1
                if estado["chamadas"] <= falhas:
                    raise PermissionError(32, "O arquivo já está sendo usado por outro processo")
        return orig(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: _sleep_real(0.01))
    return estado


def test_apagar_tenta_de_novo_ate_o_windows_soltar_o_arquivo(monkeypatch):
    nome, caminho = _novo_card()
    estado = _preso_por(monkeypatch, caminho, falhas=4)
    pipeline._apagar(nome)
    assert not caminho.exists() and estado["chamadas"] == 5


def test_apagar_async_nao_trava_o_loop_enquanto_espera(monkeypatch):
    nome, caminho = _novo_card()
    _preso_por(monkeypatch, caminho, falhas=8)
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: _sleep_real(0.05))  # ≈0,4 s de espera no total

    async def principal():
        ticks, parar = 0, False

        async def relogio():
            nonlocal ticks
            while not parar:
                await asyncio.sleep(0.01)
                ticks += 1

        t = asyncio.create_task(relogio())
        await pipeline._apagar_async(nome)
        parar = True
        await t
        return ticks

    ticks = asyncio.run(principal())
    assert not caminho.exists()
    assert ticks >= 15, f"o loop ficou bloqueado durante a espera (só {ticks} ticks)"


def test_apagar_preso_por_muito_tempo_continua_em_segundo_plano(monkeypatch):
    nome, caminho = _novo_card()
    estado = _preso_por(monkeypatch, caminho, falhas=14)  # mais que as 10 tentativas imediatas
    pipeline._apagar(nome)  # não levanta nem espera para sempre
    fim = time.time() + 5
    while caminho.exists() and time.time() < fim:
        _sleep_real(0.02)
    assert not caminho.exists() and estado["chamadas"] == 15


def test_apagar_ignora_nome_fora_do_padrao(monkeypatch):
    C.CARDS.mkdir(parents=True, exist_ok=True)
    outro = C.CARDS / "meu_arquivo.jpg"
    outro.write_bytes(b"x")
    pipeline._apagar("meu_arquivo.jpg", None, "")
    assert outro.exists()
    outro.unlink()
