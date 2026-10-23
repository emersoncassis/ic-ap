"""Render do card: HTML -> JPEG 1080x1350 via Chromium (Playwright)."""
import re, uuid
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

from . import config as C, marca as M

_state: dict = {}


async def start() -> None:
    import asyncio
    _state["pw"] = await async_playwright().start()
    _state["browser"] = await _state["pw"].chromium.launch(executable_path=C.CHROMIUM, args=["--no-sandbox"])
    _state["loop"] = asyncio.get_running_loop()


async def stop() -> None:
    if _state.get("browser"):
        try:
            await _state["browser"].close()
        except Exception:
            pass
    if _state.get("pw"):
        try:
            await _state["pw"].stop()
        except Exception:
            pass
    _state.clear()


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


TEMAS_DISPONIVEIS = ("cyber_glass", "editorial_bold", "alerta_critico", "clean_minimalist")


def escolher_estilo_automatico(texto: str) -> str:
    t = (texto or "").lower()
    if any(k in t for k in ("alerta", "risco", "lgpd", "vazar", "vazamento", "jurídico", "juridico", "perigo", "processo", "urgente")):
        return "alerta_critico"
    elif any(k in t for k in ("ia local", "on-premise", "servidor", "ciber", "codigo", "chatgpt", "deep learning", "gpu")):
        return "cyber_glass"
    elif any(k in t for k in ("empresa", "b2b", "mercado", "gestor", "dinheiro", "negócio", "lucro", "faturamento")):
        return "editorial_bold"
    return "cyber_glass"


def destacar_manchete(texto: str) -> str:
    """Destaca palavras-chave com badges pills coloridos (ex: ChatGPT, IA on-premise)."""
    t = texto or ""
    # Se o texto já tiver markdown ou colchetes [termo] ou **termo**
    t = re.sub(r'\[([^\]]+)\]', r'<span class="badge-pill pill-red">\1</span>', t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<span class="badge-pill pill-red">\1</span>', t)

    if "badge-pill" not in t:
        termos_destaque = [
            ("ChatGPT", "pill-red"),
            ("OpenAI", "pill-red"),
            ("LGPD", "pill-red"),
            ("DeepSeek", "pill-red"),
            ("Claude", "pill-red"),
            ("Gemini", "pill-red"),
            ("IA pública", "pill-red"),
            ("IA publica", "pill-red"),
            ("IA on-premise", "pill-cyan"),
            ("IA local", "pill-cyan"),
            ("Segurança", "pill-cyan"),
        ]
        for termo, classe in termos_destaque:
            padrao = re.compile(rf'\b({re.escape(termo)})\b', re.IGNORECASE)
            if padrao.search(t):
                t = padrao.sub(rf'<span class="badge-pill {classe}">\1</span>', t, count=1)
                break
    return t


def estruturar_paragrafos(paragrafos: list[str]) -> list[dict]:
    """Estrutura os parágrafos em blocos de comparação: alerta (pública) vs solução (on-premise)."""
    itens = []
    for p in paragrafos:
        p_clean = p.strip()
        p_low = p_clean.lower()
        if not p_clean:
            continue
        if p_low.startswith("ia pública") or p_low.startswith("ia publica") or p_low.startswith("nuvem pública") or p_low.startswith("ia comercial"):
            titulo = "IA pública"
            texto = p_clean[len(titulo):].strip().lstrip(":- ")
            itens.append({"tipo": "publica", "titulo": titulo, "texto": texto or p_clean})
        elif p_low.startswith("ia on-premise") or p_low.startswith("ia local") or p_low.startswith("ia privada") or p_low.startswith("on-premise"):
            titulo = "IA on-premise"
            texto = p_clean[len(titulo):].strip().lstrip(":- ")
            itens.append({"tipo": "privada", "titulo": titulo, "texto": texto or p_clean})
        elif p_low.startswith("você controla") or p_low.startswith("voce controla") or (len(p_clean) < 65 and not p_clean.endswith(".")):
            itens.append({"tipo": "destaque", "texto": p_clean})
        else:
            itens.append({"tipo": "normal", "texto": p_clean})
    return itens


LAYOUTS_NOVOS = ("impacto_foto", "editorial", "lista", "dado", "alerta", "citacao")


def destacar_manchete_com_palavras(texto: str, palavras: list[str] | None = None, cor_destaque: str = "") -> str:
    """Destaca palavras na manchete com span highlight-word."""
    t = texto or ""
    t = re.sub(r'\[([^\]]+)\]', r'<span class="highlight-word">\1</span>', t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<span class="highlight-word">\1</span>', t)
    if "highlight-word" in t:
        return t

    if palavras:
        destacados = 0
        for p in palavras:
            p_limpo = (p or "").strip().strip("?!,.;:")
            if len(p_limpo) < 3:
                continue
            padrao = re.compile(rf'(?<!>)({re.escape(p_limpo)})(?!<)', re.IGNORECASE)
            if padrao.search(t):
                t = padrao.sub(r'<span class="highlight-word">\1</span>', t, count=1)
                destacados += 1
                if destacados >= 2:
                    break

    return t


async def render_design(
    layout: str,
    formato: str,
    manchete: str,
    paragrafos: list[str] | str = "",
    handle: str = "",
    nome: str = "",
    palavras_destaque: list[str] | None = None,
    itens: list[Any] | None = None,
    dado: str | None = None,
    dado_legenda: str | None = None,
    frase_impacto: str | None = None,
    cta_texto: str | None = None,
    post_tipo_label: str | None = None,
    selo_uri: str | None = None,
    imagem_fundo_path: str | Path | None = None,
    paleta: dict | None = None,
    p: dict | None = None,
    pid: int | str | None = None,
    corpo: list[str] | str | None = None,
) -> tuple[str, bool]:
    """Renderiza um card usando um dos 6 layouts dinâmicos do estúdio agêntico.
    Devolve (nome_do_arquivo, texto_estourou).
    """
    story = formato == "story"
    altura = 1920 if story else 1350
    layout_normalizado = layout if layout in LAYOUTS_NOVOS else "editorial"

    env = Environment(loader=FileSystemLoader(str(C.CARD_TEMPLATES)), autoescape=select_autoescape(["html"]))

    texto_para_paragrafos = corpo if (corpo is not None and not paragrafos) else paragrafos
    if isinstance(texto_para_paragrafos, str):
        paragrafos_lista = [pr.strip() for pr in re.split(r"\n\s*\n|\n", texto_para_paragrafos) if pr.strip()]
    else:
        paragrafos_lista = list(texto_para_paragrafos or [])

    paragrafos_lista = [
        re.sub(r"^\s*\*{0,2}\[[A-Z_]+\]\*{0,2}\s*:?\s*", "", pr).strip()
        for pr in paragrafos_lista
        if re.sub(r"^\s*\*{0,2}\[[A-Z_]+\]\*{0,2}\s*:?\s*", "", pr).strip()
        and re.sub(r"^\s*\*{0,2}\[[A-Z_]+\]\*{0,2}\s*:?\s*", "", pr).strip().upper() != manchete.strip().upper()
    ]

    cor_destaque = (paleta or {}).get("destaque", "#00ff88")
    manchete_html = destacar_manchete_com_palavras(manchete, palavras_destaque, cor_destaque)

    imagem_fundo_uri = None
    if imagem_fundo_path:
        p_img = Path(imagem_fundo_path)
        if p_img.exists():
            imagem_fundo_uri = _uri(p_img)
    if not imagem_fundo_uri:
        try:
            from . import banco
            dest_auto = C.DATA / "fundos" / f"auto_{uuid.uuid4().hex}.jpg"
            await banco.baixar_uma(f"{manchete} {' '.join(paragrafos_lista[:1])}", dest_auto, orientacao="portrait")
            if dest_auto.exists():
                imagem_fundo_uri = _uri(dest_auto)
        except Exception:
            imagem_fundo_uri = None

    cta_limpo = (cta_texto or "").strip()
    if story and "legenda" in cta_limpo.lower():
        cta_limpo = "Responda no Direct"

    itens_lista = []
    for i, raw_it in enumerate(itens or [], 1):
        if isinstance(raw_it, dict):
            itens_lista.append({
                "titulo": raw_it.get("titulo", ""),
                "texto": raw_it.get("texto") or raw_it.get("descricao") or "",
            })
        elif isinstance(raw_it, str):
            partes = raw_it.split(":", 1)
            if len(partes) == 2 and len(partes[0].strip()) <= 35:
                itens_lista.append({"titulo": partes[0].strip(), "texto": partes[1].strip()})
            else:
                itens_lista.append({"titulo": "", "texto": raw_it.strip()})
        else:
            itens_lista.append({"titulo": "", "texto": str(raw_it)})

    if not itens_lista and layout_normalizado == "lista":
        for i, pr in enumerate(paragrafos_lista, 1):
            partes = pr.split(":", 1)
            if len(partes) == 2:
                itens_lista.append({"titulo": partes[0].strip(), "texto": partes[1].strip()})
            else:
                itens_lista.append({"titulo": f"Ponto {i}", "texto": pr.strip()})

    template_file = f"layouts/{layout_normalizado}.html"
    try:
        tmpl = env.get_template(template_file)
    except Exception:
        tmpl = env.get_template("reacao_story.html" if story else "reacao.html")

    html = tmpl.render(
        formato=formato,
        altura=altura,
        manchete=manchete,
        manchete_html=manchete_html,
        paragrafos=paragrafos_lista,
        corpo="\n\n".join(paragrafos_lista),
        itens=itens_lista,
        dado=dado or "73%",
        dado_legenda=dado_legenda or (paragrafos_lista[0] if paragrafos_lista else ""),
        frase_impacto=frase_impacto or "",
        cta_texto=cta_limpo,
        post_tipo_label=post_tipo_label or ("Story" if story else "Post de Feed"),
        selo_uri=selo_uri,
        imagem_fundo_uri=imagem_fundo_uri,
        paleta=paleta or {},
        handle=handle,
        nome=nome,
        pid=pid or "",
        **M.contexto(p)
    )

    if not _state.get("browser"):
        await start()
    name = f"{uuid.uuid4().hex}.jpg"
    page = await _state["browser"].new_page(viewport={"width": 1080, "height": altura})
    try:
        await page.set_content(html, wait_until="load")
        estourou = await page.evaluate(
            "() => { const w = document.querySelector('.card-wrap'); if (w && w.scrollHeight > w.clientHeight + 2) return true; "
            "const b = document.querySelector('.content-container, .editorial-content, .list-container, .dado-hero-container, .alert-container, .quote-body-container, .cards-container, .body'); "
            "return b ? b.scrollHeight > b.clientHeight + 2 : false }"
        )
        await page.screenshot(path=str(C.CARDS / name), type="jpeg", quality=92)
    finally:
        await page.close()
    return name, estourou


async def card(manchete: str, reacao: str, fonte: str, handle: str, nome: str,
               formato: str = "feed", print_uri: str | None = None, p: dict | None = None,
               selo_uri: str | None = None, cta_uri: str | None = None,
               estilo: str | None = None, pid: int | str | None = None,
               cta_texto: str | None = None, post_tipo_label: str | None = None) -> tuple[str, bool]:
    """Devolve (nome_do_arquivo, texto_estourou). O arquivo fica em CARDS (privado).
    formato 'story' usa 1080x1920. selo_uri/cta_uri: artes VectorCraft (data URI SVG)."""
    story = formato == "story"
    estilo_final = estilo if estilo in TEMAS_DISPONIVEIS else escolher_estilo_automatico(f"{manchete} {reacao}")
    env = Environment(loader=FileSystemLoader(str(C.CARD_TEMPLATES)), autoescape=select_autoescape(["html"]))
    paragrafos = [pr.strip() for pr in re.split(r"\n\s*\n|\n", reacao) if pr.strip()]

    # Busca imagem contextualizada em vez do fundo estático repetitivo
    tech_art_uri = None
    if estilo_final == "cyber_glass" and not print_uri:
        try:
            from . import banco
            dest_auto = C.DATA / "fundos" / f"card_{uuid.uuid4().hex}.jpg"
            await banco.baixar_uma(manchete, dest_auto, orientacao="portrait")
            if dest_auto.exists():
                tech_art_uri = _uri(dest_auto)
        except Exception:
            tech_art_uri = None

    manchete_html = destacar_manchete(manchete)
    itens_corpo = estruturar_paragrafos(paragrafos)
    tipo_label = post_tipo_label or ("Story" if story else "Post de Feed")
    cta_final = cta_texto or ""

    html = env.get_template("reacao_story.html" if story else "reacao.html").render(
        manchete=manchete, manchete_html=manchete_html, paragrafos=paragrafos,
        itens_corpo=itens_corpo, tech_art_uri=tech_art_uri,
        fonte=fonte, handle=handle, nome=nome, print_uri=print_uri,
        selo_uri=selo_uri, cta_uri=cta_uri, estilo=estilo_final,
        pid=pid or "", post_tipo_label=tipo_label, cta_texto=cta_final,
        **M.contexto(p))
    name = f"{uuid.uuid4().hex}.jpg"
    page = await _state["browser"].new_page(viewport={"width": 1080, "height": 1920 if story else 1350})
    try:
        await page.set_content(html, wait_until="load")
        estourou = await page.evaluate(
            "() => { const b = document.querySelector('.cards-container, .body'); return b ? b.scrollHeight > b.clientHeight + 2 : false }")
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


async def overlay_story(texto: str, handle: str = "", p: dict | None = None, mencoes: list[str] | None = None,
                        altura: int = 1920, selo_uri: str | None = None) -> str:
    """PNG transparente 1080x1920 (ou 1080x1350 para o feed) com o texto na zona segura (para sobrepor na foto ou no vídeo). Devolve o caminho em data/tmp."""
    env = Environment(loader=FileSystemLoader(str(C.CARD_TEMPLATES)), autoescape=select_autoescape(["html"]))
    tamanho = 74 if len(texto) <= 60 else (62 if len(texto) <= 100 else 52)
    html = env.get_template("overlay_story.html").render(
        texto=texto, handle=handle, tamanho=tamanho, mencoes=mencoes or [], altura=altura,
        base=360 if altura >= 1920 else 120, selo_uri=selo_uri, **M.contexto(p))
    tmp = C.DATA / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    caminho = tmp / f"{uuid.uuid4().hex}.png"
    page = await _state["browser"].new_page(viewport={"width": 1080, "height": altura})
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
    if not _state.get("browser"):
        await start()
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
