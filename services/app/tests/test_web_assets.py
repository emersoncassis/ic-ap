"""O escritório (SPA pixel-art) referencia bundles com hash no nome: confere que o painel serve o que a página pede."""
import re

from app import crypto, db


def test_escritorio_serve_os_assets_que_referencia(api_client):
    db.set_setting("admin_hash", crypto.hash_password("senha12345"))
    api_client.post("/login", data={"senha": "senha12345"}, follow_redirects=True)
    r = api_client.get("/escritorio")
    assert r.status_code == 200
    assert '<div id="root"></div>' in r.text and "window.__ICAP_DATA__" in r.text
    refs = re.findall(r'(?:src|href)="(/assets/[^"]+\.(?:js|css))"', r.text)
    assert refs, "a página não referencia nenhum bundle"
    for url in refs:
        assert api_client.get(url).status_code == 200, f"bundle ausente: {url}"
    for url in ("/assets/tilesets/FloorAndGround.png", "/assets/characters/char_0.png",
                "/assets/FSPixelSansUnicode-Regular-D9-dh-Uo.ttf"):
        assert api_client.get(url).status_code == 200, url


def test_post_de_outra_origem_e_recusado(client):
    r = client.post("/login", data={"senha": "x"}, headers={"origin": "https://site-malicioso.example"})
    assert r.status_code == 403
    r = client.post("/login", data={"senha": "x"}, headers={"origin": "http://testserver"})
    assert r.status_code != 403


def test_menu_tem_todas_as_telas_e_o_plano_b_de_imagens_liga_e_desliga(api_client):
    from app import settings
    db.set_setting("admin_hash", crypto.hash_password("senha12345"))
    api_client.post("/login", data={"senha": "senha12345"}, follow_redirects=True)
    pg = api_client.get("/conexoes").text
    for rota in ("/", "/pauta", "/agenda", "/historico", "/feeds", "/musicas", "/voz", "/escritorio", "/agentes", "/llm", "/perfis", "/conexoes"):
        assert f'href="{rota}"' in pg, f"menu sem link para {rota}"
    csrf = re.search(r'name="csrf" value="([a-f0-9]+)"', pg).group(1)
    anterior = db.get_setting("bancos_abertos", "1")
    try:
        api_client.post("/config/bancos_abertos", data={"csrf": csrf})            # checkbox desmarcado
        assert settings.bancos_abertos() is False
        api_client.post("/config/bancos_abertos", data={"csrf": csrf, "ligado": "on"})
        assert settings.bancos_abertos() is True
    finally:
        db.set_setting("bancos_abertos", anterior)
