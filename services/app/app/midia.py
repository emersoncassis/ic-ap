"""Fotos e vídeos enviados pelo Telegram: ajuste de formato e trilha musical com ffmpeg (tudo local)."""
import asyncio, json, random, re, uuid
from pathlib import Path

from . import config as C

EXT_MUSICA = (".mp3", ".m4a", ".wav", ".ogg", ".aac")
MAX_REEL_S, MAX_STORY_S = 90, 60


class MidiaError(Exception):
    pass


async def _run(*args: str) -> str:
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await p.communicate()
    if p.returncode != 0:
        raise MidiaError(f"{args[0]} falhou: {err.decode(errors='ignore')[-300:]}")
    return out.decode()


async def sondar(arq: Path) -> dict:
    d = json.loads(await _run("ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(arq)))
    return {"duracao": float(d.get("format", {}).get("duration") or 0),
            "audio": any(s.get("codec_type") == "audio" for s in d.get("streams", [])),
            "video": any(s.get("codec_type") == "video" for s in d.get("streams", []))}


def musicas() -> list[Path]:
    C.MUSICAS.mkdir(parents=True, exist_ok=True)
    return sorted(p for p in C.MUSICAS.iterdir() if p.suffix.lower() in EXT_MUSICA)


def escolher_musica() -> Path | None:
    lista = musicas()
    return random.choice(lista) if lista else None


def nome_seguro(nome: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(nome).name).strip(" .") or "musica"
    return base[:80]


async def foto(src: Path, formato: str) -> str:
    """Corta a foto para 4:5 (feed) ou 9:16 (story), em JPEG 1080 de largura. Devolve o nome do arquivo em CARDS."""
    w, h = (1080, 1920) if formato == "story" else (1080, 1350)
    nome = f"{uuid.uuid4().hex}.jpg"
    await _run("ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf",
               f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}", "-frames:v", "1", "-q:v", "3",
               str(C.CARDS / nome))
    return nome


def _entrada_overlay(args: list[str], overlay: str | None) -> int:
    """Acrescenta o PNG como entrada em loop (para o fade funcionar). Devolve o índice da próxima entrada livre."""
    if overlay:
        args += ["-loop", "1", "-i", overlay]
        return 2
    return 1


def _fade_overlay(idx: int, de: str, para: str) -> str:
    return f"[{idx}:v]format=rgba,fade=t=in:st=0.8:d=0.8:alpha=1[ov];[{de}][ov]overlay=0:0:format=auto,format=yuv420p[{para}]"


async def video(src: Path, formato: str, musica: Path | None = None, overlay: str | None = None) -> str:
    """Vídeo vertical 1080x1920 H.264/AAC (fundo borrado se a proporção for outra), com trilha e texto na tela opcionais.
    Com áudio original: a trilha entra baixa por baixo da voz. Sem áudio: a trilha toca sozinha."""
    info = await sondar(src)
    if not info["video"]:
        raise MidiaError("o arquivo não tem vídeo")
    limite = MAX_STORY_S if formato == "story" else MAX_REEL_S
    dur = min(info["duracao"] or limite, limite)
    nome = f"{uuid.uuid4().hex}.mp4"
    fv = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg];"
          "[b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[" + ("v0" if overlay else "v") + "]")
    args = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    prox = _entrada_overlay(args, overlay)
    if overlay:
        fv += ";" + _fade_overlay(1, "v0", "v")
    if musica:
        args += ["-stream_loop", "-1", "-i", str(musica)]
        fade = f"afade=t=out:st={max(dur - 1.5, 0):.2f}:d=1.5"
        fa = (f"[0:a]volume=1.0[a0];[{prox}:a]volume=0.22,{fade}[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[a]"
              if info["audio"] else f"[{prox}:a]volume=0.85,{fade}[a]")
        args += ["-filter_complex", f"{fv};{fa}", "-map", "[v]", "-map", "[a]"]
    else:
        args += ["-filter_complex", fv, "-map", "[v]"]
        args += ["-map", "0:a"] if info["audio"] else []
    args += ["-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-r", "30",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(C.CARDS / nome)]
    await _run(*args)
    return nome


async def story_animado(src: Path, musica: Path | None = None, overlay: str | None = None, dur: float = 7.0) -> str:
    """Foto -> Story em vídeo 1080x1920: zoom suave (efeito Ken Burns), texto que aparece com fade e trilha com fade."""
    nome = f"{uuid.uuid4().hex}.mp4"
    quadros = int(dur * 30)
    fv = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,scale=2160:3840,"
          f"zoompan=z='1+0.0006*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={quadros}:s=1080x1920:fps=30,"
          "format=yuv420p[" + ("v0" if overlay else "v") + "]")
    args = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    prox = _entrada_overlay(args, overlay)
    if overlay:
        fv += ";" + _fade_overlay(1, "v0", "v")
    if musica:
        args += ["-stream_loop", "-1", "-i", str(musica)]
        fv += f";[{prox}:a]volume=0.85,afade=t=in:d=0.6,afade=t=out:st={max(dur - 1.5, 0):.2f}:d=1.5[a]"
    args += ["-filter_complex", fv, "-map", "[v]"] + (["-map", "[a]"] if musica else [])
    args += ["-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-r", "30",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(C.CARDS / nome)]
    await _run(*args)
    return nome


async def sobrepor(jpg: str, overlay: str) -> str:
    """Texto sobre a imagem estática (Story sem animação). Troca o arquivo: apaga o original e devolve o novo."""
    nome = f"{uuid.uuid4().hex}.jpg"
    await _run("ffmpeg", "-y", "-v", "error", "-i", str(C.CARDS / jpg), "-i", overlay, "-filter_complex", "overlay=0:0",
               "-frames:v", "1", "-q:v", "2", str(C.CARDS / nome))
    (C.CARDS / jpg).unlink(missing_ok=True)
    return nome
