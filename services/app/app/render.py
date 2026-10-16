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


async def card(manchete: str, reacao: str, fonte: str, handle: str, nome: str) -> tuple[str, bool]:
    """Devolve (nome_do_arquivo, texto_estourou). O arquivo fica em CARDS (privado)."""
    env = Environment(loader=FileSystemLoader(str(C.CARD_TEMPLATES)), autoescape=select_autoescape(["html"]))
    paragrafos = [p.strip() for p in re.split(r"\n\s*\n|\n", reacao) if p.strip()]
    html = env.get_template("reacao.html").render(
        manchete=manchete, paragrafos=paragrafos, fonte=fonte, handle=handle, nome=nome)
    name = f"{uuid.uuid4().hex}.jpg"
    page = await _state["browser"].new_page(viewport={"width": 1080, "height": 1350})
    try:
        await page.set_content(html, wait_until="load")
        estourou = await page.evaluate(
            "() => { const b = document.querySelector('.body'); return b.scrollHeight > b.clientHeight + 2 }")
        await page.screenshot(path=str(C.CARDS / name), type="jpeg", quality=90)
    finally:
        await page.close()
    return name, estourou
