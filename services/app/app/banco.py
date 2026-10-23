"""Fonte de imagens de fundo (citações e memes): Higgsfield (imagem gerada por IA) e, como alternativa gratuita, Unsplash."""
import asyncio, random, time, uuid
from pathlib import Path

import httpx

from . import config as C, settings

MAX_ESPERA_S = 180


class BancoError(Exception):
    pass


def higgs_chave() -> str:
    """'ID:SEGREDO' da API do Higgsfield (cabeçalho Authorization: Key ID:SEGREDO)."""
    return settings.segredo("higgs_key")


def disponivel() -> bool:
    """Há de onde tirar imagem? Higgsfield ou Unsplash (com chave) ou o plano B de bases abertas (ligado por padrão em Conexões).
    (Estava fixo em True: com tudo desligado a citação tentava buscar foto e falhava em vez de sair sem foto.)"""
    return bool(higgs_chave() or settings.unsplash_key() or settings.bancos_abertos())


async def _higgs(c: httpx.AsyncClient, consulta: str) -> dict:
    """Gera UMA imagem pela API do Higgsfield (assíncrona: envia, consulta o status até concluir). Gasta créditos da conta."""
    aut = {"Authorization": f"Key {higgs_chave()}"}
    prompt = f"{consulta}, vertical editorial photograph, natural light, no text, no watermark, no logos"
    r = await c.post(f"{C.HIGGS_API_BASE}/higgsfield-ai/soul/v2/standard", json={"prompt": prompt},
                     headers={**aut, "Idempotency-Key": uuid.uuid4().hex})
    if r.status_code in (401, 403):
        raise BancoError("o Higgsfield recusou a chave (confira ID e segredo em Conexões)")
    r.raise_for_status()
    d = r.json()
    st = await _higgs_esperar(c, aut, d, MAX_ESPERA_S)
    imgs = st.get("images") or []
    if imgs and imgs[0].get("url"):
        return {"fonte": "Higgsfield", "autor": "", "link": "", "url": imgs[0]["url"], "ia": True}
    raise BancoError("o Higgsfield concluiu sem devolver imagem")


async def _higgs_esperar(c: httpx.AsyncClient, aut: dict, enviado: dict, espera: float) -> dict:
    """Consulta o status de um pedido do Higgsfield até terminar. Devolve o último status (completed) ou levanta BancoError."""
    status_url = enviado.get("status_url") or f"{C.HIGGS_API_BASE}/requests/{enviado.get('request_id')}/status"
    fim = time.time() + espera
    while time.time() < fim:
        s = (await c.get(status_url, headers=aut)).json()
        st = s.get("status")
        if st == "completed":
            return s
        if st in ("failed", "nsfw", "canceled"):
            raise BancoError(f"o Higgsfield não gerou o resultado (status: {st})")
        await asyncio.sleep(C.HIGGS_POLL_SECONDS)
    raise BancoError("o Higgsfield demorou demais para gerar")


async def animar_foto(imagem_url: str, prompt: str, destino: Path, duracao: int = 5) -> None:
    """Foto -> vídeo curto por IA (Kling 3.0 Turbo, image-to-video, pela API do Higgsfield). A imagem precisa estar numa URL pública.
    Grava o MP4 em destino. Gasta créditos da conta Higgsfield."""
    if not higgs_chave():
        raise BancoError("Higgsfield não configurado (Conexões)")
    aut = {"Authorization": f"Key {higgs_chave()}"}
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
        try:
            r = await c.post(f"{C.HIGGS_API_BASE}/{C.HIGGS_VIDEO_MODEL}", headers={**aut, "Idempotency-Key": uuid.uuid4().hex},
                             json={"prompt": prompt[:2400], "image_url": imagem_url, "duration": max(3, min(int(duracao), 15)), "resolution": "720p"})
            if r.status_code in (401, 403):
                raise BancoError("o Higgsfield recusou a chave (confira ID e segredo em Conexões)")
            if r.status_code == 402:
                raise BancoError("sem créditos no Higgsfield")
            r.raise_for_status()
            st = await _higgs_esperar(c, aut, r.json(), C.HIGGS_VIDEO_ESPERA_S)
            url = (st.get("video") or {}).get("url")
            if not url:
                raise BancoError("o Higgsfield concluiu sem devolver vídeo")
            v = await c.get(url)
            v.raise_for_status()
        except httpx.HTTPError as e:
            raise BancoError(f"falha ao falar com o Higgsfield ({type(e).__name__})")
    if v.content[4:8] != b"ftyp":
        raise BancoError("o Higgsfield devolveu um arquivo que não é vídeo MP4")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(v.content)


async def _unsplash(c: httpx.AsyncClient, consulta: str, orientacao: str) -> list[dict]:
    o = {"portrait": "portrait", "landscape": "landscape", "square": "squarish"}.get(orientacao, "portrait")
    r = await c.get(f"{C.UNSPLASH_API_BASE}/search/photos", headers={"Authorization": f"Client-ID {settings.unsplash_key()}", "Accept-Version": "v1"},
                    params={"query": consulta, "orientation": o, "per_page": 8})
    r.raise_for_status()
    return [{"fonte": "Unsplash", "autor": (f.get("user") or {}).get("name", ""), "link": (f.get("links") or {}).get("html", ""),
             "url": (f.get("urls") or {}).get("regular", ""), "download": (f.get("links") or {}).get("download_location", "")}
            for f in r.json().get("results", []) if (f.get("urls") or {}).get("regular")]


def _normalizar_busca_ingles(consulta: str) -> str:
    """Limpa e traduz termos comuns PT->EN para melhorar a precisão nos bancos globais de imagens."""
    import re
    t = (consulta or "").strip()
    mapa = {
        "inteligência artificial": "artificial intelligence",
        "inteligencia artificial": "artificial intelligence",
        "segurança": "cybersecurity",
        "seguranca": "cybersecurity",
        "dados": "data center technology",
        "automação": "automation technology",
        "automacao": "automation technology",
        "empresa": "modern corporate office",
        "negócios": "business executive",
        "negocios": "business executive",
        "programação": "software developer code",
        "programacao": "software developer code",
        "código": "programming code dark",
        "codigo": "programming code dark",
        "servidor": "server room datacenter",
        "nuvem": "cloud computing server",
        "dinheiro": "finance market trading",
        "finanças": "financial analytics",
        "financas": "financial analytics",
        "produtividade": "modern workspace desk",
        "futuro": "futuristic technology",
        "robô": "robotics artificial intelligence",
        "robo": "robotics artificial intelligence",
    }
    tl = t.lower()
    for pt, en in mapa.items():
        if pt in tl:
            tl = tl.replace(pt, en)
    limpo = re.sub(r"[^\w\s-]", " ", tl)
    palavras = [p for p in limpo.split() if len(p) > 2 and p not in ("para", "com", "como", "sobre", "que", "uma", "dos", "das", "nos", "nas", "por")]
    return " ".join(palavras[:6]) or "modern technology dark aesthetic"


DOMINIOS_BLOQUEADOS_MARCA_DAGUA = (
    "alamy.com", "shutterstock.com", "gettyimages.", "istockphoto.com",
    "123rf.com", "dreamstime.com", "depositphotos.com", "bigstockphoto.com",
    "canstockphoto.com", "pond5.com", "adobestock.com", "ftcdn.net", "freepik.com", "vecteezy.com",
)


async def _bing_contextual_photos(c: httpx.AsyncClient, consulta: str) -> list[dict]:
    """Busca fotografias editoriais reais e contextualizadas ao tema em resolução 4K sem logos/textos de blog."""
    import html
    import re
    termo = _normalizar_busca_ingles(consulta)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
    r = await c.get(
        "https://www.bing.com/images/async",
        params={
            "q": f"{termo} dark aesthetic wallpaper 4k photography",
            "first": 1,
            "count": 30,
            "qft": "+filterui:imagesize-wallpaper+filterui:photo-photo",
        },
        headers=headers,
        timeout=12,
    )
    if r.status_code != 200:
        return []
    murls = [html.unescape(u) for u in re.findall(r"murl&quot;:&quot;(https?://[^&]+?)&quot;", r.text)]
    itens = []
    for u in murls:
        ul = u.lower()
        if any(dom in ul for dom in DOMINIOS_BLOQUEADOS_MARCA_DAGUA):
            continue
        if any(ext in ul for ext in (".jpg", ".jpeg", ".png", ".webp")):
            itens.append({"fonte": "Fotografia Contextual", "autor": "", "link": u, "url": u})
    return itens[:12]


async def _wallhaven(c: httpx.AsyncClient, consulta: str) -> list[dict]:
    """Busca fotografias e fundos editoriais de alta resolução no Wallhaven (API aberta sem chave)."""
    q = _normalizar_busca_ingles(consulta)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    termos_tentativa = [q]
    palavras = q.split()
    if len(palavras) > 1:
        termos_tentativa.append(palavras[0])
    if "technology" not in termos_tentativa:
        termos_tentativa.append("technology")

    dados = []
    for termo in termos_tentativa:
        r = await c.get(
            "https://wallhaven.cc/api/v1/search",
            params={"q": termo, "categories": "100", "purity": "100", "sorting": "relevance", "page": 1},
            headers=headers,
            timeout=10,
        )
        if r.status_code == 200:
            dados = r.json().get("data") or []
            if dados:
                break
    return [
        {"fonte": "Wallhaven", "autor": "", "link": d.get("url", ""), "url": d.get("path", "")}
        for d in dados[:15] if d.get("path")
    ]


async def _wikimedia(c: httpx.AsyncClient, consulta: str) -> list[dict]:
    """Busca fotografias reais no Wikimedia Commons (API aberta sem chave)."""
    q = _normalizar_busca_ingles(consulta)
    headers = {"User-Agent": "ICAPStudio/2.0 (https://github.com/icap; contact@icap.org)"}
    r = await c.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query",
            "generator": "search",
            "gsrsearch": q,
            "gsrnamespace": 6,
            "gsrlimit": 12,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": 1280,
            "format": "json",
        },
        headers=headers,
        timeout=10,
    )
    if r.status_code != 200:
        return []
    pages = (r.json().get("query") or {}).get("pages") or {}
    itens = []
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        url = ii.get("thumburl") or ii.get("url") or ""
        if url and url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) and "icon" not in url.lower() and "logo" not in url.lower():
            itens.append({"fonte": "Wikimedia Commons", "autor": "", "link": ii.get("descriptionurl", ""), "url": url})
    return itens


def _pollinations_url(consulta: str, orientacao: str = "portrait") -> dict:
    """Gera imagem fotográfica sob medida via Pollinations Flux IA (sem chave)."""
    from urllib.parse import quote
    q = _normalizar_busca_ingles(consulta)
    w, h = (1080, 1920) if orientacao == "portrait" else (1080, 1350)
    seed = random.randint(1000, 999999)
    prompt = f"cinematic editorial photography of {q}, dark moody atmosphere"
    url = f"https://image.pollinations.ai/prompt/{quote(prompt)}?width={w}&height={h}&nologo=true&seed={seed}"
    return {"fonte": "Pollinations IA", "autor": "", "link": "", "url": url, "ia": True}


def _picsum_url(orientacao: str = "portrait") -> dict:
    """Fotografia editorial de alta resolução garantida (Picsum)."""
    w, h = (1080, 1920) if orientacao == "portrait" else (1080, 1350)
    seed = random.randint(1000, 999999)
    return {"fonte": "Picsum Editorial", "autor": "", "link": "", "url": f"https://picsum.photos/seed/{seed}/{w}/{h}"}


async def baixar_uma(consulta: str, destino: Path, orientacao: str = "portrait") -> dict:
    """Obtém uma imagem para a consulta, grava em destino e devolve o item (com o crédito).
    Ordem: Higgsfield (se chave) -> Unsplash (se chave) -> Wallhaven / Wikimedia Commons / Pollinations IA (abertos sem chave)."""
    if not disponivel():
        raise BancoError("nenhuma fonte de imagens configurada: cadastre a chave do Higgsfield ou do Unsplash em Conexões (ou ligue o plano B de imagens)")
    item, erro = None, ""
    headers_dl = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=headers_dl) as c:
        if higgs_chave():
            try:
                item = await _higgs(c, consulta)
            except (BancoError, httpx.HTTPError) as e:
                erro = str(e) or type(e).__name__
        if not item and settings.unsplash_key():
            try:
                lista = await _unsplash(c, consulta, orientacao)
                if lista:
                    item = random.choice(lista)
            except Exception as e:
                erro = str(e) or type(e).__name__

        # Bases online abertas (Zero Chave): Bing Fotografia Contextual -> Wikimedia Commons -> Wallhaven
        candidatos_abertos: list[dict] = []
        if not item and settings.bancos_abertos():
            try:
                candidatos_abertos.extend(await _bing_contextual_photos(c, consulta))
            except Exception:
                pass
            if not candidatos_abertos:
                try:
                    candidatos_abertos.extend(await _wikimedia(c, consulta))
                except Exception:
                    pass
            if not candidatos_abertos:
                try:
                    candidatos_abertos.extend(await _wallhaven(c, consulta))
                except Exception:
                    pass
            if candidatos_abertos:
                # Mantém as mais relevantes no topo com leve variação entre as 4 primeiras
                topo = candidatos_abertos[:4]
                random.shuffle(topo)
                candidatos_abertos = topo + candidatos_abertos[4:7]
            candidatos_abertos.append(_picsum_url(orientacao))
            candidatos_abertos.append(_pollinations_url(consulta, orientacao))

        # Tenta baixar o item escolhido ou percorrer os candidatos abertos
        fila_tentativas = [item] if item else candidatos_abertos
        conteudo_valido = None
        item_final = None
        for cand in fila_tentativas:
            if not cand or not cand.get("url"):
                continue
            try:
                r = await c.get(cand["url"], timeout=25)
                if r.status_code != 200:
                    continue
                b = r.content
                if len(b) > 5000 and (b[:2] == b"\xff\xd8" or b[:8] == b"\x89PNG\r\n\x1a\n" or (b[:4] == b"RIFF" and b[8:12] == b"WEBP")):
                    conteudo_valido = b
                    item_final = cand
                    if cand.get("download") and settings.unsplash_key():
                        try:
                            await c.get(cand["download"], headers={"Authorization": f"Client-ID {settings.unsplash_key()}"})
                        except Exception:
                            pass
                    break
            except Exception as e:
                erro = str(e) or type(e).__name__
                continue

        if not conteudo_valido or not item_final:
            raise BancoError("nenhuma imagem encontrada para essa busca" + (f" ({erro})" if erro else ""))

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(conteudo_valido)
    return item_final


def credito(item: dict) -> str:
    if item.get("ia"):
        return f"Imagem gerada por IA ({item.get('fonte', 'IA')})"
    return f"Foto: {item['autor']} · {item['fonte']}" if item.get("autor") else f"Foto: {item['fonte']}"
