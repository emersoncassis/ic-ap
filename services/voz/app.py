"""Servidor de voz local, com a mesma API da OpenAI que o ic-ap já usa:
  POST /v1/audio/transcriptions  (faster-whisper)
  POST /v1/audio/speech          (Chatterbox Multilingual; o campo "voice" é o nome da voz criada na aba Voz do painel)
  GET  /health
Dois motores de voz (variável ENGINE): "chatterbox" (padrão, MIT) ou "qwen" (Qwen3-TTS, Apache 2.0). Mesma API nos dois.
As amostras ficam em DATA_DIR/vozes/<nome>/ref.wav e ref.txt (volume compartilhado com o app, somente leitura aqui)."""
import gc, io, os, re, subprocess, threading, time, wave
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

DATA = Path(os.getenv("DATA_DIR", "/data"))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3-turbo")
PRELOAD = os.getenv("PRELOAD", "0") == "1"          # por padrão carrega só no primeiro uso, para não ocupar a placa à toa
IDLE_MIN = float(os.getenv("IDLE_MIN", "10"))        # minutos sem uso até descarregar os modelos da placa (0 = nunca)
IDIOMA_TTS = os.getenv("TTS_LANG", "pt")
ENGINE = os.getenv("ENGINE", "chatterbox").lower()
QWEN_MODEL = os.getenv("QWEN_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
# padrões do Chatterbox (o app pode sobrescrever por voz): cfg menor = mais parecido com a amostra
CFG_PADRAO, EXAG_PADRAO, TEMP_PADRAO = (float(os.getenv(k, v)) for k, v in (("CFG_PADRAO", "0.3"), ("EXAG_PADRAO", "0.5"), ("TEMP_PADRAO", "0.75")))
MAX_CHARS = 220          # o modelo fala bem trechos curtos; textos longos são fatiados por frase

app = FastAPI(title="ic-ap voz", docs_url=None, redoc_url=None, openapi_url=None)
_lock = threading.Lock()          # uma geração por vez na GPU
_ultimo_uso = [time.time()]
_cache = {"ref": None, "prompt": None, "txt": {}}
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
    cuda = torch.cuda.is_available()
    if ENGINE == "qwen":
        from qwen_tts import Qwen3TTSModel
        m = Qwen3TTSModel.from_pretrained(QWEN_MODEL, device_map="cuda:0" if cuda else "cpu",
                                          dtype=torch.bfloat16 if cuda else torch.float32)
        try:
            langs = m.get_supported_languages() or []
        except Exception:      # noqa: BLE001
            langs = []
        _estado["qwen_lang"] = next((l for l in langs if str(l).lower().startswith("portug")), "Portuguese")
        _estado["tts"], _estado["tts_info"] = m, f"qwen3-tts ({'cuda' if cuda else 'cpu'})"
    else:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        _estado["tts"] = ChatterboxMultilingualTTS.from_pretrained(device="cuda" if cuda else "cpu")
        _estado["tts_info"] = f"chatterbox-multilingual ({'cuda' if cuda else 'cpu'})"
    return _estado["tts"]


def _tocar() -> None:
    _ultimo_uso[0] = time.time()


def _descarregar() -> bool:
    """Tira Whisper e voz da memória da placa (o próximo uso recarrega). Só roda se não houver geração em andamento."""
    if not _lock.acquire(blocking=False):
        return False
    try:
        _estado.update(whisper=None, whisper_info="descarregado", tts=None, tts_info="descarregado")
        _cache.update(ref=None, prompt=None, txt={})
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:      # noqa: BLE001
            pass
        return True
    finally:
        _lock.release()


def _vigia_ociosidade() -> None:
    while True:
        time.sleep(30)
        if IDLE_MIN > 0 and time.time() - _ultimo_uso[0] > IDLE_MIN * 60 and (_estado["tts"] is not None or _estado["whisper"] is not None):
            _descarregar()


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
    threading.Thread(target=_vigia_ociosidade, daemon=True).start()
    if PRELOAD:
        threading.Thread(target=_pre_carregar, daemon=True).start()


@app.get("/health")
def health():
    return {"ok": True, "motor": ENGINE, "gpu": _estado["gpu"] or _gpu(), "whisper": _estado["whisper_info"], "tts": _estado["tts_info"],
            "clonagem": True, "ociosidade_min": IDLE_MIN, "carregado": _estado["tts"] is not None or _estado["whisper"] is not None,
            "erro": _estado["erro"] or None}


@app.post("/descarregar")
def descarregar():
    if not _descarregar():
        raise HTTPException(409, "há uma geração em andamento; tente de novo em instantes")
    return {"ok": True}


# ---------- transcrição ----------
@app.post("/v1/audio/transcriptions")
def transcrever(file: UploadFile = File(...), language: str = Form("pt"), model: str = Form(""),
                response_format: str = Form("verbose_json")):
    _tocar()
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


def _texto_da_ref(sl: str, ref: Path) -> str:
    """Texto dito na amostra: ref.txt (escrito/corrigido no painel) ou, na falta, transcrição local (guardada em memória)."""
    t = (ref.parent / "ref.txt")
    if t.exists() and t.read_text("utf-8").strip():
        return t.read_text("utf-8").strip()
    chave = (sl, ref.stat().st_mtime_ns)
    if chave not in _cache["txt"]:
        try:
            m = _carregar_whisper()
            segs, _ = m.transcribe(str(ref), language="pt", vad_filter=True)
            _cache["txt"][chave] = " ".join(x.text.strip() for x in segs).strip()
        except Exception as e:      # noqa: BLE001
            _estado["erro"] = f"transcrição da amostra: {e}"[:300]
            _cache["txt"][chave] = ""
    return _cache["txt"][chave]


def _gerar_blocos(blocos: list[str], sl: str, ref: Path, corpo: dict) -> tuple[list, int]:
    """Gera cada bloco de texto com a voz da amostra. Devolve (pedaços de áudio float32, taxa de amostragem)."""
    import torch
    tts = _carregar_tts()
    saida = []
    if ENGINE == "qwen":
        chave = (sl, ref.stat().st_mtime_ns, (ref.parent / "ref.txt").stat().st_mtime_ns if (ref.parent / "ref.txt").exists() else 0)
        if _cache["ref"] != chave:
            texto = _texto_da_ref(sl, ref)
            _cache["prompt"] = tts.create_voice_clone_prompt(ref_audio=str(ref), ref_text=texto or None, x_vector_only_mode=not texto)
            _cache["ref"] = chave
        kw = {"temperature": float(corpo["temperature"])} if corpo.get("temperature") is not None else {}
        sr = 24000
        for b in blocos:
            with torch.inference_mode():
                wavs, sr = tts.generate_voice_clone(text=b, language=_estado.get("qwen_lang", "Portuguese"),
                                                    voice_clone_prompt=_cache["prompt"], **kw)
            saida.append(np.asarray(wavs[0], dtype=np.float32).reshape(-1))
        return saida, int(sr)
    exag = float(corpo.get("exaggeration", EXAG_PADRAO))
    cfg = float(corpo.get("cfg_weight", CFG_PADRAO))
    temp = float(corpo.get("temperature", TEMP_PADRAO))
    chave = (sl, ref.stat().st_mtime_ns, round(exag, 2))
    if _cache["ref"] != chave:                    # prepara a voz uma vez e reaproveita nos blocos seguintes
        tts.prepare_conditionals(str(ref), exaggeration=exag)
        _cache["ref"] = chave
    for b in blocos:
        with torch.inference_mode():
            wav = tts.generate(b, language_id=IDIOMA_TTS, exaggeration=exag, cfg_weight=cfg, temperature=temp)
        saida.append(wav.squeeze(0).float().cpu().numpy())
    return saida, int(tts.sr)


@app.post("/v1/audio/speech")
def falar(corpo: dict):
    texto = str(corpo.get("input") or "").strip()
    voz = str(corpo.get("voice") or "").strip()
    fmt = str(corpo.get("response_format") or "mp3").lower()
    if not texto:
        raise HTTPException(400, "texto vazio")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", voz):
        raise HTTPException(400, "voz inválida: crie uma voz na aba Voz do painel e escolha-a como padrão")
    _tocar()
    ref = DATA / "vozes" / voz / "ref.wav"
    if not ref.exists():
        raise HTTPException(404, f"a voz “{voz}” não existe aqui: grave a amostra na aba Voz do painel")
    try:
        import torch
        with _lock:
            partes, sr = _gerar_blocos(_fatiar(texto[:4000]), voz, ref, corpo)
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    except Exception as e:      # noqa: BLE001
        raise HTTPException(500, f"falha ao gerar a voz: {e}")
    _tocar()
    pausa = np.zeros(int(sr * 0.18), dtype=np.float32)
    partes = [x for p in partes for x in (p, pausa)]
    wav_b = _wav_bytes(np.concatenate(partes), sr)
    if fmt == "wav":
        return Response(wav_b, media_type="audio/wav")
    p = subprocess.run(["ffmpeg", "-v", "error", "-f", "wav", "-i", "-", "-codec:a", "libmp3lame", "-q:a", "3", "-f", "mp3", "-"],
                       input=wav_b, capture_output=True)
    if p.returncode != 0 or not p.stdout:
        raise HTTPException(500, "falha ao converter para mp3")
    return Response(p.stdout, media_type="audio/mpeg")
