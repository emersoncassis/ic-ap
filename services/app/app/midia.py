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


async def miniatura_b64(src: Path, lado: int = 1024) -> str:
    """Foto reduzida (JPEG, maior lado = `lado`) em base64, para o modelo de visão."""
    import base64
    tmp = C.DATA / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    out = tmp / f"{uuid.uuid4().hex}.jpg"
    try:
        await _run("ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"scale='min({lado},iw)':'min({lado},ih)':force_original_aspect_ratio=decrease",
                   "-frames:v", "1", "-q:v", "4", str(out))
        return base64.b64encode(out.read_bytes()).decode()
    finally:
        out.unlink(missing_ok=True)


async def quadro(src: Path, segundo: float) -> Path:
    """Um quadro do vídeo (JPEG em data/tmp). Quem chama apaga."""
    tmp = C.DATA / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    out = tmp / f"{uuid.uuid4().hex}.jpg"
    await _run("ffmpeg", "-y", "-v", "error", "-ss", f"{max(segundo, 0):.2f}", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(out))
    if not out.exists():
        raise MidiaError("não consegui tirar um quadro do vídeo")
    return out


async def trilha_padrao() -> Path:
    """Trilha instrumental suave gerada aqui mesmo (sem direitos autorais), usada quando não há músicas na aba Músicas.
    Fica em data/trilha_padrao.m4a e é criada na primeira vez."""
    alvo = C.DATA / "trilha_padrao.m4a"
    if alvo.exists() and alvo.stat().st_size > 1000:
        return alvo
    # acorde Am9 → Fmaj7 → C → G em pads de senoides, com batida leve de grave; 4 x 8 s = 32 s, em loop
    acordes = [(110.0, 220.0, 261.63, 329.63, 493.88), (87.31, 174.61, 261.63, 329.63, 440.0),
               (130.81, 196.0, 261.63, 329.63, 392.0), (98.0, 196.0, 246.94, 293.66, 392.0)]
    entradas, filtros = [], []
    for i, ac in enumerate(acordes):
        expr = "+".join(f"{0.16 / (1 + 0.5 * k):.3f}*sin(2*PI*{f}*t)" for k, f in enumerate(ac))
        entradas += ["-f", "lavfi", "-t", "8", "-i", f"aevalsrc={expr}:s=44100"]
        filtros.append(f"[{i}:a]afade=t=in:d=1.5,afade=t=out:st=6.5:d=1.5,lowpass=f=1800,aecho=0.8:0.6:380:0.35[c{i}]")
    fc = ";".join(filtros) + ";" + "".join(f"[c{i}]" for i in range(4)) + "concat=n=4:v=0:a=1,tremolo=f=0.4:d=0.25,volume=1.2[a]"
    tmp = alvo.with_suffix(".tmp.m4a")
    try:
        await _run("ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", fc, "-map", "[a]", "-c:a", "aac", "-b:a", "128k", str(tmp))
        tmp.replace(alvo)
    finally:
        tmp.unlink(missing_ok=True)
    return alvo


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
    fv = ("[0:v]split[a][b];[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=6:2,scale=1080:1920[bg];"
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


async def adaptar(arquivo: str, formato: str) -> str:
    """Refaz uma imagem pronta em outro formato (feed 1080x1350 ou story 1080x1920) sem cortar nada:
    a imagem inteira fica no centro e o fundo é a própria imagem ampliada e borrada. Devolve o novo arquivo em CARDS."""
    if not arquivo.endswith(".jpg"):
        raise MidiaError("só dá para adaptar imagens (vídeos já saem em 9:16)")
    w, h = (1080, 1920) if formato == "story" else (1080, 1350)
    nome = f"{uuid.uuid4().hex}.jpg"
    fc = (f"[0:v]split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=30:6[bg];"
          f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    await _run("ffmpeg", "-y", "-v", "error", "-i", str(C.CARDS / arquivo), "-filter_complex", fc, "-frames:v", "1", "-q:v", "3", str(C.CARDS / nome))
    return nome


# ---------------- vídeo: corte de silêncio, legendas animadas, narração ----------------
async def cortar_silencio(src: Path, limiar_db: int = -32, minimo: float = 0.5, margem: float = 0.15) -> tuple[Path, float]:
    """Remove as pausas (silêncio acima de 'minimo' s) e junta os trechos falados, deixando uma margem para não cortar a fala.
    Devolve (arquivo_novo_em_tmp, segundos_removidos). Se não há o que cortar, devolve o próprio src e 0."""
    info = await sondar(src)
    if not info["video"] or not info["audio"]:
        raise MidiaError("para cortar silêncio o vídeo precisa ter áudio")
    p = await asyncio.create_subprocess_exec("ffmpeg", "-nostats", "-i", str(src), "-af", f"silencedetect=noise={limiar_db}dB:d={minimo}",
                                             "-f", "null", "-", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await p.communicate()
    log = err.decode(errors="ignore")
    inicios = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    fins = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    total = info["duracao"]
    if len(fins) < len(inicios):  # silêncio que vai até o fim do vídeo
        fins.append(total)
    manter, cursor = [], 0.0
    for a, b in zip(inicios, fins):
        a = max(a, 0.0)
        ini_corte, fim_corte = a + margem, b - margem
        if fim_corte - ini_corte < 0.2:
            continue
        if ini_corte > cursor:
            manter.append((cursor, ini_corte))
        cursor = fim_corte
    if cursor < total:
        manter.append((cursor, total))
    manter = [(a, b) for a, b in manter if b - a > 0.15]
    removido = total - sum(b - a for a, b in manter)
    if not manter or removido < 0.3:
        return src, 0.0
    partes = "".join(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}];[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}];"
                     for i, (a, b) in enumerate(manter))
    juntar = "".join(f"[v{i}][a{i}]" for i in range(len(manter))) + f"concat=n={len(manter)}:v=1:a=1[v][a]"
    dest = C.DATA / "tmp" / f"{uuid.uuid4().hex}.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    await _run("ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex", partes + juntar, "-map", "[v]", "-map", "[a]",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-c:a", "aac", "-b:a", "160k", str(dest))
    return dest, removido


def _ass_cor(hexa: str) -> str:
    h = hexa.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _ass_tempo(t: float) -> str:
    t = max(t, 0.0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _ass_texto(w: str) -> str:
    return re.sub(r"[{}\\]", "", w).upper()


def montar_ass(palavras: list[dict], destaque: str = "#ffd166", max_palavras: int = 3, max_chars: int = 20) -> str:
    """Legenda estilo 'karaokê' para vídeo vertical 1080x1920: poucas palavras por vez, a palavra falada em destaque."""
    blocos, atual = [], []
    for w in palavras:
        if atual and (len(atual) >= max_palavras or sum(len(x["w"]) + 1 for x in atual) + len(w["w"]) > max_chars):
            blocos.append(atual)
            atual = []
        atual.append(w)
    if atual:
        blocos.append(atual)
    cab = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n\n[V4+ Styles]\n"
           "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,"
           "Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
           "Style: Base,DejaVu Sans,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,2,60,60,520,1\n\n"
           "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    acento = _ass_cor(destaque)
    linhas = []
    for b, bloco in enumerate(blocos):
        proximo = blocos[b + 1][0]["ini"] if b + 1 < len(blocos) else None
        for i, w in enumerate(bloco):
            ini = w["ini"]
            fim = bloco[i + 1]["ini"] if i + 1 < len(bloco) else max(w["fim"], w["ini"] + 0.25)
            if proximo is not None and i + 1 == len(bloco):
                fim = min(fim, proximo)  # uma legenda some quando a próxima entra
            fim = max(fim, ini + 0.08)
            texto = " ".join((f"{{\\c{acento}}}{_ass_texto(x['w'])}{{\\c&H00FFFFFF&}}" if j == i else _ass_texto(x["w"])) for j, x in enumerate(bloco))
            linhas.append(f"Dialogue: 0,{_ass_tempo(ini)},{_ass_tempo(fim)},Base,,0,0,0,,{texto}")
    return cab + "\n".join(linhas) + "\n"


async def legendar(arquivo: str, palavras: list[dict], destaque: str = "#ffd166") -> str:
    """Grava as legendas animadas no vídeo (1080x1920) já pronto em CARDS. Devolve o novo arquivo; o antigo fica para quem chamou apagar."""
    if not palavras:
        raise MidiaError("sem palavras para legendar")
    ass = C.DATA / "tmp" / f"{uuid.uuid4().hex}.ass"
    ass.parent.mkdir(parents=True, exist_ok=True)
    ass.write_text(montar_ass(palavras, destaque), encoding="utf-8")
    nome = f"{uuid.uuid4().hex}.mp4"
    try:
        await _run("ffmpeg", "-y", "-v", "error", "-i", str(C.CARDS / arquivo), "-vf", f"ass='{ass.as_posix().replace(':', chr(92) + ':')}'", "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "22", "-c:a", "copy", "-movflags", "+faststart", str(C.CARDS / nome))
    finally:
        ass.unlink(missing_ok=True)
    return nome


async def misturar_voz(voz: Path, musica: Path | None, extra_fim: float = 1.0) -> tuple[Path, float]:
    """Áudio final da narração: a voz inteira (com 'extra_fim' s de respiro) e, se houver, a trilha baixinha por baixo. Devolve (arquivo, duração)."""
    dur = (await sondar(voz))["duracao"] + extra_fim
    dest = C.DATA / "tmp" / f"{uuid.uuid4().hex}.m4a"
    args = ["ffmpeg", "-y", "-v", "error", "-i", str(voz)]
    if musica:
        args += ["-stream_loop", "-1", "-i", str(musica), "-filter_complex",
                 f"[0:a]apad=pad_dur={extra_fim}[v];[1:a]volume=0.16,afade=t=out:st={max(dur - 1.2, 0):.2f}:d=1.2[m];[v][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
                 "-map", "[a]"]
    else:
        args += ["-af", f"apad=pad_dur={extra_fim}"]
    args += ["-t", f"{dur:.2f}", "-c:a", "aac", "-b:a", "160k", str(dest)]
    await _run(*args)
    return dest, dur


async def preparar_publico(src: Path, nome: str) -> Path:
    """Cópia JPEG (até 1080 de largura) da imagem em PUBLIC, para o Higgsfield buscar pela URL pública. Quem chama apaga depois."""
    C.PUBLIC.mkdir(parents=True, exist_ok=True)
    dest = C.PUBLIC / nome
    await _run("ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", "scale='min(1080,iw)':-2", "-frames:v", "1", "-q:v", "3", str(dest))
    return dest
