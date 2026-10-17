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
    return bool(higgs_chave() or settings.unsplash_key())


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


async def baixar_uma(consulta: str, destino: Path, orientacao: str = "portrait") -> dict:
    """Obtém uma imagem para a consulta, grava em destino e devolve o item (com o crédito). Higgsfield tem prioridade; se falhar e houver Unsplash, usa ele."""
    if not disponivel():
        raise BancoError("nenhuma fonte de imagens configurada: cole a chave do Higgsfield ou do Unsplash em Conexões")
    item, erro = None, ""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        if higgs_chave():
            try:
                item = await _higgs(c, consulta)
            except (BancoError, httpx.HTTPError) as e:
                erro = str(e) or type(e).__name__
                if not settings.unsplash_key():
                    raise BancoError(erro)
        if not item:
            lista = await _unsplash(c, consulta, orientacao)
            if not lista:
                raise BancoError("nenhuma imagem encontrada para essa busca" + (f" ({erro})" if erro else ""))
            item = random.choice(lista)
        r = await c.get(item["url"])
        r.raise_for_status()
        if item.get("download"):  # regra do Unsplash: avisar que a foto foi usada
            try:
                await c.get(item["download"], headers={"Authorization": f"Client-ID {settings.unsplash_key()}"})
            except Exception:
                pass
    b = r.content
    if b[:2] != b"\xff\xd8" and b[:8] != b"\x89PNG\r\n\x1a\n" and not (b[:4] == b"RIFF" and b[8:12] == b"WEBP"):
        raise BancoError("a fonte de imagens devolveu um arquivo que não é imagem")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(b)
    return item


def credito(item: dict) -> str:
    if item.get("ia"):
        return "Imagem gerada por IA (Higgsfield)"
    return f"Foto: {item['autor']} · {item['fonte']}" if item.get("autor") else f"Foto: {item['fonte']}"
