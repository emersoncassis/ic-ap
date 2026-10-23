import sys
import os
from pathlib import Path

# Add services/app to PYTHONPATH
app_dir = Path(__file__).resolve().parent.parent / "services" / "app"
sys.path.insert(0, str(app_dir))

# Set test environment
os.environ["DATA_DIR"] = str(app_dir / "test_data")
os.environ["SKILLS_DIR"] = str(Path(__file__).resolve().parent.parent / "skills")

import asyncio
from app import config as C, db, render
from app.agentes.skills import obter_skill, obter_prompt_skill
from app.agentes.estrategista import EstrategistaAgente
from app.agentes.diretor_arte import DiretorArteAgente
from app.agentes.critico import CriticoAgente
from app.agentes.estudio import EstudioCriativo

async def test_skills_loader():
    print("--- 1. Testing Skills Loader ---")
    skills_to_test = ["estrategista", "diretor-de-arte", "critico-visual", "caption-writer", "humanizer"]
    for s in skills_to_test:
        prompt = obter_prompt_skill(s)
        assert prompt, f"Skill '{s}' prompt is empty!"
        meta = obter_skill(s)
        print(f"  [OK] Skill '{s}': name='{meta.get('nome')}', prompt_len={len(prompt)}")

async def test_rendering_all_layouts():
    print("\n--- 2. Testing 6 Layouts Rendering (render_design) ---")
    db.init()
    await render.start()

    perfil_fake = {
        "id": 1,
        "handle": "@antigravity",
        "nome": "Studio Demo",
        "marca": "",
    }

    layouts = ["impacto_foto", "editorial", "lista", "dado", "alerta", "citacao"]
    formatos = ["feed", "story"]

    for layout in layouts:
        for fmt in formatos:
            nome_card, estourou = await render.render_design(
                layout=layout,
                formato=fmt,
                manchete=f"Teste do Layout {layout.upper()}",
                corpo="Este é um teste dinâmico do novo estúdio agêntico com visual premium.",
                palavras_destaque=[layout.upper(), "DINÂMICO"],
                itens=[
                    {"numero": "01", "titulo": "Primeiro Ponto", "descricao": "Detalhamento estratégico."},
                    {"numero": "02", "titulo": "Segundo Ponto", "descricao": "Execução com alta fidelidade."},
                    {"numero": "03", "titulo": "Terceiro Ponto", "descricao": "Resultado aprovado."},
                ],
                dado="94.8%",
                dado_legenda="Taxa de retenção verificada",
                frase_impacto="A estética certa transforma retenção em autoridade.",
                cta_texto="Toque para salvar",
                post_tipo_label="Story" if fmt == "story" else "Post de Feed",
                selo_uri=None,
                imagem_fundo_path=None,
                p=perfil_fake,
            )
            caminho = C.CARDS / nome_card
            assert caminho.exists(), f"Card file {caminho} was not created!"
            tamanho = caminho.stat().st_size
            print(f"  [OK] Layout '{layout}' ({fmt}): file={nome_card}, size={tamanho} bytes, estourou={estourou}")

    await render.stop()

async def test_critic_heuristic():
    print("\n--- 3. Testing Visual Critic (Objective Heuristic Checks) ---")
    critico = CriticoAgente()
    perfil_fake = {"id": 1, "handle": "@demo", "nome": "Demo"}
    
    # Test with a mock card file
    mock_card = Path(C.CARDS / "mock_test.png")
    mock_card.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    
    avaliacao = await critico.avaliar(
        con={"tipo": "dummy", "modelo": ""},
        perfil=perfil_fake,
        caminho_card=mock_card,
        estourou_texto=False,
        pedido="Análise sobre transporte de cargas no aeroporto de Guarulhos",
        estrategia={"fatos_verificados": ["Cargas em Guarulhos subiram 15%"], "angulo": "análise setorial"},
        copy={"manchete_card": "Guarulhos bate recorde de carga em 2026", "corpo": "Volume transportado cresce 15%."},
        direcao_arte={"layout": "dado", "paleta_cores": {"destaque": "#00f0ff"}},
    )
    print(f"  [OK] Critic heuristic score: {avaliacao.get('score')}/10, aprovado={avaliacao.get('aprovado')}")
    print(f"  [OK] Critic parecer: {avaliacao.get('parecer')}")
    mock_card.unlink(missing_ok=True)

async def test_no_hardcoded_leaks():
    print("\n--- 4. Checking for Hardcoded Leaks in Layout Templates ---")
    templates_dir = C.CARD_TEMPLATES / "layouts"
    banned_words = ["ia pública", "ia on-premise", "proteja seus dados", "tech_art_cyber.jpg"]
    
    for tpl_file in templates_dir.glob("*.html"):
        content = tpl_file.read_text(encoding="utf-8").lower()
        for bw in banned_words:
            assert bw not in content, f"Leak found: '{bw}' in template {tpl_file.name}!"
        print(f"  [OK] Template {tpl_file.name} clean of leaks.")

async def main():
    try:
        await test_skills_loader()
        await test_no_hardcoded_leaks()
        await test_rendering_all_layouts()
        await test_critic_heuristic()
        print("\n=== ALL 4 VERIFICATION SUITES PASSED! ===")
    finally:
        import shutil
        shutil.rmtree(app_dir / "test_data", ignore_errors=True)

if __name__ == "__main__":
    asyncio.run(main())
