"""Leitura de RSS, filtro e extração do texto da matéria."""
import asyncio
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser
import httpx
import trafilatura

MAX_CHARS = 6000
UA = {"User-Agent": "Mozilla/5.0 (compatible; ic-ap/1.0)"}


async def ler_feed(url: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=UA) as c:
        r = await c.get(url)
        r.raise_for_status()
    parsed = feedparser.parse(r.content)
    itens = []
    for e in parsed.entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        data = datetime.fromtimestamp(mktime(t), tz=timezone.utc) if t else datetime.now(timezone.utc)
        itens.append({"titulo": e.get("title", "").strip(), "url": e.get("link", ""), "data": data,
                      "resumo": e.get("summary", "")})
    return itens


def pontuar(item: dict, palavras: list[str]) -> int:
    txt = f"{item['titulo']} {item['resumo']}".lower()
    return sum(1 for p in palavras if p and p.lower() in txt)


async def candidatas(feeds: list[dict], palavras: list[str], max_idade_h: int, ja_usadas: set[str]) -> list[dict]:
    corte = datetime.now(timezone.utc) - timedelta(hours=max_idade_h)
    res = []
    for f in feeds:
        try:
            for it in await ler_feed(f["url"]):
                if not it["url"] or it["url"] in ja_usadas or it["data"] < corte:
                    continue
                s = pontuar(it, palavras)
                if palavras and s == 0:
                    continue
                res.append({**it, "fonte": f["nome"], "score": s})
        except Exception:
            continue  # um feed quebrado não derruba os outros
    res.sort(key=lambda i: (i["score"], i["data"]), reverse=True)
    return res


async def extrair(url: str) -> dict:
    def _run():
        html = trafilatura.fetch_url(url)
        if not html:
            raise ValueError("não consegui baixar a página")
        d = trafilatura.bare_extraction(html, url=url, with_metadata=True)
        if not d or not getattr(d, "text", None):
            raise ValueError("sem texto extraível")
        return {"titulo": d.title or "", "fonte": d.sitename or d.hostname or "", "texto": d.text[:MAX_CHARS]}
    return await asyncio.to_thread(_run)
