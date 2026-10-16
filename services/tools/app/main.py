"""Serviço de apoio: extrai texto de matéria e renderiza o card em JPEG."""
import os, re, uuid
from contextlib import asynccontextmanager
from pathlib import Path

import trafilatura
from fastapi import FastAPI, HTTPException
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

TEMPLATES = Path(os.getenv("TEMPLATES_DIR", "/app/templates"))
PUBLIC = Path(os.getenv("PUBLIC_DIR", "/data/public"))
BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
MAX_CHARS = int(os.getenv("EXTRACT_MAX_CHARS", "6000"))
CHROMIUM = os.getenv("CHROMIUM_PATH") or None

env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    PUBLIC.mkdir(parents=True, exist_ok=True)
    pw = await async_playwright().start()
    state["browser"] = await pw.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
    yield
    await state["browser"].close()
    await pw.stop()


app = FastAPI(title="ic-ap tools", lifespan=lifespan)


class ExtractIn(BaseModel):
    url: str


class RenderIn(BaseModel):
    manchete: str = Field(max_length=120)
    reacao: str = Field(max_length=700)
    fonte: str = Field(max_length=60)
    handle: str = os.getenv("CARD_HANDLE", "@usuario")
    nome: str = os.getenv("CARD_NAME", "")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/extract")
def extract(body: ExtractIn):
    html = trafilatura.fetch_url(body.url)
    if not html:
        raise HTTPException(502, "não consegui baixar a página")
    data = trafilatura.bare_extraction(html, url=body.url, with_metadata=True)
    if not data or not getattr(data, "text", None):
        raise HTTPException(422, "sem texto extraível")
    return {
        "url": body.url,
        "titulo": data.title,
        "fonte": data.sitename or data.hostname,
        "data": data.date,
        "texto": data.text[:MAX_CHARS],
    }


@app.post("/render")
async def render(body: RenderIn):
    paragrafos = [p.strip() for p in re.split(r"\n\s*\n|\n", body.reacao) if p.strip()]
    html = env.get_template("reacao.html").render(
        manchete=body.manchete, paragrafos=paragrafos, fonte=body.fonte,
        handle=body.handle, nome=body.nome)
    name = f"{uuid.uuid4().hex}.jpg"
    page = await state["browser"].new_page(viewport={"width": 1080, "height": 1350})
    try:
        await page.set_content(html, wait_until="load")
        overflow = await page.evaluate(
            "() => { const b = document.querySelector('.body'); return b.scrollHeight > b.clientHeight + 2 }")
        await page.screenshot(path=str(PUBLIC / name), type="jpeg", quality=90)
    finally:
        await page.close()
    return {"arquivo": name, "public_url": f"{BASE_URL}/{name}" if BASE_URL else None,
            "texto_estourou": overflow}


@app.delete("/public/{name}")
def delete(name: str):
    if not re.fullmatch(r"[0-9a-f]{32}\.jpg", name):
        raise HTTPException(400, "nome inválido")
    (PUBLIC / name).unlink(missing_ok=True)
    return {"apagado": name}
