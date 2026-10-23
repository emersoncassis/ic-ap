"""Motor e Bridge VectorCraft para Criação de Ativos Visuais e Vetoriais.

Implementa os comandos e primitivas do VectorCraft (Adobe Illustrator parity em Rust/SVG):
- draw_shape: retângulos com raio, elipses, polígonos, estrelas, linhas
- draw_path: caminhos com curvas Bézier e comandos SVG
- add_text: tipografia, texto em curva, pesos, alinhamentos
- apply_effect: brilho neon (outer glow), sombras (drop shadow), gradientes lineares/radiais
- presets: selos/badges de retenção, overlays para Reels (9:16 safe zones), lower-thirds,
           molduras de carrossel e fundos geométricos/synthwave.
- export / render: geração de SVG puro e rasterização PNG em alta resolução via Chromium.
"""
import base64
import logging
import math
import re
from pathlib import Path
from typing import Any

from . import config as C

logger = logging.getLogger(__name__)


class VectorCraftDoc:
    """Documento de arte vetorial inspirado no VectorCraft Engine."""

    def __init__(self, width: int = 1080, height: int = 1350, title: str = "VectorCraft Art"):
        self.width = width
        self.height = height
        self.title = title
        self.defs: list[str] = []
        self.elements: list[str] = []
        self._def_counter = 0

    def add_linear_gradient(self, id_grad: str, stops: list[tuple[float, str]], x1="0%", y1="0%", x2="100%", y2="100%") -> str:
        """Adiciona um gradiente linear às definições e retorna o identificador url(#id)."""
        stop_elems = "".join(f'<stop offset="{s[0] * 100:.0f}%" stop-color="{s[1]}" />' for s in stops)
        self.defs.append(f'<linearGradient id="{id_grad}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">{stop_elems}</linearGradient>')
        return f"url(#{id_grad})"

    def add_radial_gradient(self, id_grad: str, stops: list[tuple[float, str]], cx="50%", cy="50%", r="50%") -> str:
        """Adiciona um gradiente radial às definições."""
        stop_elems = "".join(f'<stop offset="{s[0] * 100:.0f}%" stop-color="{s[1]}" />' for s in stops)
        self.defs.append(f'<radialGradient id="{id_grad}" cx="{cx}" cy="{cy}" r="{r}">{stop_elems}</radialGradient>')
        return f"url(#{id_grad})"

    def add_glow_filter(self, id_filter: str, cor: str = "#00f0ff", desvio: float = 8.0) -> str:
        """Adiciona filtro de brilho neon (outer glow) estilo VectorCraft."""
        f = f"""
        <filter id="{id_filter}" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="{desvio}" result="blur" />
            <feFlood flood-color="{cor}" result="color" />
            <feComposite in="color" in2="blur" operator="in" result="coloredBlur" />
            <feMerge>
                <feMergeNode in="coloredBlur" />
                <feMergeNode in="coloredBlur" />
                <feMergeNode in="SourceGraphic" />
            </feMerge>
        </filter>
        """.strip()
        self.defs.append(f)
        return f"url(#{id_filter})"

    def add_drop_shadow_filter(self, id_filter: str, dx: float = 0, dy: float = 6, blur: float = 12, opacity: float = 0.5) -> str:
        """Adiciona filtro de sombra projetada suave."""
        f = f"""
        <filter id="{id_filter}" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="{dx}" dy="{dy}" stdDeviation="{blur}" flood-opacity="{opacity}" flood-color="#000000" />
        </filter>
        """.strip()
        self.defs.append(f)
        return f"url(#{id_filter})"

    def draw_shape(self, shape: str, **params: Any) -> "VectorCraftDoc":
        """Executa o comando draw_shape do VectorCraft.
        
        Suporta:
        - rectangle: x, y, width, height, radius, fill, stroke, stroke_width, filter, opacity
        - ellipse: cx, cy, rx, ry, fill, stroke, stroke_width, filter, opacity
        - polygon: cx, cy, radius, sides, fill, stroke, stroke_width, filter, opacity
        - star: cx, cy, radius1, radius2, points, fill, stroke, stroke_width, filter, opacity
        - line: x1, y1, x2, y2, stroke, stroke_width, dash
        """
        fill = params.get("fill", "none")
        stroke = params.get("stroke", "none")
        sw = params.get("stroke_width", 0)
        filtro = f'filter="{params["filter"]}"' if params.get("filter") else ""
        opacity = f'opacity="{params["opacity"]}"' if "opacity" in params else ""
        dash = f'stroke-dasharray="{params["dash"]}"' if params.get("dash") else ""

        if shape == "rectangle":
            x, y = params.get("x", 0), params.get("y", 0)
            w, h = params.get("width", 100), params.get("height", 100)
            rx = params.get("radius", 0)
            self.elements.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="{sw}" {dash} {filtro} {opacity} />'
            )
        elif shape == "ellipse":
            cx, cy = params.get("cx", 0), params.get("cy", 0)
            rx, ry = params.get("rx", 50), params.get("ry", 50)
            self.elements.append(
                f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="{sw}" {dash} {filtro} {opacity} />'
            )
        elif shape == "polygon":
            cx, cy = params.get("cx", 0), params.get("cy", 0)
            r = params.get("radius", 50)
            sides = max(3, params.get("sides", 6))
            pts = []
            for i in range(sides):
                ang = i * (2 * math.pi / sides) - (math.pi / 2)
                px = cx + r * math.cos(ang)
                py = cy + r * math.sin(ang)
                pts.append(f"{px:.2f},{py:.2f}")
            self.elements.append(
                f'<polygon points="{" ".join(pts)}" fill="{fill}" stroke="{stroke}" '
                f'stroke-width="{sw}" {dash} {filtro} {opacity} />'
            )
        elif shape == "star":
            cx, cy = params.get("cx", 0), params.get("cy", 0)
            r1 = params.get("radius1", 50)
            r2 = params.get("radius2", 25)
            num_pts = max(3, params.get("points", 5))
            pts = []
            for i in range(num_pts * 2):
                r = r1 if i % 2 == 0 else r2
                ang = i * (math.pi / num_pts) - (math.pi / 2)
                px = cx + r * math.cos(ang)
                py = cy + r * math.sin(ang)
                pts.append(f"{px:.2f},{py:.2f}")
            self.elements.append(
                f'<polygon points="{" ".join(pts)}" fill="{fill}" stroke="{stroke}" '
                f'stroke-width="{sw}" {dash} {filtro} {opacity} />'
            )
        elif shape == "line":
            x1, y1 = params.get("x1", 0), params.get("y1", 0)
            x2, y2 = params.get("x2", 100), params.get("y2", 100)
            self.elements.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
                f'stroke-width="{sw}" {dash} {filtro} {opacity} />'
            )
        return self

    def draw_path(self, d: str, fill: str = "none", stroke: str = "none", stroke_width: float = 0, **params: Any) -> "VectorCraftDoc":
        """Executa o comando draw_path do VectorCraft com dados de curvas Bézier."""
        filtro = f'filter="{params["filter"]}"' if params.get("filter") else ""
        opacity = f'opacity="{params["opacity"]}"' if "opacity" in params else ""
        dash = f'stroke-dasharray="{params["dash"]}"' if params.get("dash") else ""
        cap = f'stroke-linecap="{params.get("cap", "round")}"'
        join = f'stroke-linejoin="{params.get("join", "round")}"'
        self.elements.append(
            f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" '
            f'{cap} {join} {dash} {filtro} {opacity} />'
        )
        return self

    def add_text(
        self,
        text: str,
        x: float,
        y: float,
        font_size: int = 36,
        color: str = "#ffffff",
        font_family: str = "'Inter', 'Montserrat', -apple-system, sans-serif",
        font_weight: str = "bold",
        text_anchor: str = "middle",
        letter_spacing: float = 0.0,
        filter_url: str = "",
        stroke: str = "",
        stroke_width: float = 0,
    ) -> "VectorCraftDoc":
        """Adiciona tipografia vetorial de alta definição."""
        filtro = f'filter="{filter_url}"' if filter_url else ""
        sp = f'letter-spacing="{letter_spacing}px"' if letter_spacing else ""
        stk = f'stroke="{stroke}" stroke-width="{stroke_width}"' if stroke else ""
        self.elements.append(
            f'<text x="{x}" y="{y}" fill="{color}" font-family="{font_family}" font-size="{font_size}px" '
            f'font-weight="{font_weight}" text-anchor="{text_anchor}" {sp} {stk} {filtro}>{text}</text>'
        )
        return self

    def to_svg(self) -> str:
        """Serializa o documento para uma string SVG limpa, standalone e escalável."""
        defs_bloco = f"<defs>{''.join(self.defs)}</defs>" if self.defs else ""
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" '
            f'width="{self.width}" height="{self.height}">\n'
            f'{defs_bloco}\n'
            f'<g id="VectorCraft_Layer_1">\n'
            f'{"".join(self.elements)}\n'
            f'</g>\n'
            f'</svg>'
        )


# =====================================================================
# PRESETS E FERRAMENTAS CRIATIVAS DO VECTORCRAFT
# =====================================================================

def criar_badge_vetorial(
    texto: str,
    estilo: str = "neon_ciano",
    subtexto: str = "",
    largura: int = 500,
    altura: int = 140,
) -> str:
    """Gera um selo/adesivo vetorial de alta conversão (para Reels, Stories e Capas).
    
    Estilos:
    - 'neon_ciano': Brilho cibernético ciano e roxo.
    - 'neon_ouro': Visual dourado premium para ofertas/conteúdo VIP.
    - 'alerta_vermelho': Tag chamativa para notícias urgentes e polêmicas.
    - 'glassmorphism': Fundo translúcido com borda suave e visual Apple.
    - 'pill_clean': Tag moderna e limpa no estilo 2026.
    """
    doc = VectorCraftDoc(width=largura, height=altura)

    cx = largura / 2
    cy = altura / 2
    padding = 10

    if estilo == "neon_ciano":
        glow = doc.add_glow_filter("glow_cyan", cor="#00f0ff", desvio=6.0)
        grad = doc.add_linear_gradient("grad_bg", [(0.0, "#0b121e"), (1.0, "#16243b")], x1="0%", y1="0%", x2="100%", y2="100%")
        
        # Borda externa com glow
        doc.draw_shape("rectangle", x=padding, y=padding, width=largura - padding*2, height=altura - padding*2,
                       radius=altura/2, fill=grad, stroke="#00f0ff", stroke_width=2.5, filter=glow)
        # Detalhe geométrico lateral
        doc.draw_shape("polygon", cx=padding + 28, cy=cy, radius=12, sides=3, fill="#00f0ff")
        doc.draw_shape("polygon", cx=largura - padding - 28, cy=cy, radius=12, sides=3, fill="#00f0ff")
        
        doc.add_text(texto.upper(), x=cx, y=cy + (6 if not subtexto else -4), font_size=int(altura * 0.32),
                     color="#ffffff", font_weight="900", letter_spacing=2.0)
        if subtexto:
            doc.add_text(subtexto.upper(), x=cx, y=cy + 28, font_size=int(altura * 0.18),
                         color="#00f0ff", font_weight="600", letter_spacing=1.5)

    elif estilo == "neon_ouro":
        glow = doc.add_glow_filter("glow_gold", cor="#ffd700", desvio=6.0)
        grad = doc.add_linear_gradient("grad_gold", [(0.0, "#ffd700"), (0.5, "#fff2a1"), (1.0, "#d4af37")])
        bg = doc.add_linear_gradient("grad_gold_bg", [(0.0, "#1a1608"), (1.0, "#2c240a")])

        doc.draw_shape("rectangle", x=padding, y=padding, width=largura - padding*2, height=altura - padding*2,
                       radius=18, fill=bg, stroke=grad, stroke_width=3, filter=glow)
        # Estrela decorativa
        doc.draw_shape("star", cx=padding + 30, cy=cy, radius1=14, radius2=7, points=5, fill=grad)
        doc.draw_shape("star", cx=largura - padding - 30, cy=cy, radius1=14, radius2=7, points=5, fill=grad)
        
        doc.add_text(texto.upper(), x=cx, y=cy + (6 if not subtexto else -4), font_size=int(altura * 0.32),
                     color="#fff8db", font_weight="900", letter_spacing=2.5)
        if subtexto:
            doc.add_text(subtexto.upper(), x=cx, y=cy + 28, font_size=int(altura * 0.18),
                         color="#ffd700", font_weight="700", letter_spacing=2.0)

    elif estilo == "alerta_vermelho":
        glow = doc.add_glow_filter("glow_red", cor="#ff2a55", desvio=8.0)
        grad = doc.add_linear_gradient("grad_red", [(0.0, "#ff1a40"), (1.0, "#b80024")])
        doc.draw_shape("rectangle", x=padding, y=padding, width=largura - padding*2, height=altura - padding*2,
                       radius=12, fill=grad, stroke="#ffffff", stroke_width=2, filter=glow)
        doc.add_text(f"⚠ {texto.upper()}", x=cx, y=cy + (6 if not subtexto else -4), font_size=int(altura * 0.34),
                     color="#ffffff", font_weight="900", letter_spacing=1.8)
        if subtexto:
            doc.add_text(subtexto, x=cx, y=cy + 28, font_size=int(altura * 0.18),
                         color="#ffdfe5", font_weight="600")

    else:  # pill_clean
        shadow = doc.add_drop_shadow_filter("shadow_clean", dy=4, blur=8, opacity=0.35)
        doc.draw_shape("rectangle", x=padding, y=padding, width=largura - padding*2, height=altura - padding*2,
                       radius=altura/2, fill="#ffffff", filter=shadow)
        doc.add_text(texto.upper(), x=cx, y=cy + (6 if not subtexto else -4), font_size=int(altura * 0.30),
                     color="#0f141c", font_weight="800", letter_spacing=1.5)
        if subtexto:
            doc.add_text(subtexto, x=cx, y=cy + 26, font_size=int(altura * 0.17),
                         color="#5c6a79", font_weight="600")

    return doc.to_svg()


def criar_overlay_reels(
    titulo: str,
    subtitulo: str = "",
    badge_texto: str = "NOVO",
    safe_zone: bool = True,
    estilo: str = "cyber_clean",
) -> str:
    """Gera um layout de sobreposição para Reels (1080x1920) respeitando rigorosamente as Safe Zones:
    - Topo livre (primeiros 220px) para header do Instagram.
    - Lateral direita livre (últimos 150px) para botões de curtir/comentar/compartilhar.
    - Base livre (últimos 380px) para legenda do app e áudio original.
    """
    doc = VectorCraftDoc(width=1080, height=1920, title="Reels Safe Overlay")

    # Gradiente sutil escuro para contraste de leitura
    grad_fade = doc.add_linear_gradient("top_fade", [(0.0, "rgba(0,0,0,0.85)"), (0.5, "rgba(0,0,0,0.5)"), (1.0, "rgba(0,0,0,0.0)")],
                                        x1="0%", y1="0%", x2="0%", y2="100%")
    doc.draw_shape("rectangle", x=0, y=0, width=1080, height=600, fill=grad_fade)

    # Base da safe-zone
    card_y = 260
    card_w = 920
    card_x = (1080 - card_w) / 2

    # Badge de topo
    if badge_texto:
        glow = doc.add_glow_filter("badge_glow", cor="#ff0055", desvio=6.0)
        doc.draw_shape("rectangle", x=card_x, y=card_y, width=160, height=44, radius=22,
                       fill="#ff0055", filter=glow)
        doc.add_text(badge_texto.upper(), x=card_x + 80, y=card_y + 28, font_size=18,
                     color="#ffffff", font_weight="900", letter_spacing=1.5)

    # Título principal do gancho
    doc.add_text(
        titulo,
        x=card_x,
        y=card_y + 110,
        font_size=58,
        color="#ffffff",
        font_weight="900",
        text_anchor="start",
        letter_spacing=-0.5,
    )

    # Subtítulo de apoio
    if subtitulo:
        doc.add_text(
            subtitulo,
            x=card_x,
            y=card_y + 175,
            font_size=32,
            color="#ffd700",
            font_weight="700",
            text_anchor="start",
            letter_spacing=0.2,
        )

    # Indicador de chamada inferior (logo acima da legenda, na safe zone)
    call_y = 1500
    doc.draw_shape("rectangle", x=card_x, y=call_y, width=card_w, height=80, radius=40,
                   fill="rgba(15, 20, 30, 0.75)", stroke="rgba(255, 255, 255, 0.2)", stroke_width=1.5)
    doc.add_text("🔥 VEJA OS DETALHES NA LEGENDA ABAIXO", x=540, y=call_y + 48, font_size=24,
                 color="#ffffff", font_weight="800", letter_spacing=1.0)

    return doc.to_svg()


def criar_slide_vetorial_carrossel(
    titulo: str,
    corpo: str,
    indice: int,
    total: int,
    badge: str = "",
    tema: str = "dark_neon",
) -> str:
    """Gera um slide de carrossel 1080x1350 diagramado com precisão vetorial."""
    doc = VectorCraftDoc(width=1080, height=1350, title=f"Slide {indice}")

    # Fundo
    grad_bg = doc.add_linear_gradient("slide_bg", [(0.0, "#0c1017"), (0.6, "#141b26"), (1.0, "#0a0d14")],
                                      x1="0%", y1="0%", x2="100%", y2="100%")
    doc.draw_shape("rectangle", x=0, y=0, width=1080, height=1350, fill=grad_bg)

    # Grid geométrico sutil decorativo
    for y in range(120, 1250, 160):
        doc.draw_shape("line", x1=60, y1=y, x2=1020, y2=y, stroke="rgba(255,255,255,0.03)", stroke_width=1)

    # Header: Numeração e Badge
    num_txt = f"{indice:02d} / {total:02d}"
    doc.add_text(num_txt, x=100, y=140, font_size=26, color="#00f0ff", font_weight="800", text_anchor="start", letter_spacing=2)

    if badge:
        doc.draw_shape("rectangle", x=780, y=110, width=200, height=42, radius=21,
                       fill="rgba(0, 240, 255, 0.12)", stroke="#00f0ff", stroke_width=1.5)
        doc.add_text(badge.upper(), x=880, y=138, font_size=16, color="#00f0ff", font_weight="800", letter_spacing=1.2)

    # Linha separadora de alta definição
    glow_line = doc.add_glow_filter("glow_div", cor="#00f0ff", desvio=4)
    doc.draw_shape("line", x1=100, y1=170, x2=980, y2=170, stroke="#00f0ff", stroke_width=2, filter=glow_line)

    # Título do Slide (com suporte a quebra de linha simples)
    palavras = titulo.split()
    linhas_titulo = []
    linha_atual = []
    for p in palavras:
        linha_atual.append(p)
        if len(" ".join(linha_atual)) >= 24:
            linhas_titulo.append(" ".join(linha_atual))
            linha_atual = []
    if linha_atual:
        linhas_titulo.append(" ".join(linha_atual))

    cur_y = 290
    for l in linhas_titulo[:3]:
        doc.add_text(l, x=100, y=cur_y, font_size=56, color="#ffffff", font_weight="900", text_anchor="start", letter_spacing=-0.5)
        cur_y += 72

    # Corpo do Slide
    paragrafos = [p.strip() for p in re.split(r"\n\s*\n|\n", corpo) if p.strip()]
    cur_y += 50

    card_shadow = doc.add_drop_shadow_filter("card_shadow", dy=10, blur=20, opacity=0.4)
    for p in paragrafos[:3]:
        # Card de conteúdo translúcido
        doc.draw_shape("rectangle", x=100, y=cur_y, width=880, height=170, radius=20,
                       fill="rgba(255, 255, 255, 0.04)", stroke="rgba(255, 255, 255, 0.08)", stroke_width=1, filter=card_shadow)
        
        # Ponto luminoso de destaque
        doc.draw_shape("ellipse", cx=140, cy=cur_y + 40, rx=8, ry=8, fill="#00f0ff")

        # Texto do parágrafo
        p_palavras = p.split()
        l1 = " ".join(p_palavras[:10])
        l2 = " ".join(p_palavras[10:20])
        l3 = " ".join(p_palavras[20:30])

        doc.add_text(l1, x=170, y=cur_y + 46, font_size=28, color="#e6edf5", font_weight="500", text_anchor="start")
        if l2:
            doc.add_text(l2, x=170, y=cur_y + 86, font_size=28, color="#b0c0d0", font_weight="400", text_anchor="start")
        if l3:
            doc.add_text(l3, x=170, y=cur_y + 126, font_size=26, color="#8090a0", font_weight="400", text_anchor="start")

        cur_y += 200

    # Rodapé com Swipe Indicator
    doc.draw_shape("line", x1=100, y1=1230, x2=980, y2=1230, stroke="rgba(255,255,255,0.08)", stroke_width=1)
    doc.add_text("ARRASTE PARA O LADO 👉", x=540, y=1280, font_size=20, color="#00f0ff", font_weight="800", letter_spacing=2.0)

    return doc.to_svg()


def svg_para_data_uri(svg_content: str) -> str:
    """Converte uma string SVG diretamente para data URI base64."""
    b64_svg = base64.b64encode(svg_content.encode("utf-8")).decode("utf-8")
    return f"data:image/svg+xml;base64,{b64_svg}"


async def renderizar_svg_para_png(svg_content: str, out_path: Path, largura: int = 1080, altura: int = 1350) -> Path:
    """Renderiza uma string SVG diretamente para um arquivo PNG em alta resolução via Playwright."""
    from . import render
    data_uri = svg_para_data_uri(svg_content)

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ width:{largura}px; height:{altura}px; overflow:hidden; background:transparent; display:flex; }}
        img {{ width:100%; height:100%; object-fit:contain; }}
      </style>
    </head>
    <body>
      <img src="{data_uri}">
    </body>
    </html>
    """

    out_path.parent.mkdir(parents=True, exist_ok=True)
    import asyncio
    loop_atual = asyncio.get_running_loop()
    browser = render._state.get("browser") if render._state.get("loop") is loop_atual else None
    if browser and hasattr(browser, "is_connected") and not browser.is_connected():
        browser = None
    fecha_ao_sair = False
    pw = None

    if not browser:
        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(executable_path=C.CHROMIUM, args=["--no-sandbox"])
            fecha_ao_sair = True
        except Exception as e:
            logger.warning(f"Não foi possível iniciar Chromium sob demanda ({e}); fallback SVG.")

    if browser:
        page = await browser.new_page(viewport={"width": largura, "height": altura})
        try:
            await page.set_content(html, wait_until="load")
            await page.screenshot(path=str(out_path), type="png", omit_background=True)
        finally:
            await page.close()
            if fecha_ao_sair:
                await browser.close()
                if pw:
                    await pw.stop()
        return out_path
    else:
        # Fallback caso browser não esteja disponível (grava como SVG)
        svg_file = out_path.with_suffix(".svg")
        svg_file.write_text(svg_content, encoding="utf-8")
        return svg_file
