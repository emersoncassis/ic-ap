"""Testes para o módulo Meta AI e detecção da técnica Blow Up."""
from app import meta_ai


def test_extrair_link_instagram():
    texto1 = "Dá uma olhada nesse reel aqui https://www.instagram.com/reel/C7xyz123/ ficou muito bom"
    assert meta_ai.extrair_link_instagram(texto1) == "https://www.instagram.com/reel/C7xyz123/"

    texto2 = "https://instagram.com/p/DA12345/?igsh=abcdef=="
    assert meta_ai.extrair_link_instagram(texto2) is not None
    assert "instagram.com/p/DA12345/" in meta_ai.extrair_link_instagram(texto2)

    texto3 = "Veja essa matéria https://g1.globo.com/tecnologia/noticia.ghtml"
    assert meta_ai.extrair_link_instagram(texto3) is None


def test_normalizar_cookies_string():
    raw = "c_user=10001234; xs=abc9876; datr=xyz555"
    cookies = meta_ai.normalizar_cookies(raw)
    assert len(cookies) == 3
    nomes = [c["name"] for c in cookies]
    assert "c_user" in nomes
    assert "xs" in nomes
    assert "datr" in nomes
    assert cookies[0]["domain"] == ".meta.ai"


def test_normalizar_cookies_json():
    json_raw = '[{"name": "c_user", "value": "10009999", "domain": ".meta.ai"}, {"name": "xs", "value": "token123"}]'
    cookies = meta_ai.normalizar_cookies(json_raw)
    assert len(cookies) == 2
    assert cookies[0]["name"] == "c_user"
    assert cookies[0]["value"] == "10009999"


def test_fallback_blow_up_sem_con():
    import asyncio
    async def _run():
        perfil = {"id": 1, "nome": "Emerson", "contexto_md": "Especialista em segurança", "llm_conexao_id": None}
        res = await meta_ai._fallback_blow_up_llm("https://instagram.com/p/teste", perfil, "prompt", "Simulação de timeout")
        assert "ok" in res
    asyncio.run(_run())


def test_testar_sessao_sem_cookies():
    import asyncio
    async def _run():
        res = await meta_ai.testar_sessao()
        assert res["ok"] is False
        assert "cookie" in res["erro"].lower()
    asyncio.run(_run())

