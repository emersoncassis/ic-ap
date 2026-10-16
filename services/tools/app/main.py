"""Serviço de apoio: extrai texto de matéria e renderiza o card em JPEG."""
import asyncio, os, re, uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
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
IG_BASE = os.getenv("IG_GRAPH_BASE") or (
    f"https://{os.getenv('IG_API_HOST', 'graph.facebook.com')}/{os.getenv('IG_GRAPH_VERSION', 'v23.0')}")
IG_POLL_SECONDS = float(os.getenv("IG_POLL_SECONDS", "5"))
IG_POLL_TRIES = int(os.getenv("IG_POLL_TRIES", "12"))

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


class PublishIn(BaseModel):
    arquivo: str
    legenda: str = Field(max_length=2200)


async def graph(client: httpx.AsyncClient, method: str, path: str, **params):
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    r = await client.request(method, f"{IG_BASE}/{path}", params=params)
    data = r.json()
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", {})
        # nunca repassar o token; só a mensagem da Meta
        raise HTTPException(502, f"Meta: {err.get('message', r.text[:200])} (code {err.get('code')})")
    return data


@app.post("/publish")
async def publish(body: PublishIn):
    if not re.fullmatch(r"[0-9a-f]{32}\.jpg", body.arquivo):
        raise HTTPException(400, "nome inválido")
    if not (PUBLIC / body.arquivo).exists():
        raise HTTPException(404, "arquivo não existe")
    if not BASE_URL:
        raise HTTPException(500, "PUBLIC_BASE_URL não configurada")
    ig = os.environ["IG_USER_ID"]
    async with httpx.AsyncClient(timeout=60) as c:
        cont = await graph(c, "POST", f"{ig}/media", image_url=f"{BASE_URL}/{body.arquivo}", caption=body.legenda)
        cid = cont["id"]
        for _ in range(IG_POLL_TRIES):
            st = (await graph(c, "GET", cid, fields="status_code")).get("status_code")
            if st == "FINISHED":
                break
            if st in ("ERROR", "EXPIRED"):
                raise HTTPException(502, f"container em {st}")
            await asyncio.sleep(IG_POLL_SECONDS)
        else:
            raise HTTPException(504, "container não ficou pronto a tempo")
        pub = await graph(c, "POST", f"{ig}/media_publish", creation_id=cid)
    (PUBLIC / body.arquivo).unlink(missing_ok=True)
    return {"media_id": pub["id"]}
