"""Transcrição (Whisper) e voz (TTS) por servidores compatíveis com a API da OpenAI, rodando FORA do app (faster-whisper-server,
whisper.cpp server, Kokoro/Piper/OpenAI-edge-tts, LM Studio etc.). O endereço é configurado em Conexões."""
import re, uuid
from pathlib import Path

import httpx

from . import config as C, db, midia, settings


class VozError(Exception):
    pass


def _cfg(kind: str) -> dict:
    return {"url": db.get_setting(f"{kind}_url").strip().rstrip("/"), "modelo": db.get_setting(f"{kind}_model").strip(),
            "voz": db.get_setting("tts_voz").strip() if kind == "tts" else "", "chave": settings.segredo(f"{kind}_key")}


def whisper_ok() -> bool:
    return bool(_cfg("whisper")["url"])


def tts_ok() -> bool:
    return bool(_cfg("tts")["url"])


def _endpoint(base: str, caminho: str) -> str:
    base = base[:-3] if base.endswith("/v1") else base
    return f"{base}/v1/{caminho}"


def _headers(c: dict) -> dict:
    return {"Authorization": f"Bearer {c['chave']}"} if c["chave"] else {}


async def _audio_16k(src: Path) -> Path:
    """Extrai só o áudio (mono, 16 kHz) para a transcrição ficar leve."""
    dest = C.DATA / "tmp" / f"{uuid.uuid4().hex}.mp3"
    dest.parent.mkdir(parents=True, exist_ok=True)
    await midia._run("ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(dest))
    return dest


async def transcrever(src: Path) -> list[dict]:
    """Palavras com tempo: [{'w': 'texto', 'ini': 0.0, 'fim': 0.4}, ...]. Pede timestamps por palavra; se o servidor só der segmentos,
    distribui as palavras do segmento pelo tempo dele."""
    c = _cfg("whisper")
    if not c["url"]:
        raise VozError("transcrição não configurada (Conexões → Transcrição)")
    audio = await _audio_16k(src)
    try:
        dados = {"model": c["modelo"] or "whisper-1", "response_format": "verbose_json", "language": "pt",
                 "timestamp_granularities[]": ["word", "segment"]}
        async with httpx.AsyncClient(timeout=600) as cli:
            with open(audio, "rb") as f:
                r = await cli.post(_endpoint(c["url"], "audio/transcriptions"), headers=_headers(c), data=dados,
                    files={"file": (audio.name, f, "audio/mpeg")})
        if r.status_code >= 400:
            raise VozError(f"o servidor de transcrição respondeu HTTP {r.status_code}: {r.text[:150]}")
        d = r.json()
    except httpx.HTTPError as e:
        raise VozError(f"não consegui falar com o servidor de transcrição ({type(e).__name__})")
    finally:
        audio.unlink(missing_ok=True)
    palavras = [{"w": str(w.get("word") or w.get("text") or "").strip(), "ini": float(w.get("start", 0)), "fim": float(w.get("end", 0))}
                for w in d.get("words") or []]
    if not palavras:
        for seg in d.get("segments") or []:
            ws = str(seg.get("text") or "").split()
            if ws:
                a, b = float(seg.get("start", 0)), float(seg.get("end", 0))
                palavras += _distribuir(ws, a, b)
    return [w for w in palavras if w["w"]]


def _distribuir(ws: list[str], ini: float, fim: float) -> list[dict]:
    """Reparte o tempo entre as palavras na proporção do tamanho de cada uma."""
    total = sum(len(w) + 1 for w in ws) or 1
    t, out = ini, []
    for w in ws:
        dur = (fim - ini) * (len(w) + 1) / total
        out.append({"w": w, "ini": t, "fim": t + dur})
        t += dur
    return out


def estimar(texto: str, duracao: float) -> list[dict]:
    """Tempo das palavras quando não há transcrição (ex.: narração gerada pela voz local)."""
    return _distribuir(texto.split(), 0.0, duracao)


async def narrar(texto: str) -> Path:
    """Fala o texto com o servidor de voz. Devolve um áudio mp3 em data/tmp."""
    c = _cfg("tts")
    if not c["url"]:
        raise VozError("voz não configurada (Conexões → Voz)")
    texto = re.sub(r"\s+", " ", texto).strip()
    if not texto:
        raise VozError("narração vazia")
    corpo = {"model": c["modelo"] or "tts-1", "input": texto[:4000], "voice": c["voz"] or "alloy", "response_format": "mp3"}
    try:
        async with httpx.AsyncClient(timeout=600) as cli:
            r = await cli.post(_endpoint(c["url"], "audio/speech"), headers=_headers(c), json=corpo)
    except httpx.HTTPError as e:
        raise VozError(f"não consegui falar com o servidor de voz ({type(e).__name__})")
    if r.status_code >= 400:
        raise VozError(f"o servidor de voz respondeu HTTP {r.status_code}: {r.text[:150]}")
    if len(r.content) < 500:
        raise VozError("o servidor de voz devolveu um áudio vazio")
    dest = C.DATA / "tmp" / f"{uuid.uuid4().hex}.mp3"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest
