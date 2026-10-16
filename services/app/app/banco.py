"""Banco de imagens gratuito (Pexels e Unsplash). Cada um pede uma chave de API gratuita, configurada em Conexões."""
import random
from pathlib import Path

import httpx

from . import config as C, settings

ORIENT = {"portrait": ("portrait", "portrait"), "landscape": ("landscape", "landscape"), "square": ("square", "squarish")}


class BancoError(Exception):
    pass


def disponivel() -> bool:
    return bool(settings.pexels_key() or settings.unsplash_key())


async def buscar(consulta: str, orientacao: str = "portrait", n: int = 8) -> list[dict]:
    """Fotos para a consulta (de preferência em inglês). Cada item: fonte, autor, link, url (e download_location do Unsplash)."""
    if not disponivel():
        raise BancoError("nenhum banco de imagens configurado: cole a chave do Pexels ou do Unsplash em Conexões")
    o_px, o_un = ORIENT.get(orientacao, ORIENT["portrait"])
    itens: list[dict] = []
    erros: list[str] = []
    async with httpx.AsyncClient(timeout=30) as c:
        if settings.pexels_key():
            try:
                r = await c.get(f"{C.PEXELS_API_BASE}/v1/search", headers={"Authorization": settings.pexels_key()},
                                params={"query": consulta, "orientation": o_px, "per_page": n, "locale": "pt-BR"})
                r.raise_for_status()
                itens += [{"fonte": "Pexels", "autor": f.get("photographer", ""), "link": f.get("url", ""),
                           "url": (f.get("src") or {}).get("large2x") or (f.get("src") or {}).get("large", "")}
                          for f in r.json().get("photos", [])]
            except Exception as e:
                erros.append(f"Pexels: {type(e).__name__}")
        if settings.unsplash_key():
            try:
                r = await c.get(f"{C.UNSPLASH_API_BASE}/search/photos", headers={"Authorization": f"Client-ID {settings.unsplash_key()}", "Accept-Version": "v1"},
                                params={"query": consulta, "orientation": o_un, "per_page": n})
                r.raise_for_status()
                itens += [{"fonte": "Unsplash", "autor": (f.get("user") or {}).get("name", ""), "link": (f.get("links") or {}).get("html", ""),
                           "url": (f.get("urls") or {}).get("regular", ""), "download": (f.get("links") or {}).get("download_location", "")}
                          for f in r.json().get("results", [])]
            except Exception as e:
                erros.append(f"Unsplash: {type(e).__name__}")
    itens = [i for i in itens if i["url"]]
    if not itens:
        raise BancoError("nenhuma imagem encontrada para essa busca" + (f" ({'; '.join(erros)})" if erros else ""))
    return itens


async def baixar_uma(consulta: str, destino: Path, orientacao: str = "portrait") -> dict:
    """Escolhe uma das fotos da busca, grava em destino (JPEG/PNG) e devolve o item (com o crédito)."""
    item = random.choice(await buscar(consulta, orientacao))
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        r = await c.get(item["url"])
        r.raise_for_status()
        if item.get("download"):  # regra do Unsplash: avisar que a foto foi usada
            try:
                await c.get(item["download"], headers={"Authorization": f"Client-ID {settings.unsplash_key()}"})
            except Exception:
                pass
    if r.content[:2] != b"\xff\xd8" and r.content[:8] != b"\x89PNG\r\n\x1a\n":
        raise BancoError("o banco de imagens devolveu um arquivo que não é imagem")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(r.content)
    return item


def credito(item: dict) -> str:
    return f"Foto: {item['autor']} · {item['fonte']}" if item.get("autor") else f"Foto: {item['fonte']}"
