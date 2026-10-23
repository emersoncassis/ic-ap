"""Testes unitários para o motor e agente VectorCraft."""
from app.agentes import OrquestradorAgente, VectorArtAgente
from app.vectorcraft import (
    VectorCraftDoc,
    criar_badge_vetorial,
    criar_overlay_reels,
    criar_slide_vetorial_carrossel,
)


def test_vectorcraft_doc_primitives():
    doc = VectorCraftDoc(width=800, height=600, title="Teste Primitivas")
    glow = doc.add_glow_filter("glow_teste", cor="#00f0ff", desvio=5.0)
    shadow = doc.add_drop_shadow_filter("shadow_teste")
    grad = doc.add_linear_gradient("grad_teste", [(0.0, "#ff0000"), (1.0, "#0000ff")])

    doc.draw_shape("rectangle", x=10, y=20, width=100, height=50, radius=5, fill=grad, filter=glow)
    doc.draw_shape("ellipse", cx=200, cy=200, rx=40, ry=30, fill="#ffffff", filter=shadow)
    doc.draw_shape("polygon", cx=300, cy=300, radius=50, sides=6, fill="#00ff00")
    doc.draw_shape("star", cx=400, cy=400, radius1=40, radius2=20, points=5, fill="#ffff00")
    doc.draw_shape("line", x1=0, y1=0, x2=800, y2=600, stroke="#ffffff", stroke_width=2)
    doc.draw_path("M 10 10 C 20 20, 40 20, 50 10", stroke="#ff00ff", stroke_width=3)
    doc.add_text("TEXTO VETORIAL", x=400, y=100, font_size=32, color="#ffffff")

    svg = doc.to_svg()
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg
    assert 'viewBox="0 0 800 600"' in svg
    assert '<filter id="glow_teste"' in svg
    assert '<filter id="shadow_teste"' in svg
    assert '<linearGradient id="grad_teste"' in svg
    assert "<rect " in svg
    assert "<ellipse " in svg
    assert "<polygon " in svg
    assert "<line " in svg
    assert "<path " in svg
    assert "TEXTO VETORIAL" in svg


def test_criar_badge_vetorial_estilos():
    # Neon ciano
    svg_ciano = criar_badge_vetorial("IA LOCAL", estilo="neon_ciano", subtexto="RTX 5070")
    assert "IA LOCAL" in svg_ciano
    assert "RTX 5070" in svg_ciano
    assert "#00f0ff" in svg_ciano

    # Neon ouro
    svg_ouro = criar_badge_vetorial("VIP ACCESS", estilo="neon_ouro", subtexto="EXCLUSIVO")
    assert "VIP ACCESS" in svg_ouro
    assert "#ffd700" in svg_ouro

    # Alerta vermelho
    svg_alerta = criar_badge_vetorial("URGENTE", estilo="alerta_vermelho", subtexto="ATENÇÃO")
    assert "URGENTE" in svg_alerta
    assert "feGaussianBlur" in svg_alerta

    # Pill clean
    svg_clean = criar_badge_vetorial("EDITORIAL", estilo="pill_clean")
    assert "EDITORIAL" in svg_clean
    assert "#ffffff" in svg_clean


def test_criar_overlay_reels_safe_zones():
    svg = criar_overlay_reels(
        titulo="3 SEGREDOS DE IA",
        subtitulo="Que ninguém te conta",
        badge_texto="EXCLUSIVO",
    )
    assert 'viewBox="0 0 1080 1920"' in svg
    assert "3 SEGREDOS DE IA" in svg
    assert "Que ninguém te conta" in svg
    assert "EXCLUSIVO" in svg
    # Verifica indicação para legenda dentro da safe zone
    assert "VEJA OS DETALHES NA LEGENDA ABAIXO" in svg


def test_criar_slide_vetorial_carrossel():
    svg = criar_slide_vetorial_carrossel(
        titulo="Como Escalar Automações de Conteúdo",
        corpo="Primeiro passo: defina os canais prioritários.\nSegundo passo: integre a esteira de renderização local.",
        indice=2,
        total=7,
        badge="ESTRATÉGIA",
    )
    assert 'viewBox="0 0 1080 1350"' in svg
    assert "02 / 07" in svg
    assert "ESTRATÉGIA" in svg
    assert "Como Escalar Automações" in svg
    assert "ARRASTE PARA O LADO" in svg


def test_vector_art_agente_tools():
    agente = VectorArtAgente()

    # Tool gerar badge
    res_b = agente.gerar_badge("NOVO POST", estilo="neon_ciano")
    assert res_b["sucesso"] is True
    assert "NOVO POST" in res_b["svg"]

    # Tool overlay reels
    res_ov = agente.gerar_overlay_reels("HOOK VIRAL", subtitulo="Aprenda hoje")
    assert res_ov["sucesso"] is True
    assert res_ov["largura"] == 1080
    assert res_ov["altura"] == 1920

    # Tool slide carrossel
    res_sl = agente.gerar_slide_carrossel("Título Slide", "Texto explicativo", indice=1, total=5)
    assert res_sl["sucesso"] is True
    assert res_sl["largura"] == 1080

    # Compilar composição estruturada
    composicao = {
        "titulo_projeto": "Card Teste",
        "formato": "feed",
        "largura": 1080,
        "altura": 1350,
        "estilo_visual": "neon",
        "elementos": [
            {
                "tipo": "shape",
                "forma": "rectangle",
                "x": 100,
                "y": 100,
                "largura": 880,
                "altura": 400,
                "raio": 20,
                "cor_preenchimento": "rgba(255,255,255,0.05)",
                "cor_borda": "#00f0ff",
                "espessura_borda": 2,
                "efeito": "glow_ciano",
            },
            {
                "tipo": "text",
                "texto": "TITULO DO CARD",
                "x": 540,
                "y": 250,
                "tamanho_fonte": 48,
                "peso_fonte": "bold",
                "alinhamento": "middle",
                "cor_preenchimento": "#ffffff",
            },
        ],
    }
    doc = agente.compilar_doc(composicao)
    svg_comp = doc.to_svg()
    assert "TITULO DO CARD" in svg_comp
    assert 'stroke="#00f0ff"' in svg_comp


def test_orquestrador_comandos_vectorcraft():
    import asyncio
    orq = OrquestradorAgente()
    perfil = {"id": 1, "nome": "Emerson", "contexto_md": "Tech Leader", "palavras_chave": "ia"}
    con = {"provedor": "local", "modelo": "qwen2.5:14b", "url": "http://icap-llm:11434"}

    # Comando /badge direto
    res_b = asyncio.run(orq.processar_mensagem(con, perfil, "123", "/badge ULTRA neon_ouro | Exclusivo"))
    assert res_b["acao"] == "badge"
    assert "ULTRA" in res_b["dados"]["svg"]
    assert res_b["dados"]["estilo"] == "neon_ouro"
    assert "Badge Vetorial Gerado" in res_b["resposta_telegram"]

    # Comando /overlay direto
    res_ov = asyncio.run(orq.processar_mensagem(con, perfil, "123", "/overlay O FIM DO PROMPT MANUAL | Veja a nova era dos agentes"))
    assert res_ov["acao"] == "overlay"
    assert "O FIM DO PROMPT MANUAL" in res_ov["dados"]["svg"]
    assert "Overlay Reels 9:16 Gerado" in res_ov["resposta_telegram"]
