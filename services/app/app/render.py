"""Render do card: HTML -> JPEG 1080x1350 via Chromium (Playwright)."""
import re, uuid

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

from . import config as C, marca as M

_state: dict = {}


async def start() -> None:
    _state["pw"] = await async_playwright().start()
    _state["browser"] = await _state["pw"].chromium.launch(executable_path=C.CHROMIUM, args=["--no-sandbox"])


async def stop() -> None:
    if _state.get("browser"):
        await _state["browser"].close()
        await _state["pw"].stop()


async def print_pagina(url: str) -> str | None:
    """Print do topo da matéria (1080x760) como data URI. None se a página não carregar."""
    import base64
    page = await _state["browser"].new_page(viewport={"width": 1080, "height": 760})
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(800)
        return "data:image/jpeg;base64," + base64.b64encode(await page.screenshot(type="jpeg", quality=80)).decode()
    except Exception:
        return None
    finally:
        await page.close()


async def card(manchete: str, reacao: str, fonte: str, handle: str, nome: str,
               formato: str = "feed", print_uri: str | None = None, p: dict | None = None) -> tuple[str, bool]:
    """Devolve (nome_do_arquivo, texto_estourou). O arquivo fica em CARDS (privado).
    formato 'story' usa 1080x1920 (reacao_story.html)."""
    story = formato == "story"
    env = Environment(loader=FileSystemLoader(str(C.CARD_TEMPLATES)), autoescape=select_autoescape(["html"]))
    paragrafos = [p.strip() for p in re.split(r"\n\s*\n|\n", reacao) if p.strip()]
    html = env.get_template("reacao_story.html" if story else "reacao.html").render(
        manchete=manchete, paragrafos=paragrafos, fonte=fonte, handle=handle, nome=nome, print_uri=print_uri, **M.contexto(p))
    name = f"{uuid.uuid4().hex}.jpg"
    page = await _state["browser"].new_page(viewport={"width": 1080, "height": 1920 if story else 1350})
    try:
        await page.set_content(html, wait_until="load")
        estourou = await page.evaluate(
            "() => { const b = document.querySelector('.body'); return b.scrollHeight > b.clientHeight + 2 }")
        await page.screenshot(path=str(C.CARDS / name), type="jpeg", quality=90)
    finally:
        await page.close()
    return name, estourou


async def slide(titulo: str, texto: str, idx: int, total: int, handle: str, nome: str, tipo: str = "conteudo", p: dict | None = None) -> tuple[str, bool]:
    """Um slide de carrossel 1080x1350. tipo: capa | conteudo | cta. Devolve (arquivo, texto_estourou)."""
    env = Environment(loader=FileSystemLoader(str(C.CARD_TEMPLATES)), autoescape=select_autoescape(["html"]))
    paragrafos = [p.strip() for p in re.split(r"\n\s*\n|\n", texto or "") if p.strip()]
    html = env.get_template("carrossel.html").render(titulo=titulo, paragrafos=paragrafos, idx=idx, total=total,
                                                      handle=handle, nome=nome, tipo=tipo, **M.contexto(p))
    name = f"{uuid.uuid4().hex}.jpg"
    page = await _state["browser"].new_page(viewport={"width": 1080, "height": 1350})
    try:
        await page.set_content(html, wait_until="load")
        estourou = await page.evaluate(
            "() => { const b = document.querySelector('.body'), m = document.querySelector('.mid');"
            " return (b && b.scrollHeight > b.clientHeight + 2) || m.scrollHeight > m.clientHeight + 2 }")
        await page.screenshot(path=str(C.CARDS / name), type="jpeg", quality=90)
    finally:
        await page.close()
    return name, estourou


async def overlay_story(texto: str, handle: str = "", p: dict | None = None, mencoes: list[str] | None = None) -> str:
    """PNG transparente 1080x1920 com o texto na zona segura do Story (para sobrepor na foto ou no vídeo). Devolve o nome em CARDS-tmp."""
    env = Environment(loader=FileSystemLoader(str(C.CARD_TEMPLATES)), autoescape=select_autoescape(["html"]))
    tamanho = 78 if len(texto) <= 60 else (66 if len(texto) <= 100 else 56)
    html = env.get_template("overlay_story.html").render(texto=texto, handle=handle, tamanho=tamanho, mencoes=mencoes or [], **M.contexto(p))
    tmp = C.DATA / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    caminho = tmp / f"{uuid.uuid4().hex}.png"
    page = await _state["browser"].new_page(viewport={"width": 1080, "height": 1920})
    try:
        await page.set_content(html, wait_until="load")
        await page.screenshot(path=str(caminho), type="png", omit_background=True)
    finally:
        await page.close()
    return str(caminho)


def _uri(caminho) -> str:
    import base64
    from pathlib import Path
    c = Path(caminho)
    mime = "image/png" if c.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(c.read_bytes()).decode()


async def _foto_pagina(html: str, altura: int = 1350) -> tuple[str, bool]:
    name = f"{uuid.uuid4().hex}.jpg"
    page = await _state["browser"].new_page(viewport={"width": 1080, "height": altura})
    try:
        await page.set_content(html, wait_until="load")
        estourou = await page.evaluate(
            "() => [...document.querySelectorAll('.frase, .t')].some(f => f.scrollHeight > f.clientHeight + 14)")
        await page.screenshot(path=str(C.CARDS / name), type="jpeg", quality=90)
    finally:
        await page.close()
    return name, estourou


async def citacao(frase: str, autor: str, handle: str, nome: str, p: dict | None = None, estilo: str | None = None,
                  fundo=None, credito: str = "") -> tuple[str, bool]:
    """Card de citação 1080x1350. estilo: escuro | claro | acento (cores da marca); com 'fundo' (foto) usa a foto com véu escuro."""
    env = Environment(loader=FileSystemLoader(str(C.CARD_TEMPLATES)), autoescape=select_autoescape(["html"]))
    tamanho = 92 if len(frase) <= 70 else (80 if len(frase) <= 120 else (68 if len(frase) <= 180 else 58))
    html = env.get_template("citacao.html").render(frase=frase, autor=autor, handle=handle, nome=nome, tamanho=tamanho,
                                                   fundo_uri=_uri(fundo) if fundo else None, credito=credito,
                                                   **M.contexto(p, None if fundo else estilo))
    return await _foto_pagina(html)


async def meme(foto, topo: str, base: str, p: dict | None = None) -> tuple[str, bool]:
    """Meme clássico: texto em caixa alta, branco com contorno preto, no topo e/ou embaixo da foto (1080x1350)."""
    env = Environment(loader=FileSystemLoader(str(C.CARD_TEMPLATES)), autoescape=select_autoescape(["html"]))
    maior = max(len(topo or ""), len(base or ""))
    tamanho = 104 if maior <= 24 else (88 if maior <= 40 else (72 if maior <= 60 else 60))
    html = env.get_template("meme.html").render(foto_uri=_uri(foto), topo=(topo or "").strip(), base=(base or "").strip(),
                                                tamanho=tamanho, **M.contexto(p))
    return await _foto_pagina(html)
