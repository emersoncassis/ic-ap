"""Agente VectorArt: Especialista em design gráfico vetorial e motion graphics (VectorCraft).

Transforma ideias, títulos, chamadas e estilos em gráficos vetoriais profissionais (SVG/PNG):
- Badges e selos de alta retenção (neon, gold, alert, pill) para capas e miniaturas.
- Overlays 9:16 com respeito rigoroso às safe-zones do Instagram Reels, TikTok e Shorts.
- Slides diagramados para carrosséis de alto valor e conversão.
- Composições geométricas e tipográficas personalizadas com gradientes, outer-glow e drop-shadows.
"""
import logging
from pathlib import Path
from typing import Any

from .. import config as C
from ..vectorcraft import (
    VectorCraftDoc,
    criar_badge_vetorial,
    criar_overlay_reels,
    criar_slide_vetorial_carrossel,
    renderizar_svg_para_png,
)
from .base import BaseAgente

logger = logging.getLogger(__name__)

_STR = {"type": "string"}
_NUM = {"type": "number"}

SCHEMA_COMPOSICAO_VETORIAL = {
    "type": "object",
    "properties": {
        "titulo_projeto": _STR,
        "formato": {"type": "string", "enum": ["feed", "reels", "badge", "quadrado"]},
        "largura": {"type": "integer"},
        "altura": {"type": "integer"},
        "estilo_visual": _STR,
        "elementos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": ["shape", "text", "line", "path"]},
                    "forma": {"type": "string", "enum": ["rectangle", "ellipse", "polygon", "star", "line"]},
                    "x": _NUM,
                    "y": _NUM,
                    "largura": _NUM,
                    "altura": _NUM,
                    "raio": _NUM,
                    "texto": _STR,
                    "tamanho_fonte": {"type": "integer"},
                    "peso_fonte": _STR,
                    "alinhamento": {"type": "string", "enum": ["start", "middle", "end"]},
                    "cor_preenchimento": _STR,
                    "cor_borda": _STR,
                    "espessura_borda": _NUM,
                    "efeito": {"type": "string", "enum": ["nenhum", "glow_ciano", "glow_ouro", "glow_vermelho", "sombra_suave"]},
                },
                "required": ["tipo"],
            },
        },
    },
    "required": ["titulo_projeto", "formato", "largura", "altura", "estilo_visual", "elementos"],
}

INSTR_VECTOR_ART = """
Você é o VectorArt Agent, especialista sênior em design vetorial de alta definição (VectorCraft Engine).
Sua missão é planejar layouts visuais impecáveis para redes sociais (Reels, Carrosséis, Feed, Badges e Miniaturas).

Diretrizes de Design 2026:
1. Contraste e Legibilidade: Fundo escuro premium (#0b0f17, #121824) com acentos vibrantes (#00f0ff neon ciano, #ffd700 ouro, #ff2a55 neon pink/red).
2. Safe Zones:
   - Reels (1080x1920): Deixe o topo (0-220px) e a base (1540-1920px) livres de elementos críticos.
   - Carrossel / Feed (1080x1350): Mantenha margem interna de segurança de 60px a 100px.
   - Badges (500x140 ou 600x180): Elementos compactos, tipografia em caixa alta com letter-spacing refinado.
3. Hierarquia Visual: Títulos fortes em 900/bold, contrastes bem definidos e elementos de apoio geométricos (estrelas, polígonos, linhas neon).

Responda SOMENTE em JSON seguindo rigorosamente o schema: titulo_projeto, formato, largura, altura, estilo_visual, elementos.
""".strip()


class VectorArtAgente(BaseAgente):
    """Agente de design gráfico e criação de ativos vetoriais."""

    nome = "vector_art"
    descricao = "Gera artes, overlays para vídeos, badges de retenção e diagramações vetoriais de alta resolução via VectorCraft."
    schema = SCHEMA_COMPOSICAO_VETORIAL

    def gerar_badge(
        self,
        texto: str,
        estilo: str = "neon_ciano",
        subtexto: str = "",
        largura: int = 500,
        altura: int = 140,
    ) -> dict[str, Any]:
        """Gera um badge vetorial imediato nos estilos do VectorCraft."""
        svg = criar_badge_vetorial(
            texto=texto,
            estilo=estilo,
            subtexto=subtexto,
            largura=largura,
            altura=altura,
        )
        return {
            "sucesso": True,
            "tipo": "badge",
            "estilo": estilo,
            "texto": texto,
            "subtexto": subtexto,
            "largura": largura,
            "altura": altura,
            "svg": svg,
        }

    def gerar_overlay_reels(
        self,
        titulo: str,
        subtitulo: str = "",
        badge_texto: str = "NOVO",
        estilo: str = "cyber_clean",
    ) -> dict[str, Any]:
        """Gera um overlay para vídeo vertical (Reels/Shorts) 1080x1920 com safe zones calculadas."""
        svg = criar_overlay_reels(
            titulo=titulo,
            subtitulo=subtitulo,
            badge_texto=badge_texto,
            estilo=estilo,
        )
        return {
            "sucesso": True,
            "tipo": "overlay_reels",
            "titulo": titulo,
            "subtitulo": subtitulo,
            "badge_texto": badge_texto,
            "largura": 1080,
            "altura": 1920,
            "svg": svg,
        }

    def gerar_slide_carrossel(
        self,
        titulo: str,
        corpo: str,
        indice: int = 1,
        total: int = 5,
        badge: str = "",
        tema: str = "dark_neon",
    ) -> dict[str, Any]:
        """Gera um slide 1080x1350 diagramado para carrossel."""
        svg = criar_slide_vetorial_carrossel(
            titulo=titulo,
            corpo=corpo,
            indice=indice,
            total=total,
            badge=badge,
            tema=tema,
        )
        return {
            "sucesso": True,
            "tipo": "slide_carrossel",
            "titulo": titulo,
            "indice": indice,
            "total": total,
            "largura": 1080,
            "altura": 1350,
            "svg": svg,
        }

    def compilar_doc(self, composicao: dict[str, Any]) -> VectorCraftDoc:
        """Converte a estrutura abstrata de composição do agente em um VectorCraftDoc renderizável."""
        largura = int(composicao.get("largura") or 1080)
        altura = int(composicao.get("altura") or 1350)
        titulo = composicao.get("titulo_projeto") or "Arte VectorCraft"

        doc = VectorCraftDoc(width=largura, height=altura, title=titulo)

        # Filtros pré-registrados no documento
        glow_cyan = doc.add_glow_filter("glow_cyan", cor="#00f0ff", desvio=6.0)
        glow_gold = doc.add_glow_filter("glow_gold", cor="#ffd700", desvio=6.0)
        glow_red = doc.add_glow_filter("glow_red", cor="#ff2a55", desvio=6.0)
        shadow_soft = doc.add_drop_shadow_filter("shadow_soft", dy=6, blur=14, opacity=0.4)

        filtros_map = {
            "glow_ciano": glow_cyan,
            "glow_ouro": glow_gold,
            "glow_vermelho": glow_red,
            "sombra_suave": shadow_soft,
        }

        # Fundo padrão suave caso não haja primeiro elemento cobrindo
        grad_bg = doc.add_linear_gradient("base_bg", [(0.0, "#0b0e14"), (1.0, "#141a24")])
        doc.draw_shape("rectangle", x=0, y=0, width=largura, height=altura, fill=grad_bg)

        for el in composicao.get("elementos", []):
            tipo = el.get("tipo")
            efeito = el.get("efeito")
            filtro_url = filtros_map.get(efeito, "")

            if tipo == "shape":
                forma = el.get("forma", "rectangle")
                if forma == "rectangle":
                    doc.draw_shape(
                        "rectangle",
                        x=el.get("x", 0),
                        y=el.get("y", 0),
                        width=el.get("largura", 100),
                        height=el.get("altura", 100),
                        radius=el.get("raio", 0),
                        fill=el.get("cor_preenchimento", "none"),
                        stroke=el.get("cor_borda", "none"),
                        stroke_width=el.get("espessura_borda", 0),
                        filter=filtro_url,
                    )
                elif forma == "ellipse":
                    doc.draw_shape(
                        "ellipse",
                        cx=el.get("x", 50),
                        cy=el.get("y", 50),
                        rx=el.get("largura", 50) / 2,
                        ry=el.get("altura", 50) / 2,
                        fill=el.get("cor_preenchimento", "none"),
                        stroke=el.get("cor_borda", "none"),
                        stroke_width=el.get("espessura_borda", 0),
                        filter=filtro_url,
                    )
                elif forma == "star":
                    doc.draw_shape(
                        "star",
                        cx=el.get("x", 50),
                        cy=el.get("y", 50),
                        radius1=el.get("raio", 30),
                        radius2=el.get("raio", 30) / 2,
                        fill=el.get("cor_preenchimento", "#ffd700"),
                        stroke=el.get("cor_borda", "none"),
                        stroke_width=el.get("espessura_borda", 0),
                        filter=filtro_url,
                    )
                elif forma == "polygon":
                    doc.draw_shape(
                        "polygon",
                        cx=el.get("x", 50),
                        cy=el.get("y", 50),
                        radius=el.get("raio", 30),
                        sides=6,
                        fill=el.get("cor_preenchimento", "none"),
                        stroke=el.get("cor_borda", "none"),
                        stroke_width=el.get("espessura_borda", 0),
                        filter=filtro_url,
                    )

            elif tipo == "line":
                doc.draw_shape(
                    "line",
                    x1=el.get("x", 0),
                    y1=el.get("y", 0),
                    x2=el.get("x", 0) + el.get("largura", 100),
                    y2=el.get("y", 0) + el.get("altura", 0),
                    stroke=el.get("cor_borda", "#ffffff"),
                    stroke_width=el.get("espessura_borda", 2),
                    filter=filtro_url,
                )

            elif tipo == "text":
                doc.add_text(
                    text=el.get("texto", ""),
                    x=el.get("x", largura / 2),
                    y=el.get("y", altura / 2),
                    font_size=el.get("tamanho_fonte", 36),
                    color=el.get("cor_preenchimento", "#ffffff"),
                    font_weight=el.get("peso_fonte", "bold"),
                    text_anchor=el.get("alinhamento", "middle"),
                    filter_url=filtro_url,
                )

        return doc

    async def criar_composicao(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        ideia: str,
        formato: str = "feed",
        estilo: str = "cyber_clean",
        temperature: float = 0.5,
    ) -> dict[str, Any]:
        """Cria uma composição vetorial completa via LLM e compila para SVG."""
        dimensoes = {
            "feed": (1080, 1350),
            "reels": (1080, 1920),
            "quadrado": (1080, 1080),
            "badge": (600, 180),
        }.get(formato, (1080, 1350))

        user_prompt = (
            f"Crie uma composição vetorial de alto impacto para o seguinte pedido:\n\n"
            f"Pedido / Ideia: {ideia}\n"
            f"Formato desejado: {formato} ({dimensoes[0]}x{dimensoes[1]})\n"
            f"Estilo visual preferido: {estilo}\n\n"
            f"Gere elementos geométricos e textuais com espaçamento harmonioso."
        )

        dados = await self.executar(
            con=con,
            perfil=perfil,
            mensagem_user=user_prompt,
            instrucoes_agente=INSTR_VECTOR_ART,
            temperature=temperature,
        )

        doc = self.compilar_doc(dados)
        svg = doc.to_svg()
        dados["svg"] = svg
        return dados

    async def salvar_e_renderizar(
        self,
        svg_content: str,
        nome_arquivo: str,
        largura: int = 1080,
        altura: int = 1350,
    ) -> tuple[Path, Path]:
        """Salva o arquivo SVG e opcionalmente gera o PNG de alta resolução."""
        dir_artes = getattr(C, "ARTES", C.DATA / "artes")
        dir_artes.mkdir(parents=True, exist_ok=True)

        svg_path = dir_artes / f"{nome_arquivo}.svg"
        png_path = dir_artes / f"{nome_arquivo}.png"

        svg_path.write_text(svg_content, encoding="utf-8")
        try:
            await renderizar_svg_para_png(svg_content, png_path, largura=largura, altura=altura)
        except Exception as e:
            logger.warning(f"Não foi possível rasterizar PNG via Chromium ({e}); SVG preservado.")
            png_path = svg_path

        return svg_path, png_path
