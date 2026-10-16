"""Render do card: HTML -> JPEG 1080x1350 via Chromium (Playwright)."""
import re, uuid

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

from . import config as C

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
               formato: str = "feed", print_uri: str | None = None) -> tuple[str, bool]:
    """Devolve (nome_do_arquivo, texto_estourou). O arquivo fica em CARDS (privado).
    formato 'story' usa 1080x1920 (reacao_story.html)."""
    story = formato == "story"
    env = Environment(loader=FileSystemLoader(str(C.CARD_TEMPLATES)), autoescape=select_autoescape(["html"]))
    paragrafos = [p.strip() for p in re.split(r"\n\s*\n|\n", reacao) if p.strip()]
    html = env.get_template("reacao_story.html" if story else "reacao.html").render(
        manchete=manchete, paragrafos=paragrafos, fonte=fonte, handle=handle, nome=nome, print_uri=print_uri)
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


async def slide(titulo: str, texto: str, idx: int, total: int, handle: str, nome: str, tipo: str = "conteudo") -> tuple[str, bool]:
    """Um slide de carrossel 1080x1350. tipo: capa | conteudo | cta. Devolve (arquivo, texto_estourou)."""
    env = Environment(loader=FileSystemLoader(str(C.CARD_TEMPLATES)), autoescape=select_autoescape(["html"]))
    paragrafos = [p.strip() for p in re.split(r"\n\s*\n|\n", texto or "") if p.strip()]
    html = env.get_template("carrossel.html").render(titulo=titulo, paragrafos=paragrafos, idx=idx, total=total,
                                                      handle=handle, nome=nome, tipo=tipo)
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


async def overlay_story(texto: str, handle: str = "") -> str:
    """PNG transparente 1080x1920 com o texto na zona segura do Story (para sobrepor na foto ou no vídeo). Devolve o nome em CARDS-tmp."""
    env = Environment(loader=FileSystemLoader(str(C.CARD_TEMPLATES)), autoescape=select_autoescape(["html"]))
    tamanho = 78 if len(texto) <= 60 else (66 if len(texto) <= 100 else 56)
    html = env.get_template("overlay_story.html").render(texto=texto, handle=handle, tamanho=tamanho)
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
