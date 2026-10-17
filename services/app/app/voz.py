"""Transcrição (Whisper) e voz (TTS) por servidores compatíveis com a API da OpenAI, rodando FORA do app (faster-whisper-server,
whisper.cpp server, Kokoro/Piper/OpenAI-edge-tts, LM Studio etc.). O endereço é configurado em Conexões."""
import asyncio, re, threading, uuid
from pathlib import Path

import httpx

from . import config as C, db, midia, settings


class VozError(Exception):
    pass


def _cfg(kind: str) -> dict:
    return {"url": db.get_setting(f"{kind}_url").strip().rstrip("/"), "modelo": db.get_setting(f"{kind}_model").strip(),
            "voz": db.get_setting("tts_voz").strip() if kind == "tts" else "", "chave": settings.segredo(f"{kind}_key")}


def local_ok() -> bool:
    """Transcrição embutida no próprio app (faster-whisper na CPU): funciona sem subir nenhum servidor. Desligue com a configuração whisper_local=0."""
    return db.get_setting("whisper_local", "1") != "0"


def usa_local() -> bool:
    return not _cfg("whisper")["url"] and local_ok()


def modelo_baixado() -> bool:
    return any((C.DATA / "modelos" / "whisper").glob("**/model.bin")) if (C.DATA / "modelos" / "whisper").exists() else False


def whisper_ok() -> bool:
    return bool(_cfg("whisper")["url"]) or local_ok()


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


_LOCAL: dict = {"modelo": None}
_LOCAL_LOCK = threading.Lock()


def _transcrever_local_sync(caminho: str) -> list[dict]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise VozError("o faster-whisper não está instalado no app: rode docker compose up -d --build")
    with _LOCAL_LOCK:
        try:
            if _LOCAL["modelo"] is None:
                nome = db.get_setting("whisper_local_modelo", "small") or "small"
                _LOCAL["modelo"] = WhisperModel(nome, device="cpu", compute_type="int8",
                                                download_root=str(C.DATA / "modelos" / "whisper"))
            segs, _ = _LOCAL["modelo"].transcribe(caminho, language="pt", word_timestamps=True, vad_filter=True, beam_size=1)
            return [{"w": str(w.word).strip(), "ini": float(w.start), "fim": float(w.end)} for s in segs for w in (s.words or []) if str(w.word).strip()]
        except VozError:
            raise
        except Exception as e:
            raise VozError(f"a transcrição local falhou ({type(e).__name__}: {str(e)[:150]}). Na primeira vez o app baixa o modelo da internet (~460 MB)")


async def _transcrever_local(src: Path) -> list[dict]:
    audio = await _audio_16k(src)
    try:
        return await asyncio.to_thread(_transcrever_local_sync, str(audio))
    finally:
        audio.unlink(missing_ok=True)


async def transcrever(src: Path) -> list[dict]:
    """Palavras com tempo: [{'w': 'texto', 'ini': 0.0, 'fim': 0.4}, ...]. Usa o servidor configurado em Conexões; sem servidor (ou com o
    servidor fora do ar) usa a transcrição embutida no app, na CPU, sem precisar subir nada."""
    c = _cfg("whisper")
    if not c["url"]:
        if not local_ok():
            raise VozError("transcrição não configurada (Conexões → Transcrição)")
        return await _transcrever_local(src)
    try:
        return await _transcrever_servidor(src, c)
    except VozError as e:
        if local_ok() and str(e).startswith("não consegui falar"):
            return await _transcrever_local(src)
        raise


async def _transcrever_servidor(src: Path, c: dict) -> list[dict]:
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


async def narrar(texto: str, voz: str | None = None, extra: dict | None = None) -> Path:
    """Fala o texto com o servidor de voz (voz padrão de Conexões, ou a indicada). Devolve um áudio mp3 em data/tmp."""
    c = _cfg("tts")
    if not c["url"]:
        raise VozError("voz não configurada (Conexões → Voz)")
    texto = re.sub(r"\s+", " ", texto).strip()
    if not texto:
        raise VozError("narração vazia")
    corpo = {"model": c["modelo"] or "tts-1", "input": texto[:4000], "voice": voz or c["voz"] or "alloy", "response_format": "mp3"}
    from . import vozes
    corpo.update(vozes.ajustes_de(corpo["voice"]))          # ajustes salvos da voz clonada (se houver)
    corpo.update({k: v for k, v in (extra or {}).items() if v is not None})
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
