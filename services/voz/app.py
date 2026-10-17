"""Servidor de voz local, com a mesma API da OpenAI que o ic-ap já usa:
  POST /v1/audio/transcriptions  (faster-whisper)
  POST /v1/audio/speech          (Chatterbox Multilingual; o campo "voice" é o nome da voz criada na aba Voz do painel)
  GET  /health
As amostras ficam em DATA_DIR/vozes/<nome>/ref.wav (volume compartilhado com o app, somente leitura aqui)."""
import io, os, re, subprocess, threading, wave
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

DATA = Path(os.getenv("DATA_DIR", "/data"))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3-turbo")
PRELOAD = os.getenv("PRELOAD", "1") == "1"
IDIOMA_TTS = os.getenv("TTS_LANG", "pt")
MAX_CHARS = 220          # o modelo fala bem trechos curtos; textos longos são fatiados por frase

app = FastAPI(title="ic-ap voz", docs_url=None, redoc_url=None, openapi_url=None)
_lock = threading.Lock()          # uma geração por vez na GPU
_estado = {"whisper": None, "whisper_info": "não carregado", "tts": None, "tts_info": "não carregado", "gpu": None, "erro": ""}


def _gpu() -> str | None:
    try:
        import torch
        return torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except Exception:
        return None


def _carregar_whisper():
    if _estado["whisper"] is not None:
        return _estado["whisper"]
    from faster_whisper import WhisperModel
    tentativas = [("cuda", "float16"), ("cpu", "int8")] if _gpu() else [("cpu", "int8")]
    ultimo = None
    for dev, tipo in tentativas:
        try:
            m = WhisperModel(WHISPER_MODEL, device=dev, compute_type=tipo)
            # teste rápido: alguns builds carregam na GPU e só falham ao rodar
            list(m.transcribe(np.zeros(16000, dtype=np.float32), language="pt")[0])
            _estado["whisper"], _estado["whisper_info"] = m, f"{WHISPER_MODEL} ({dev})"
            return m
        except Exception as e:      # noqa: BLE001
            ultimo = e
            _estado["erro"] = f"whisper {dev}: {e}"[:300]
    raise RuntimeError(f"não consegui carregar o Whisper: {ultimo}")


def _carregar_tts():
    if _estado["tts"] is not None:
        return _estado["tts"]
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    _estado["tts"] = ChatterboxMultilingualTTS.from_pretrained(device=dev)
    _estado["tts_info"] = f"chatterbox-multilingual ({dev})"
    return _estado["tts"]


def _pre_carregar():
    for f in (_carregar_tts, _carregar_whisper):
        try:
            with _lock:
                f()
        except Exception as e:      # noqa: BLE001
            _estado["erro"] = str(e)[:300]


@app.on_event("startup")
def _inicio():
    _estado["gpu"] = _gpu()
    if PRELOAD:
        threading.Thread(target=_pre_carregar, daemon=True).start()


@app.get("/health")
def health():
    return {"ok": True, "gpu": _estado["gpu"] or _gpu(), "whisper": _estado["whisper_info"], "tts": _estado["tts_info"],
            "clonagem": True, "erro": _estado["erro"] or None}


# ---------- transcrição ----------
@app.post("/v1/audio/transcriptions")
def transcrever(file: UploadFile = File(...), language: str = Form("pt"), model: str = Form(""),
                response_format: str = Form("verbose_json")):
    tmp = Path("/tmp") / f"in_{os.getpid()}_{threading.get_ident()}_{file.filename or 'a'}"
    tmp.write_bytes(file.file.read())
    try:
        with _lock:
            m = _carregar_whisper()
            segs, info = m.transcribe(str(tmp), language=language or None, word_timestamps=True, vad_filter=True)
            segs = list(segs)
    except Exception as e:      # noqa: BLE001
        raise HTTPException(500, f"falha na transcrição: {e}")
    finally:
        tmp.unlink(missing_ok=True)
    palavras = [{"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)} for s in segs for w in (s.words or [])]
    texto = " ".join(s.text.strip() for s in segs).strip()
    if response_format == "text":
        return Response(texto, media_type="text/plain")
    return {"task": "transcribe", "language": info.language, "duration": round(info.duration, 2), "text": texto, "words": palavras,
            "segments": [{"id": i, "start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()} for i, s in enumerate(segs)]}


# ---------- voz ----------
def _fatiar(texto: str) -> list[str]:
    texto = re.sub(r"\s+", " ", texto).strip()
    pecas = []
    for f in re.split(r"(?<=[.!?…])\s+", texto):
        while len(f) > MAX_CHARS:                     # frase gigante: corta na vírgula/espaço mais próximo
            corte = max(f.rfind(", ", 0, MAX_CHARS), f.rfind(" ", 0, MAX_CHARS))
            corte = corte if corte > 40 else MAX_CHARS
            pecas.append(f[:corte].strip())
            f = f[corte:].strip(" ,")
        if f:
            pecas.append(f)
    blocos, atual = [], ""
    for p in pecas:
        if atual and len(atual) + 1 + len(p) > MAX_CHARS:
            blocos.append(atual)
            atual = p
        else:
            atual = (atual + " " + p).strip()
    if atual:
        blocos.append(atual)
    return blocos


def _wav_bytes(x: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


@app.post("/v1/audio/speech")
def falar(corpo: dict):
    texto = str(corpo.get("input") or "").strip()
    voz = str(corpo.get("voice") or "").strip()
    fmt = str(corpo.get("response_format") or "mp3").lower()
    if not texto:
        raise HTTPException(400, "texto vazio")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", voz):
        raise HTTPException(400, "voz inválida: crie uma voz na aba Voz do painel e escolha-a como padrão")
    ref = DATA / "vozes" / voz / "ref.wav"
    if not ref.exists():
        raise HTTPException(404, f"a voz “{voz}” não existe aqui: grave a amostra na aba Voz do painel")
    try:
        import torch
        with _lock:
            tts = _carregar_tts()
            partes, pausa = [], np.zeros(int(tts.sr * 0.18), dtype=np.float32)
            for bloco in _fatiar(texto[:4000]):
                with torch.inference_mode():
                    wav = tts.generate(bloco, language_id=IDIOMA_TTS, audio_prompt_path=str(ref))
                partes += [wav.squeeze(0).float().cpu().numpy(), pausa]
            sr = tts.sr
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    except Exception as e:      # noqa: BLE001
        raise HTTPException(500, f"falha ao gerar a voz: {e}")
    wav_b = _wav_bytes(np.concatenate(partes), sr)
    if fmt == "wav":
        return Response(wav_b, media_type="audio/wav")
    p = subprocess.run(["ffmpeg", "-v", "error", "-f", "wav", "-i", "-", "-codec:a", "libmp3lame", "-q:a", "3", "-f", "mp3", "-"],
                       input=wav_b, capture_output=True)
    if p.returncode != 0 or not p.stdout:
        raise HTTPException(500, "falha ao converter para mp3")
    return Response(p.stdout, media_type="audio/mpeg")
