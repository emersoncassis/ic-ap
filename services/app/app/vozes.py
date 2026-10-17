"""Biblioteca de vozes para clonagem: guarda as gravações, limpa o áudio com ffmpeg e monta a amostra de referência
(data/vozes/<nome>/ref.wav) que o servidor de voz lê. A clonagem em si roda FORA do app (services/voz, na GPU)."""
import asyncio, json, re, shutil, time, unicodedata
from pathlib import Path

import httpx

from . import config as C, db, midia

VOZES = C.DATA / "vozes"
REF_MAX_S = 20.0          # os motores usam só os primeiros 10 a 20 s; mais que isso não melhora e deixa a geração mais lenta
REF_IDEAL_S = 10.0
EXT = (".wav", ".mp3", ".m4a", ".ogg", ".oga", ".webm", ".aac", ".flac", ".mp4", ".opus")
MAX_BYTES = 40 * 1024 * 1024
URL_SERVIDOR_LOCAL = "http://voz:8001"        # Chatterbox: nome do serviço no docker-compose (perfil "gpu")
URL_SERVIDOR_QWEN = "http://voz-qwen:8001"    # Qwen3-TTS (perfil "qwen")

TEXTO_LEITURA = (
    "Hoje eu quero contar um pouco da minha história. Eu comecei no suporte técnico, depois viajei o Brasil inteiro "
    "treinando profissionais e, no caminho, mudei a minha saúde por completo. Aprendi que disciplina vale mais do que "
    "motivação e que cuidar do corpo é a base de qualquer carreira. Se você quer mudar, comece pequeno, mas comece hoje. "
    "Uma boa gravação tem voz natural, ritmo calmo e nenhum barulho ao fundo."
)


class VozesError(Exception):
    pass


def slug(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40]


def _dir(sl: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", sl or ""):
        raise VozesError("nome de voz inválido")
    return VOZES / sl


def _meta(sl: str) -> dict | None:
    f = _dir(sl) / "meta.json"
    try:
        return json.loads(f.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _salvar(sl: str, m: dict) -> None:
    (_dir(sl) / "meta.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), "utf-8")


def padrao() -> str:
    return db.get_setting("tts_voz").strip()


def listar() -> list[dict]:
    VOZES.mkdir(parents=True, exist_ok=True)
    out = []
    for d in sorted(VOZES.iterdir()):
        m = _meta(d.name) if d.is_dir() else None
        if m:
            m["pronta"] = (d / "ref.wav").exists()
            m["padrao"] = d.name == padrao()
            m["texto_ref"] = texto_ref(d.name)
            out.append(m)
    return out


def obter(sl: str) -> dict | None:
    m = _meta(sl)
    if m:
        m["pronta"] = (_dir(sl) / "ref.wav").exists()
        m["padrao"] = sl == padrao()
        m["texto_ref"] = texto_ref(sl)
    return m


async def _ffmpeg(*args: str) -> str:
    """Roda o ffmpeg e devolve o stderr (onde saem os relatórios de volumedetect)."""
    p = await asyncio.create_subprocess_exec("ffmpeg", "-hide_banner", "-y", *args,
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await p.communicate()
    txt = err.decode(errors="ignore")
    if p.returncode != 0:
        raise VozesError(f"não consegui ler o áudio ({txt.strip()[-200:]})")
    return txt


async def _volume(arq: Path) -> tuple[float, float]:
    """(pico, média) em dB."""
    txt = await _ffmpeg("-i", str(arq), "-vn", "-af", "volumedetect", "-f", "null", "-")
    mx = re.search(r"max_volume:\s*(-?[\d.]+) dB", txt)
    me = re.search(r"mean_volume:\s*(-?[\d.]+) dB", txt)
    return (float(mx.group(1)) if mx else -91.0, float(me.group(1)) if me else -91.0)


# Limpeza LEVE (padrão): só corta o silêncio das pontas e ajusta o volume. Não usa redução de ruído nem compressão:
# esses processamentos deixam artefatos que o modelo copia, e o clone fica com timbre artificial.
_PONTAS = "silenceremove=start_periods=1:start_duration=0.1:start_threshold=-50dB:start_silence=0.12"
_LEVE = f"highpass=f=60,{_PONTAS},areverse,{_PONTAS},areverse"
# Limpeza FORTE (para gravação ruim, com chiado): reduz ruído, tira pausas longas e nivela o volume.
_FORTE = ("highpass=f=80,afftdn=nf=-28,"
          "silenceremove=start_periods=1:start_duration=0.1:start_threshold=-45dB:"
          "stop_periods=-1:stop_duration=0.8:stop_threshold=-45dB,"
          "loudnorm=I=-20:TP=-2:LRA=11")


async def _limpar(bruto: Path, dest: Path, pico_db: float, modo: str = "leve") -> float:
    # gravação baixa: sobe o volume ANTES de cortar silêncios, senão a fala some junto com o limite do detector
    ganho = min(max(-3.0 - pico_db, 0.0), 40.0) if pico_db > -90 else 0.0
    filtro, hz = (_FORTE, "24000") if modo == "forte" else (_LEVE, "44100")
    await _ffmpeg("-i", str(bruto), "-vn", "-af", f"volume={ganho:.1f}dB,{filtro}", "-ac", "1", "-ar", hz, "-c:a", "pcm_s16le", str(dest))
    return (await midia.sondar(dest))["duracao"]


async def _montar_ref(sl: str, m: dict) -> None:
    """Junta as gravações limpas em ref.wav (até REF_MAX_S) e calcula os avisos de qualidade."""
    d = _dir(sl)
    limpos = [d / "limpos" / t["limpo"] for t in m["takes"] if (d / "limpos" / t["limpo"]).exists()]
    if not limpos:
        (d / "ref.wav").unlink(missing_ok=True)
        m["dur_ref"], m["avisos"] = 0.0, ["Sem gravações."]
        return
    lista = d / "lista.txt"
    lista.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in limpos), "utf-8")
    tmp = d / "ref_tmp.wav"
    await _ffmpeg("-f", "concat", "-safe", "0", "-i", str(lista), "-t", str(REF_MAX_S), "-c:a", "pcm_s16le", str(tmp))
    lista.unlink(missing_ok=True)
    tmp.replace(d / "ref.wav")
    (d / "ref.txt").unlink(missing_ok=True)       # a transcrição antiga não vale mais
    m["dur_ref"] = round((await midia.sondar(d / "ref.wav"))["duracao"], 1)
    av = []
    if m["dur_ref"] < 6:
        av.append(f"Só {m['dur_ref']:.0f} s de fala útil: grave pelo menos 10 s (ideal 10 a 20 s).")
    elif m["dur_ref"] < REF_IDEAL_S:
        av.append(f"{m['dur_ref']:.0f} s de fala: funciona, mas fica melhor com 10 a 20 s.")
    if any(t["pico_db"] > -0.5 for t in m["takes"]):
        av.append("Alguma gravação estourou (volume no máximo): grave de novo mais longe do microfone.")
    if any(t["media_db"] < -38 for t in m["takes"]):
        av.append("Alguma gravação está baixa demais: chegue mais perto do microfone.")
    m["avisos"] = av


async def adicionar(nome: str, dados: bytes, nome_arquivo: str, *, dono: str = "propria", autor: str = "", consentimento: bool = False) -> dict:
    """Cria a voz (se nova) ou acrescenta uma gravação; reprocessa e devolve os metadados."""
    sl = slug(nome)
    if not sl:
        raise VozesError("dê um nome para a voz")
    ext = Path(nome_arquivo or "").suffix.lower()
    if ext not in EXT:
        raise VozesError("formato não aceito (use wav, mp3, m4a, ogg, webm, aac, flac)")
    if not dados or len(dados) > MAX_BYTES:
        raise VozesError("arquivo vazio ou maior que 40 MB")
    d = _dir(sl)
    m = _meta(sl)
    if m is None:
        if not consentimento:
            raise VozesError("confirme que a voz é sua ou que a pessoa autorizou o uso")
        if dono == "outra" and not autor.strip():
            raise VozesError("diga de quem é a voz")
        m = {"slug": sl, "nome": nome.strip()[:60], "dono": "outra" if dono == "outra" else "propria", "autor": autor.strip()[:80],
             "consentimento": True, "criado": time.strftime("%Y-%m-%d %H:%M"), "takes": [], "limpeza": "leve"}
    for sub in ("brutos", "limpos"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    n = len(m["takes"]) + 1
    bruto = d / "brutos" / f"{n:02d}{ext}"
    bruto.write_bytes(dados)
    limpo = f"{n:02d}.wav"
    try:
        pico, media = await _volume(bruto)
        dur = await _limpar(bruto, d / "limpos" / limpo, pico, m.get("limpeza", "leve"))
        if dur < 1.5:
            raise VozesError("quase não há fala nessa gravação (só silêncio ou ruído)")
    except Exception:
        bruto.unlink(missing_ok=True)
        (d / "limpos" / limpo).unlink(missing_ok=True)
        if not m["takes"]:
            shutil.rmtree(d, ignore_errors=True)
        raise
    m["takes"].append({"n": n, "bruto": bruto.name, "limpo": limpo, "dur": round(dur, 1), "pico_db": pico, "media_db": media})
    await _montar_ref(sl, m)
    _salvar(sl, m)
    await transcrever_ref(sl)
    return obter(sl)


async def remover_take(sl: str, n: int) -> dict | None:
    m = _meta(sl)
    if not m:
        return None
    d = _dir(sl)
    resto = [t for t in m["takes"] if t["n"] != n]
    for t in m["takes"]:
        if t["n"] == n:
            (d / "brutos" / t["bruto"]).unlink(missing_ok=True)
            (d / "limpos" / t["limpo"]).unlink(missing_ok=True)
    m["takes"] = resto
    await _montar_ref(sl, m)
    _salvar(sl, m)
    await transcrever_ref(sl)
    return obter(sl)


async def reprocessar(sl: str, modo: str) -> dict | None:
    """Refaz a limpeza de todas as gravações originais no modo "leve" ou "forte"."""
    m = _meta(sl)
    if not m:
        return None
    modo = "forte" if modo == "forte" else "leve"
    d = _dir(sl)
    novos = []
    for t in m["takes"]:
        bruto = d / "brutos" / t["bruto"]
        if not bruto.exists():
            continue
        pico, media = await _volume(bruto)
        dur = await _limpar(bruto, d / "limpos" / t["limpo"], pico, modo)
        novos.append({**t, "dur": round(dur, 1), "pico_db": pico, "media_db": media})
    m["takes"], m["limpeza"] = novos, modo
    await _montar_ref(sl, m)
    _salvar(sl, m)
    await transcrever_ref(sl)
    return obter(sl)


def texto_ref(sl: str) -> str:
    try:
        return (_dir(sl) / "ref.txt").read_text("utf-8").strip()
    except OSError:
        return ""


def salvar_texto_ref(sl: str, texto: str) -> None:
    if not obter(sl):
        raise VozesError("voz não encontrada")
    (_dir(sl) / "ref.txt").write_text(re.sub(r"\s+", " ", texto).strip()[:2000], "utf-8")


async def transcrever_ref(sl: str) -> None:
    """Transcreve a amostra com o Whisper (se configurado) e guarda em ref.txt. Alguns motores (Qwen3) usam esse texto
    para clonar melhor; o usuário pode corrigi-lo na tela. Falhas são ignoradas."""
    from . import voz
    f = ref_path(sl)
    if not f or not voz.whisper_ok():
        return
    try:
        palavras = await voz.transcrever(f)
    except voz.VozError:
        return
    txt = " ".join(w["w"] for w in palavras).strip()
    if txt:
        salvar_texto_ref(sl, txt)


def ajustes_de(sl: str) -> dict:
    """Ajustes de geração salvos para a voz (cfg_weight, exaggeration, temperature). Vazio = padrão do servidor."""
    try:
        m = _meta(sl)
    except VozesError:
        return {}
    return dict((m or {}).get("ajustes") or {})


def definir_ajustes(sl: str, cfg: float | None, exag: float | None, temp: float | None) -> dict:
    m = _meta(sl)
    if not m:
        raise VozesError("voz não encontrada")
    lim = lambda v, a, b: None if v is None else round(min(max(float(v), a), b), 2)
    aj = {k: v for k, v in (("cfg_weight", lim(cfg, 0.0, 1.0)), ("exaggeration", lim(exag, 0.0, 1.5)), ("temperature", lim(temp, 0.1, 1.5))) if v is not None}
    m["ajustes"] = aj
    _salvar(sl, m)
    return aj


def excluir(sl: str) -> None:
    d = _dir(sl)
    if padrao() == sl:
        db.set_setting("tts_voz", "")
    shutil.rmtree(d, ignore_errors=True)


def definir_padrao(sl: str) -> None:
    m = obter(sl)
    if not m or not m["pronta"]:
        raise VozesError("essa voz ainda não tem amostra pronta")
    db.set_setting("tts_voz", sl)


def ref_path(sl: str) -> Path | None:
    f = _dir(sl) / "ref.wav"
    return f if f.exists() else None


async def estado_servidor() -> dict:
    """Pergunta ao servidor de voz (rota /health) se ele está de pé e se usa a GPU. Nunca levanta erro."""
    url = db.get_setting("tts_url").strip().rstrip("/")
    if not url:
        return {"configurado": False}
    base = url[:-3] if url.endswith("/v1") else url
    try:
        async with httpx.AsyncClient(timeout=3) as cli:
            r = await cli.get(f"{base}/health")
        if r.status_code == 200 and isinstance(r.json(), dict):
            return {"configurado": True, "ok": True, "url": url, **r.json()}
        return {"configurado": True, "ok": True, "url": url, "generico": True}   # outro servidor (sem /health nosso)
    except (httpx.HTTPError, ValueError):
        return {"configurado": True, "ok": False, "url": url}


async def descarregar_servidor() -> None:
    """Pede ao servidor de voz para tirar os modelos da memória da placa (voltam sozinhos no próximo uso)."""
    url = db.get_setting("tts_url").strip().rstrip("/")
    if not url:
        raise VozesError("servidor de voz não configurado")
    base = url[:-3] if url.endswith("/v1") else url
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.post(f"{base}/descarregar")
    except httpx.HTTPError as e:
        raise VozesError(f"não consegui falar com o servidor de voz ({type(e).__name__})")
    if r.status_code == 404:
        raise VozesError("esse servidor não tem a função de descarregar (só o servidor de voz do ic-ap tem)")
    if r.status_code >= 400:
        try:
            msg = r.json().get("detail", "")
        except ValueError:
            msg = ""
        raise VozesError(msg or f"o servidor respondeu HTTP {r.status_code}")
