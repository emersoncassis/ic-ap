import re
import struct
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import config as C, crypto, db, pipeline, scheduler
from tests.conftest import esperar

TOKEN = "EAAB-token-secreto-de-teste-1234"


def csrf_de(client, path="/"):
    html = client.get(path).text
    return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)


@pytest.fixture(scope="module")
def logado(client):
    r = client.post("/login", data={"senha": "senha-de-teste-123"})
    assert r.status_code == 303
    return client


def post_form(client, url, **data):
    return client.post(url, data={"csrf": csrf_de(client), **data})


def jpeg_dims(path):
    b = path.read_bytes()
    assert b[:2] == b"\xff\xd8"
    i = 2
    while i < len(b):
        marker = b[i + 1]
        if marker in (0xC0, 0xC2):
            h, w = struct.unpack(">HH", b[i + 5:i + 9])
            return w, h
        i += 2 + struct.unpack(">H", b[i + 2:i + 4])[0]


def configurar_perfil(client, ativo=False):
    post_form(client, "/perfis/1", nome="Emerson Assis", handle="@emerson_teste", ig_user_id="1784", ig_token=TOKEN,
              telegram_chat_id="42", llm_provider="ollama", llm_model="", horarios="09:00,18:00",
              palavras_chave="IA", max_idade_horas="36", contexto_md=C.CONTEXT_FILE.read_text(),
              **({"ativo": "on"} if ativo else {}))


def gerar_e_esperar(client, esperado_estado="aguardando_aprovacao"):
    antes = len(db.q("SELECT id FROM posts"))
    post_form(client, "/gerar", perfil_id="1")
    r = esperar(lambda: (lambda r: r[0] if len(r) > antes and r[0]["estado"] == esperado_estado else None)(
        db.q("SELECT * FROM posts ORDER BY id DESC")))
    esperar(lambda: 1 not in pipeline.RUNNING)
    return r


def test_exige_login(client):
    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app, follow_redirects=False)
    for rota in ("/", "/perfis", "/feeds", "/conexoes", "/historico", "/cards/" + "a" * 32 + ".jpg"):
        r = anon.get(rota)
        assert r.status_code == 303 and r.headers["location"] == "/login", rota
    assert anon.post("/gerar", data={"perfil_id": "1"}).status_code in (303, 403)
    assert "incorreta" in anon.post("/login", data={"senha": "errada"}).text


def test_seed_perfil_desligado(logado):
    p = db.one("SELECT * FROM perfis WHERE id=1")
    assert p["nome"] == "Emerson Assis" and p["ativo"] == 0
    assert "Ysafe" in p["contexto_md"]
    assert db.q("SELECT * FROM feeds WHERE perfil_id IS NULL")


def test_csrf_obrigatorio(logado):
    assert logado.post("/gerar", data={"perfil_id": "1"}).status_code == 403
    assert logado.post("/gerar", data={"perfil_id": "1", "csrf": "errado"}).status_code == 403


def test_token_criptografado_e_mascarado(logado):
    configurar_perfil(logado)
    enc = db.one("SELECT ig_token_enc FROM perfis WHERE id=1")["ig_token_enc"]
    assert TOKEN not in enc and crypto.dec(enc) == TOKEN
    html = logado.get("/perfis/1").text
    assert TOKEN not in html and "1234" in html
    configurar_perfil(logado)  # reenviar sem token não pode apagá-lo
    post_form(logado, "/perfis/1", nome="Emerson Assis", ig_token="", ig_user_id="1784", llm_provider="ollama",
              horarios="09:00", palavras_chave="IA", max_idade_horas="36", contexto_md="x")
    assert crypto.dec(db.one("SELECT ig_token_enc FROM perfis WHERE id=1")["ig_token_enc"]) == TOKEN
    configurar_perfil(logado)


def test_fluxo_completo_gerar_e_publicar(logado, fake):
    configurar_perfil(logado)
    p = gerar_e_esperar(logado)
    assert p["manchete"] == "IA vira prioridade nas empresas"
    assert "Fonte: Feed Teste" in p["legenda"]
    card = C.CARDS / p["arquivo"]
    assert jpeg_dims(card) == (1080, 1350)
    assert not (C.PUBLIC / p["arquivo"]).exists(), "o card não pode ficar público antes da aprovação"
    tg = fake.st()["tg"]
    assert any(m == "sendPhoto" and d["chat_id"] == "42" for m, d in tg)

    post_form(logado, f"/posts/{p['id']}/aprovar")
    pub = esperar(lambda: (lambda r: r if r["estado"] == "publicado" else None)(pipeline.post(p["id"])))
    assert pub["media_id"] == "MEDIA9"
    chamadas = fake.st()["graph"]
    media = next(d for t, d in chamadas if t == "media")
    assert media["image_url"].endswith(p["arquivo"]) and "Fonte: Feed Teste" in media["caption"]
    assert media["access_token"] == TOKEN
    assert any(t == "publish" for t, _ in chamadas)
    assert not (C.PUBLIC / p["arquivo"]).exists(), "a imagem pública deve ser apagada após publicar"
    assert not db.q("SELECT 1 FROM posts WHERE id=? AND erro IS NOT NULL", (p["id"],))


def test_aprovar_duas_vezes_publica_uma_vez(logado, fake):
    p = gerar_e_esperar(logado)
    post_form(logado, f"/posts/{p['id']}/aprovar")
    esperar(lambda: pipeline.post(p["id"])["estado"] == "publicado")
    post_form(logado, f"/posts/{p['id']}/aprovar")
    assert sum(1 for t, _ in fake.st()["graph"] if t == "publish") == 1


def test_llm_invalido_tenta_de_novo_com_feedback(logado, fake):
    fake.set(llm_mode="bad_then_ok")
    p = gerar_e_esperar(logado)
    users = fake.st()["llm_users"]
    assert len(users) >= 2 and "rejeitada" in users[1] and "ausente" in users[1]
    post_form(logado, f"/posts/{p['id']}/descartar")


def test_texto_longo_demais_refaz(logado, fake):
    fake.set(llm_mode="long_then_ok")
    p = gerar_e_esperar(logado)
    assert len(fake.st()["llm_users"]) >= 2
    post_form(logado, f"/posts/{p['id']}/descartar")


def test_llm_sempre_invalido_marca_falhou(logado, fake):
    fake.set(llm_mode="always_bad")
    p = gerar_e_esperar(logado, "falhou")
    assert "3 tentativas" in p["erro"]
    assert len(db.q("SELECT 1 FROM posts WHERE estado='falhou'")) <= pipeline.MAX_FALHAS  # não varre o feed todo
    assert any(m == "sendMessage" for m, _ in fake.st()["tg"])
    post_form(logado, f"/posts/{p['id']}/descartar")


def test_erro_da_meta_nao_vaza_token(logado, fake):
    p = gerar_e_esperar(logado)
    fake.set(graph_fail=True)
    post_form(logado, f"/posts/{p['id']}/aprovar")
    f = esperar(lambda: (lambda r: r if r["estado"] == "falhou" else None)(pipeline.post(p["id"])))
    assert "Invalid OAuth" in f["erro"] and TOKEN not in f["erro"]
    assert not (C.PUBLIC / p["arquivo"]).exists()
    assert TOKEN not in logado.get("/").text
    fake.set(graph_fail=False)
    post_form(logado, f"/posts/{p['id']}/aprovar")  # "tentar de novo"
    esperar(lambda: pipeline.post(p["id"])["estado"] == "publicado")


def test_refazer_troca_o_card(logado, fake):
    p = gerar_e_esperar(logado)
    post_form(logado, f"/posts/{p['id']}/refazer")
    novo = esperar(lambda: (lambda r: r if r["estado"] == "aguardando_aprovacao" and r["arquivo"] != p["arquivo"] else None)(pipeline.post(p["id"])))
    assert not (C.CARDS / p["arquivo"]).exists() and (C.CARDS / novo["arquivo"]).exists()
    post_form(logado, f"/posts/{p['id']}/descartar")
    assert pipeline.post(p["id"])["estado"] == "descartado" and not (C.CARDS / novo["arquivo"]).exists()


def test_noticia_nao_se_repete(logado, fake):
    for pid in [r["id"] for r in db.q("SELECT id FROM posts WHERE estado='aguardando_aprovacao'")]:
        post_form(logado, f"/posts/{pid}/descartar")
    urls = [r["noticia_url"] for r in db.q("SELECT noticia_url FROM posts")]
    assert len(urls) == len(set(urls)), "a mesma notícia gerou dois posts"


def test_telegram_botoes_so_do_dono(logado, fake):
    db.x("DELETE FROM posts WHERE estado!='publicado'")
    db.x("DELETE FROM posts")  # libera as notícias do feed de teste
    p = gerar_e_esperar(logado)
    fake.push(f"ds:{p['id']}", chat_id="999")  # chat de outra pessoa: ignorado
    import time; time.sleep(1.5)
    assert pipeline.post(p["id"])["estado"] == "aguardando_aprovacao"
    fake.push(f"ap:{p['id']}", chat_id=42)
    esperar(lambda: pipeline.post(p["id"])["estado"] == "publicado")
    esperar(lambda: any(m == "sendMessage" and "Publicado" in d.get("text", "") for m, d in fake.st()["tg"]))


def test_agendador_slots():
    db.x("UPDATE perfis SET ativo=1, horarios='09:00,18:00' WHERE id=1")
    tz = ZoneInfo("America/Sao_Paulo")
    assert scheduler.slots_devidos(datetime(2030, 1, 1, 8, 59, tzinfo=tz)) == []
    assert scheduler.slots_devidos(datetime(2030, 1, 1, 9, 5, tzinfo=tz)) == [(1, "09:00")]
    assert scheduler.slots_devidos(datetime(2030, 1, 1, 9, 6, tzinfo=tz)) == []      # não repete no mesmo dia
    assert scheduler.slots_devidos(datetime(2030, 1, 2, 20, 0, tzinfo=tz)) == []     # slots muito atrasados são pulados
    db.x("UPDATE perfis SET ativo=0 WHERE id=1")
    assert scheduler.slots_devidos(datetime(2030, 1, 3, 9, 5, tzinfo=tz)) == []      # perfil desligado não dispara


def test_novo_perfil_isolado(logado):
    r = post_form(logado, "/perfis", nome="Iago Carvalho", handle="@iago")
    assert r.status_code == 303
    iago = db.one("SELECT * FROM perfis WHERE nome='Iago Carvalho'")
    assert iago["ativo"] == 0 and iago["contexto_md"] == "" and iago["ig_token_enc"] == ""
    assert crypto.dec(db.one("SELECT ig_token_enc FROM perfis WHERE id=1")["ig_token_enc"]) == TOKEN


def test_conexoes(logado, fake):
    configurar_perfil(logado)
    for alvo, ok in (("meta", "emerson_teste"), ("ollama", "Ollama OK"), ("telegram", "Telegram OK"), ("publico", "URL pública OK")):
        post_form(logado, f"/conexoes/{alvo}", perfil_id="1")
        assert ok in logado.get("/conexoes").text, alvo
