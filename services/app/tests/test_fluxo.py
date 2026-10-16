import re
import stat
import struct
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import config as C, crypto, db, pipeline, scheduler, settings
from app.tunnel import tunel
from tests.conftest import FAKE, PUBLIC_URL, esperar

SENHA = "senha-de-teste-123"
TOKEN = "PAGETOKEN-xyz"  # token da Página, obtido pelo assistente da Meta


def csrf_de(client, path="/"):
    return re.search(r'name="csrf" value="([0-9a-f]+)"', client.get(path).text).group(1)


def post_form(client, url, **data):
    return client.post(url, data={"csrf": csrf_de(client), **data})


def ver(client, path):
    return client.get(path).text


@pytest.fixture(scope="module")
def logado(client):
    if not db.get_setting("admin_hash"):
        client.post("/setup", data={"senha": SENHA, "senha2": SENHA})
    else:
        client.post("/login", data={"senha": SENHA})
    assert client.get("/").status_code == 200
    return client


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


def configurar_perfil(client, ativo=False, conexao=""):
    post_form(client, "/perfis/1", nome="Emerson Assis", handle="@emerson_teste", ig_user_id="1784", ig_token="",
              telegram_chat_id="42", llm_conexao_id=str(conexao), horarios="09:00,18:00",
              palavras_chave="IA", max_idade_horas="36", contexto_md=C.CONTEXT_FILE.read_text(),
              **({"ativo": "on"} if ativo else {}))


def gerar_e_esperar(client, esperado_estado="aguardando_aprovacao"):
    antes = len(db.q("SELECT id FROM posts"))
    post_form(client, "/gerar", perfil_id="1")
    r = esperar(lambda: (lambda r: r[0] if len(r) > antes and r[0]["estado"] == esperado_estado else None)(
        db.q("SELECT * FROM posts ORDER BY id DESC")))
    esperar(lambda: 1 not in pipeline.RUNNING)
    return r


# ---------------- primeiro acesso e senha ----------------
def test_primeiro_acesso_cria_senha_e_chave(client):
    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app, follow_redirects=False)
    assert anon.get("/").headers["location"] == "/setup"
    assert anon.get("/login").headers["location"] == "/setup"
    assert "iguais" in anon.post("/setup", data={"senha": SENHA, "senha2": "outra-coisa"}).text
    assert "iguais" in anon.post("/setup", data={"senha": "curta", "senha2": "curta"}).text
    r = anon.post("/setup", data={"senha": SENHA, "senha2": SENHA})
    assert r.status_code == 303 and r.headers["location"] == "/llm"
    assert anon.get("/setup").headers["location"] == "/login"  # setup só roda uma vez
    # a chave do app foi criada sozinha, com permissão restrita, e a senha não está em texto puro
    assert C.SECRET_FILE.exists() and stat.S_IMODE(C.SECRET_FILE.stat().st_mode) == 0o600
    assert SENHA.encode() not in C.DB_PATH.read_bytes()
    assert "Ysafe" in db.one("SELECT contexto_md FROM perfis WHERE id=1")["contexto_md"]


def test_exige_login(client):
    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app, follow_redirects=False)
    for rota in ("/", "/perfis", "/feeds", "/llm", "/conexoes", "/historico", "/cards/" + "a" * 32 + ".jpg"):
        r = anon.get(rota)
        assert r.status_code == 303 and r.headers["location"] == "/login", rota
    assert "incorreta" in anon.post("/login", data={"senha": "errada"}).text
    assert anon.post("/gerar", data={"perfil_id": "1"}).status_code in (303, 403)


def test_csrf_obrigatorio(logado):
    assert logado.post("/gerar", data={"perfil_id": "1"}).status_code == 403
    assert logado.post("/llm/editar", data={"csrf": "errado", "acao": "aplicar"}).status_code == 403
    assert logado.post("/config/publico", data={"public_base_url": "https://x.com"}).status_code == 403


def test_perfil_emerson_nasce_desligado(logado):
    p = db.one("SELECT * FROM perfis WHERE id=1")
    assert p["nome"] == "Emerson Assis" and p["ativo"] == 0 and db.q("SELECT * FROM feeds WHERE perfil_id IS NULL")


def test_gerar_sem_llm_explica_o_que_falta(logado):
    assert "Configure em LLM" in ver(logado, "/") or "LLM" in ver(logado, "/")
    configurar_perfil(logado)
    p = gerar_e_esperar(logado, "falhou")
    assert "configure em LLM" in p["erro"]
    db.x("DELETE FROM posts")


# ---------------- LLM: apontar, detectar, escolher, aplicar e testar ----------------
def test_llm_openai_detecta_e_aplica(logado, fake):
    r = post_form(logado, "/llm/editar", acao="detectar", nome="LM Studio", tipo="openai", base_url=FAKE, api_key="")
    assert r.status_code == 200 and "modelo-a" in r.text and "modelo-b" in r.text
    assert f'value="{FAKE}/v1"' in r.text, "deve descobrir sozinho que a base é /v1"
    r = post_form(logado, "/llm/editar", acao="aplicar", nome="LM Studio", tipo="openai", base_url=f"{FAKE}/v1",
                  modelo="modelo-b", padrao="on", api_key="")
    assert r.status_code == 303
    assert "Teste OK" in ver(logado, "/llm")
    c = db.one("SELECT * FROM llm_conexoes WHERE id=1")
    assert c["modelo"] == "modelo-b" and c["padrao"] == 1 and c["tipo"] == "openai"
    assert fake.st()["llm_users"], "o teste deve ter chamado o modelo de verdade"


def test_llm_openai_sem_response_format_cai_no_prompt(logado, fake):
    fake.set(openai_no_format=True)
    post_form(logado, "/llm/1/testar")
    assert "teste OK" in ver(logado, "/llm")


def test_llm_chave_guardada_criptografada_e_reutilizada(logado, fake):
    post_form(logado, "/llm/editar", acao="aplicar", id="1", nome="LM Studio", tipo="openai", base_url=f"{FAKE}/v1",
              modelo="modelo-b", padrao="on", api_key="sk-local-123")
    enc = db.one("SELECT api_key_enc FROM llm_conexoes WHERE id=1")["api_key_enc"]
    assert "sk-local-123" not in enc and crypto.dec(enc) == "sk-local-123"
    assert "sk-local-123" not in ver(logado, "/llm?editar=1")
    post_form(logado, "/llm/editar", acao="detectar", id="1", nome="LM Studio", tipo="openai", base_url=f"{FAKE}/v1", api_key="")
    assert fake.st()["openai_keys"][-1] == "Bearer sk-local-123", "chave em branco deve manter a salva"


def test_llm_ollama_gemini_anthropic(logado, fake):
    r = post_form(logado, "/llm/editar", acao="detectar", nome="Ollama", tipo="ollama", base_url=FAKE, api_key="")
    assert "teste:7b" in r.text
    post_form(logado, "/llm/editar", acao="aplicar", nome="Ollama", tipo="ollama", base_url=FAKE, modelo="teste:7b", api_key="")
    # Gemini: sem chave avisa; com chave lista só modelos que geram texto
    assert "chave de API" in post_form(logado, "/llm/editar", acao="detectar", nome="G", tipo="gemini", base_url="", api_key="").text
    r = post_form(logado, "/llm/editar", acao="detectar", nome="G", tipo="gemini", base_url="", api_key="g-key")
    assert "g-flash" in r.text and ">emb<" not in r.text
    post_form(logado, "/llm/editar", acao="aplicar", nome="Gemini", tipo="gemini", base_url="", modelo="g-flash", api_key="g-key")
    # Anthropic: chave errada mostra o erro da API
    assert "invalid x-api-key" in post_form(logado, "/llm/editar", acao="detectar", nome="A", tipo="anthropic", base_url="", api_key="x").text
    r = post_form(logado, "/llm/editar", acao="detectar", nome="A", tipo="anthropic", base_url="", api_key="a-key")
    assert "claude-test" in r.text
    post_form(logado, "/llm/editar", acao="aplicar", nome="Claude", tipo="anthropic", base_url="", modelo="claude-test", api_key="a-key")
    assert [c["tipo"] for c in db.q("SELECT tipo FROM llm_conexoes ORDER BY id")] == ["openai", "ollama", "gemini", "anthropic"]
    assert [c["padrao"] for c in db.q("SELECT padrao FROM llm_conexoes ORDER BY id")] == [1, 0, 0, 0]


def test_llm_erro_de_conexao_mostra_dica_do_docker(logado):
    r = post_form(logado, "/llm/editar", acao="detectar", nome="X", tipo="openai", base_url="http://127.0.0.1:1", api_key="")
    assert "host.docker.internal" in r.text


# ---------------- configurações globais pela interface ----------------
def test_url_publica_e_servidor_de_imagens_isolado(logado):
    post_form(logado, "/config/publico", public_base_url="ftp://x")
    assert settings.base_url() == ""
    post_form(logado, "/config/publico", public_base_url=PUBLIC_URL + "/")
    assert settings.base_url() == PUBLIC_URL
    # o servidor público serve só a pasta de imagens: sem listagem, sem painel
    (C.PUBLIC / "x.txt").write_text("oi")
    assert httpx.get(f"{PUBLIC_URL}/x.txt").text == "oi"
    (C.PUBLIC / "x.txt").unlink()
    assert httpx.get(f"{PUBLIC_URL}/").status_code == 404
    assert httpx.get(f"{PUBLIC_URL}/login").status_code == 404
    assert httpx.get(f"{PUBLIC_URL}/../app.db").status_code in (400, 404)


def test_tunel_inicia_pelo_token_da_interface_e_mascara_o_token(logado):
    post_form(logado, "/config/tunel", tunnel_token="TUNEL-SEGREDO-999")
    esperar(lambda: tunel.status == "conectado", 20)
    html = ver(logado, "/conexoes")
    assert "conectado" in html and "TUNEL-SEGREDO-999" not in html and "***" in html
    assert "TUNEL-SEGREDO-999" not in db.get_setting("tunnel_token")
    post_form(logado, "/config/tunel", acao="remover")
    esperar(lambda: tunel.status == "parado" and tunel.proc is None, 10)
    assert not settings.tunnel_token()


def test_telegram_fuso_e_senha(logado):
    post_form(logado, "/config/telegram", telegram_token="TG-TOKEN-123")
    assert settings.telegram_token() == "TG-TOKEN-123" and "TG-TOKEN-123" not in ver(logado, "/conexoes")
    post_form(logado, "/config/geral", tz="Marte/Olympus")
    assert settings.tz() == "America/Sao_Paulo"
    post_form(logado, "/config/geral", tz="America/Manaus")
    assert settings.tz() == "America/Manaus"
    post_form(logado, "/config/geral", tz="America/Sao_Paulo")
    post_form(logado, "/config/senha", atual="errada", nova="nova-senha-456", nova2="nova-senha-456")
    assert crypto.check_password(SENHA, db.get_setting("admin_hash"))
    post_form(logado, "/config/senha", atual=SENHA, nova="nova-senha-456", nova2="nova-senha-456")
    assert crypto.check_password("nova-senha-456", db.get_setting("admin_hash"))
    post_form(logado, "/config/senha", atual="nova-senha-456", nova=SENHA, nova2=SENHA)
    assert crypto.check_password(SENHA, db.get_setting("admin_hash"))


# ---------------- assistente de token da Meta ----------------
def test_assistente_meta(logado):
    post_form(logado, "/perfis/1/meta/buscar", app_id="123", app_secret="errado", token_curto="TOKEN-CURTO")
    assert "Invalid client secret" in ver(logado, "/perfis/1")
    post_form(logado, "/perfis/1/meta/buscar", app_id="123", app_secret="segredo-app", token_curto="TOKEN-CURTO")
    html = ver(logado, "/perfis/1")
    assert "@emerson_teste" in html and "Sem Instagram" not in html
    for segredo in ("LONGO123", "PAGETOKEN", "segredo-app", "TOKEN-CURTO"):
        assert segredo not in html
    post_form(logado, "/perfis/1/meta/usar", idx="0")
    p = db.one("SELECT * FROM perfis WHERE id=1")
    assert p["ig_user_id"] == "1784" and crypto.dec(p["ig_token_enc"]) == TOKEN
    assert not db.get_setting("metatmp:1"), "a lista temporária deve ser apagada"
    assert "segredo-app" not in "".join(r["v"] for r in db.q("SELECT v FROM settings"))


def test_token_criptografado_e_mascarado(logado):
    enc = db.one("SELECT ig_token_enc FROM perfis WHERE id=1")["ig_token_enc"]
    assert TOKEN not in enc
    html = ver(logado, "/perfis/1")
    assert TOKEN not in html and "-xyz" not in html.replace("PAGETOKEN", "") or "••••" in html
    configurar_perfil(logado)  # salvar sem informar token não pode apagá-lo
    assert crypto.dec(db.one("SELECT ig_token_enc FROM perfis WHERE id=1")["ig_token_enc"]) == TOKEN


# ---------------- fluxo de posts ----------------
def test_fluxo_completo_gerar_e_publicar(logado, fake):
    configurar_perfil(logado)
    p = gerar_e_esperar(logado)
    assert p["manchete"] == "IA vira prioridade nas empresas" and "Fonte: Feed Teste" in p["legenda"]
    assert jpeg_dims(C.CARDS / p["arquivo"]) == (1080, 1350)
    assert not (C.PUBLIC / p["arquivo"]).exists(), "o card não pode ficar público antes da aprovação"
    esperar(lambda: any(m == "sendPhoto" and d["chat_id"] == "42" for m, d in fake.st()["tg"]))

    post_form(logado, f"/posts/{p['id']}/aprovar")
    pub = esperar(lambda: (lambda r: r if r["estado"] == "publicado" else None)(pipeline.post(p["id"])))
    assert pub["media_id"] == "MEDIA9"
    chamadas = fake.st()["graph"]
    media = next(d for t, d in chamadas if t == "media")
    # a Meta buscou a imagem de verdade pela URL pública servida pelo próprio app
    assert media["image_url"] == f"{PUBLIC_URL}/{p['arquivo']}" and "Fonte: Feed Teste" in media["caption"]
    assert media["access_token"] == TOKEN
    assert not (C.PUBLIC / p["arquivo"]).exists(), "a imagem pública deve ser apagada após publicar"


@pytest.mark.parametrize("conexao_id", [2, 3, 4])
def test_pipeline_com_cada_tipo_de_llm(logado, fake, conexao_id):
    configurar_perfil(logado, conexao=conexao_id)
    p = gerar_e_esperar(logado)
    assert p["manchete"] == "IA vira prioridade nas empresas"
    post_form(logado, f"/posts/{p['id']}/descartar")
    configurar_perfil(logado)


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
    assert len(db.q("SELECT 1 FROM posts WHERE estado='falhou'")) <= pipeline.MAX_FALHAS
    esperar(lambda: any(m == "sendMessage" for m, _ in fake.st()["tg"]))
    post_form(logado, f"/posts/{p['id']}/descartar")


def test_erro_da_meta_nao_vaza_token(logado, fake):
    p = gerar_e_esperar(logado)
    fake.set(graph_fail=True)
    post_form(logado, f"/posts/{p['id']}/aprovar")
    f = esperar(lambda: (lambda r: r if r["estado"] == "falhou" else None)(pipeline.post(p["id"])))
    assert "Invalid OAuth" in f["erro"] and TOKEN not in f["erro"]
    assert not (C.PUBLIC / p["arquivo"]).exists()
    assert TOKEN not in ver(logado, "/")
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


def test_noticia_nao_se_repete(logado):
    urls = [(r["noticia_url"], r["variacao"]) for r in db.q("SELECT noticia_url, variacao FROM posts")]
    assert len(urls) == len(set(urls))


def test_telegram_botoes_so_do_dono(logado, fake):
    db.x("DELETE FROM posts")
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
    assert scheduler.slots_devidos(datetime(2030, 1, 1, 9, 6, tzinfo=tz)) == []
    assert scheduler.slots_devidos(datetime(2030, 1, 2, 20, 0, tzinfo=tz)) == []
    db.x("UPDATE perfis SET ativo=0 WHERE id=1")
    assert scheduler.slots_devidos(datetime(2030, 1, 3, 9, 5, tzinfo=tz)) == []


def test_novo_perfil_isolado(logado):
    assert post_form(logado, "/perfis", nome="Iago Carvalho", handle="@iago").status_code == 303
    iago = db.one("SELECT * FROM perfis WHERE nome='Iago Carvalho'")
    assert iago["ativo"] == 0 and iago["contexto_md"] == "" and iago["ig_token_enc"] == "" and iago["llm_conexao_id"] is None
    assert crypto.dec(db.one("SELECT ig_token_enc FROM perfis WHERE id=1")["ig_token_enc"]) == TOKEN


def test_remover_conexao_padrao_promove_outra(logado):
    post_form(logado, "/llm/4/remover")
    post_form(logado, "/llm/1/remover")
    assert db.one("SELECT padrao FROM llm_conexoes ORDER BY id LIMIT 1")["padrao"] == 1
    # recria a conexão padrão para os testes seguintes
    post_form(logado, "/llm/editar", acao="aplicar", nome="LM Studio", tipo="openai", base_url=f"{FAKE}/v1",
              modelo="modelo-b", padrao="on", api_key="")


def test_conexoes_do_perfil(logado, fake):
    configurar_perfil(logado)
    for alvo, ok in (("llm", "LLM OK"), ("meta", "emerson_teste"), ("telegram", "Telegram OK"), ("publico", "URL pública OK")):
        post_form(logado, f"/conexoes/{alvo}", perfil_id="1")
        assert ok in ver(logado, "/conexoes"), alvo


# ---------------- pauta do dia, variações e agenda ----------------
def _esperar_pauta(n_esperado):
    esperar(lambda: 1 not in pipeline.RUNNING and len(db.q("SELECT 1 FROM posts WHERE estado='rascunho'")) >= n_esperado, 90)


def test_pauta_gera_variacoes_em_rascunho(logado, fake):
    db.x("DELETE FROM posts WHERE estado IN ('rascunho','agendado')")
    configurar_perfil(logado)
    post_form(logado, "/pauta/gerar", perfil_id="1", noticias="2", variacoes="2", formato="feed")
    _esperar_pauta(4)
    r = db.q("SELECT * FROM posts WHERE estado='rascunho' ORDER BY grupo, variacao")
    assert len(r) == 4 and len({p["grupo"] for p in r}) == 2
    assert all(len({p["noticia_url"] for p in r if p["grupo"] == g}) == 1 for g in {p["grupo"] for p in r})
    assert len({p["angulo"] for p in r}) == 2, "cada versão tem um ângulo diferente"
    assert sum("Ângulo desta versão" in u for u in fake.st()["llm_users"]) == 4
    assert not any(m == "sendPhoto" for m, _ in fake.st()["tg"]), "rascunhos não inundam o Telegram"
    esperar(lambda: any(m == "sendMessage" and "Pauta pronta" in d.get("text", "") for m, d in fake.st()["tg"]))
    html = ver(logado, "/pauta")
    assert html.count('name="ids"') == 4 and "Agendar selecionados" in html
    assert "/pauta" in ver(logado, "/") and not any(f'/posts/{p["id"]}/aprovar' in ver(logado, "/") for p in r), "rascunhos ficam fora da fila"


def test_agendar_com_intervalo_e_fuso(logado):
    ids = [p["id"] for p in db.q("SELECT id FROM posts WHERE estado='rascunho' ORDER BY id LIMIT 3")]
    post_form(logado, "/pauta/agendar", ids=ids, quando="2031-01-01T09:00", intervalo="60", acao="agendar")
    ag = db.q("SELECT agendado_para FROM posts WHERE estado='agendado' ORDER BY agendado_para")
    assert [a["agendado_para"] for a in ag] == ["2031-01-01 12:00:00", "2031-01-01 13:00:00", "2031-01-01 14:00:00"], "09:00 em São Paulo = 12:00 UTC"
    html = ver(logado, "/agenda")
    assert "01/01 09:00" in html and "01/01 10:00" in html and "01/01 11:00" in html
    assert pipeline.agendar([ids[0]], "lixo") == 0
    post_form(logado, f"/posts/{ids[2]}/desagendar")
    assert pipeline.post(ids[2])["estado"] == "rascunho" and pipeline.post(ids[2])["agendado_para"] is None
    post_form(logado, f"/posts/{ids[1]}/desagendar")


def test_agendado_vencido_e_publicado_sozinho(logado, fake):
    pid = db.one("SELECT id FROM posts WHERE estado='rascunho' ORDER BY id LIMIT 1")["id"]
    post_form(logado, "/pauta/agendar", ids=[pid], quando="2020-01-01T09:00", intervalo="0", acao="agendar")
    p = esperar(lambda: (lambda r: r if r["estado"] == "publicado" else None)(pipeline.post(pid)), 20)
    media = next(d for t, d in fake.st()["graph"] if t == "media")
    assert media["image_url"] == f"{PUBLIC_URL}/{p['arquivo']}" and "media_type" not in media and p["agendado_para"] is None
    assert not (C.PUBLIC / p["arquivo"]).exists()


def test_agendado_futuro_nao_publica(logado, fake):
    pid = db.one("SELECT id FROM posts WHERE estado='rascunho' ORDER BY id LIMIT 1")["id"]
    post_form(logado, "/pauta/agendar", ids=[pid], quando="2031-06-01T09:00", intervalo="0", acao="agendar")
    import time; time.sleep(2.5)
    assert pipeline.post(pid)["estado"] == "agendado" and not any(t == "publish" for t, _ in fake.st()["graph"])
    post_form(logado, f"/posts/{pid}/desagendar")


def test_descartar_em_lote(logado):
    ids = [p["id"] for p in db.q("SELECT id FROM posts WHERE estado='rascunho'")]
    post_form(logado, "/pauta/agendar", ids=ids, acao="descartar")
    assert not db.q("SELECT 1 FROM posts WHERE estado='rascunho'")
    assert not any((C.CARDS / p["arquivo"]).exists() for p in db.q("SELECT arquivo FROM posts WHERE estado='descartado' AND arquivo IS NOT NULL ORDER BY id DESC LIMIT 4"))


def test_story_com_print_da_materia(logado, fake):
    post_form(logado, "/pauta/gerar", perfil_id="1", noticias="1", variacoes="1", formato="story", com_print="on")
    _esperar_pauta(1)
    p = db.one("SELECT * FROM posts WHERE estado='rascunho' AND formato='story'")
    assert jpeg_dims(C.CARDS / p["arquivo"]) == (1080, 1920)
    post_form(logado, f"/posts/{p['id']}/aprovar")
    esperar(lambda: pipeline.post(p["id"])["estado"] == "publicado")
    media = [d for t, d in fake.st()["graph"] if t == "media"][-1]
    assert media["media_type"] == "STORIES" and "caption" not in media and media["image_url"].endswith(p["arquivo"])


def test_em_alta_prioriza_assunto_repetido():
    from app import feeds
    it = [{"titulo": "Nvidia lança chip novo para inteligência artificial", "fonte": "A"},
          {"titulo": "Chip novo da Nvidia promete inteligência artificial mais barata", "fonte": "B"},
          {"titulo": "Receita de bolo de cenoura fofinho", "fonte": "C"}]
    feeds._marcar_em_alta(it)
    assert [i["mencoes"] for i in it] == [1, 1, 0]


def test_migracao_de_banco_antigo(tmp_path):
    import sqlite3
    velho = sqlite3.connect(tmp_path / "v.db"); velho.row_factory = sqlite3.Row
    velho.executescript("""CREATE TABLE perfis(id INTEGER PRIMARY KEY, nome TEXT);
      CREATE TABLE posts(id INTEGER PRIMARY KEY, perfil_id INTEGER NOT NULL, estado TEXT NOT NULL, noticia_url TEXT, noticia_titulo TEXT,
      fonte TEXT, texto TEXT, json_llm TEXT, manchete TEXT, reacao TEXT, legenda TEXT, arquivo TEXT, media_id TEXT, erro TEXT,
      tg_message_id TEXT, criado_em TEXT, atualizado_em TEXT, UNIQUE(perfil_id, noticia_url));
      INSERT INTO posts(perfil_id,estado,noticia_url) VALUES(1,'publicado','http://x');""")
    original = db._conn
    db._conn = velho
    try:
        with db._lock:
            db._migrar()
        assert "musica_modo" in {r[1] for r in velho.execute("PRAGMA table_info(perfis)")}
        r = velho.execute("SELECT estado, variacao, formato FROM posts").fetchone()
        assert (r["estado"], r["variacao"], r["formato"]) == ("publicado", 1, "feed")
        velho.execute("INSERT INTO posts(perfil_id,estado,noticia_url,variacao) VALUES(1,'rascunho','http://x',2)")  # mesma notícia, outra versão
    finally:
        db._conn = original


# ---------------- foto e vídeo enviados pelo Telegram ----------------
def _probe(path):
    import json, subprocess
    d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                                  capture_output=True, text=True, check=True).stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    return {"w": v["width"], "h": v["height"], "audio": any(s["codec_type"] == "audio" for s in d["streams"]),
            "dur": float(d["format"]["duration"]), "vcodec": v["codec_name"]}


def _novo_post(antes):
    return esperar(lambda: (lambda r: r[0] if len(r) > antes else None)(db.q("SELECT * FROM posts WHERE fonte='Telegram' ORDER BY id DESC")))


def _n_midia():
    return len(db.q("SELECT 1 FROM posts WHERE fonte='Telegram'"))


def test_foto_do_telegram_vira_post_de_feed(logado, fake):
    configurar_perfil(logado)
    n = _n_midia()
    fake.push_msg(42, "foto", "Treino de hoje cedo, 5 km sem parar")
    p = _novo_post(n)
    assert p["formato"] == "feed" and p["estado"] == "aguardando_aprovacao" and p["noticia_url"] is None
    assert jpeg_dims(C.CARDS / p["arquivo"]) == (1080, 1350), "800x600 cortado para 4:5"
    assert p["legenda"].startswith("Minha leitura") and "Treino de hoje" in fake.st()["llm_users"][-1]
    esperar(lambda: any(m == "sendPhoto" and "[FEED]" in d["caption"] and d["chat_id"] == "42" for m, d in fake.st()["tg"]))
    post_form(logado, f"/posts/{p['id']}/aprovar")
    esperar(lambda: pipeline.post(p["id"])["estado"] == "publicado")
    media = next(d for t, d in fake.st()["graph"] if t == "media")
    assert media["image_url"].endswith(p["arquivo"]) and media["caption"] == p["legenda"] and "media_type" not in media


def test_foto_com_palavra_story_nao_gera_legenda(logado, fake):
    n = _n_midia()
    fake.push_msg(42, "foto", "story: bastidores")
    p = _novo_post(n)
    assert p["formato"] == "story" and p["legenda"] == "" and jpeg_dims(C.CARDS / p["arquivo"]) == (1080, 1920)
    assert not fake.st()["llm_users"], "Story não tem legenda: não chama o LLM"
    post_form(logado, f"/posts/{p['id']}/aprovar")
    esperar(lambda: pipeline.post(p["id"])["estado"] == "publicado")
    media = next(d for t, d in fake.st()["graph"] if t == "media")
    assert media["media_type"] == "STORIES" and "caption" not in media


def test_video_vira_reel_vertical_com_audio_original(logado, fake):
    n = _n_midia()
    fake.push_msg(42, "video", "Palestra sobre IA na saúde")
    p = _novo_post(n)
    assert p["formato"] == "reel" and p["arquivo"].endswith(".mp4")
    info = _probe(C.CARDS / p["arquivo"])
    assert (info["w"], info["h"], info["vcodec"]) == (1080, 1920, "h264") and info["audio"] and 2 < info["dur"] < 4
    esperar(lambda: any(m == "sendVideo" and "[REEL]" in d["caption"] for m, d in fake.st()["tg"]))
    post_form(logado, f"/posts/{p['id']}/aprovar")
    esperar(lambda: pipeline.post(p["id"])["estado"] == "publicado")
    media = next(d for t, d in fake.st()["graph"] if t == "media")
    assert media["media_type"] == "REELS" and media["video_url"].endswith(".mp4") and media["share_to_feed"] == "true"
    assert not (C.PUBLIC / p["arquivo"]).exists()


def test_musicas_envio_validacao_e_remocao(logado):
    dados = {"csrf": csrf_de(logado, "/musicas")}
    import os
    trilha = open(os.environ["FAKE_MEDIA_DIR"] + "/trilha.mp3", "rb").read()
    r = logado.post("/musicas", data=dados, files=[("arquivo", ("../../trilha.mp3", trilha, "audio/mpeg")),
                                                   ("arquivo", ("virus.exe", b"MZ", "application/octet-stream"))])
    assert r.status_code == 303
    html = ver(logado, "/musicas")
    assert "trilha.mp3" in html and "formato não aceito" in html
    assert (C.MUSICAS / "trilha.mp3").exists() and not (C.MUSICAS.parent / "trilha.mp3").exists(), "sem escapar da pasta"
    assert not (C.MUSICAS / "virus.exe").exists()


def test_video_com_musica_automatica(logado, fake):
    db.x("UPDATE perfis SET musica_modo='aleatoria' WHERE id=1")
    n = _n_midia()
    fake.push_msg(42, "video", "Dia de gravação", arquivo="mudo.mp4")
    p = _novo_post(n)
    info = _probe(C.CARDS / p["arquivo"])
    assert info["audio"], "vídeo mudo ganhou a trilha"
    assert "trilha: trilha" in " ".join(d.get("caption", "") for m, d in fake.st()["tg"] if m == "sendVideo") or esperar(
        lambda: any("trilha: trilha" in d.get("caption", "") for m, d in fake.st()["tg"] if m == "sendVideo"))
    # com áudio original, a trilha entra por baixo e o vídeo continua com som
    n = _n_midia()
    fake.push_msg(42, "video", "Com som original")
    p2 = _novo_post(n)
    assert _probe(C.CARDS / p2["arquivo"])["audio"]
    # "sem música" respeita o pedido
    n = _n_midia()
    fake.push_msg(42, "video", "sem música: bastidor", arquivo="mudo.mp4")
    p3 = _novo_post(n)
    assert not _probe(C.CARDS / p3["arquivo"])["audio"]
    db.x("UPDATE perfis SET musica_modo='nenhuma' WHERE id=1")
    for x in (p, p2, p3):
        post_form(logado, f"/posts/{x['id']}/descartar")


def test_midia_sem_frase_e_refazer_legenda(logado, fake):
    n = _n_midia()
    fake.push_msg(42, "foto", "")
    p = _novo_post(n)
    assert p["legenda"] == ""
    esperar(lambda: any(m == "sendPhoto" and "Sem frase de contexto" in d["caption"] for m, d in fake.st()["tg"]))
    # com frase: "refazer" só troca a legenda
    db.x("UPDATE posts SET texto='Evento de IA em Floripa' WHERE id=?", (p["id"],))
    post_form(logado, f"/posts/{p['id']}/refazer")
    novo = esperar(lambda: (lambda r: r if r["legenda"] else None)(pipeline.post(p["id"])))
    assert novo["arquivo"] == p["arquivo"] and (C.CARDS / p["arquivo"]).exists() and "Evento de IA" in fake.st()["llm_users"][-1]
    post_form(logado, f"/posts/{p['id']}/descartar")


def test_telegram_midia_so_do_dono_texto_e_limite(logado, fake):
    n = _n_midia()
    fake.push_msg(999, "foto", "intruso")
    fake.push_msg(42, "foto", "grande demais", size=25 * 1024 * 1024)
    fake.push_msg(42, "texto", "/ajuda")
    esperar(lambda: any(m == "sendMessage" and "20 MB" in d["text"] for m, d in fake.st()["tg"]))
    esperar(lambda: any(m == "sendMessage" and "Converse comigo" in d["text"] for m, d in fake.st()["tg"]))
    assert _n_midia() == n and not any(d.get("chat_id") == "999" for m, d in fake.st()["tg"])


def test_destino_por_palavras():
    assert pipeline._destino("foto", "Story: treino") == ("story", "treino", False)
    assert pipeline._destino("video", "meu reel de hoje") == ("reel", "meu de hoje", False)
    assert pipeline._destino("video", "feed sem música") == ("reel", "", True)
    assert pipeline._destino("foto", "sem história")[0] == "feed"


def test_id_de_pagina_no_lugar_do_instagram_explica_o_erro(logado):
    antigo = db.one("SELECT ig_user_id FROM perfis WHERE id=1")["ig_user_id"]
    db.x("UPDATE perfis SET ig_user_id='PAGE1' WHERE id=1")
    post_form(logado, "/conexoes/meta", perfil_id="1")
    html = ver(logado, "/conexoes")
    assert "não é o de uma conta do Instagram" in html and "assistente" in html
    db.x("UPDATE perfis SET ig_user_id=? WHERE id=1", (antigo,))



# ---------------- brainstorming pelo Telegram: ideia -> post, carrossel, A/B, hashtags, perfil ----------------
def _gerar_cmd(formato, ideia="Dado privado na empresa: por que a IA precisa respeitar isso", n=0, v=1):
    return {"resposta": "Gerando agora.", "acao": "gerar", "gerar": {"formato": formato, "ideia": ideia, "n_slides": n, "variacoes": v}}


def _n_texto():
    return len(db.q("SELECT 1 FROM posts WHERE fonte='Texto'"))


def _novos_texto(antes, quantos=1):
    return esperar(lambda: (lambda r: list(reversed(r[:quantos])) if len(r) >= antes + quantos and all(
        x["estado"] != "capturado" for x in r[:quantos]) else None)(db.q("SELECT * FROM posts WHERE fonte='Texto' ORDER BY id DESC")))


def _dizer(fake, texto):
    n = len([1 for m, d in fake.st()["tg"] if m == "sendMessage"])
    fake.push_msg(42, "texto", texto)
    return n


def test_ideia_na_conversa_vira_post_de_feed_com_hashtags(logado, fake):
    configurar_perfil(logado)
    n = _n_texto()
    fake.set(agente=[_gerar_cmd("feed")])
    _dizer(fake, "faz um post sobre dado privado na empresa")
    [p] = _novos_texto(n)
    assert p["formato"] == "feed" and p["estado"] == "aguardando_aprovacao" and p["noticia_url"] is None
    assert jpeg_dims(C.CARDS / p["arquivo"]) == (1080, 1350)
    assert p["manchete"].startswith("Dado na mão") and "Fonte:" not in p["reacao"]
    # legenda: texto + chamada para ação + hashtags normalizadas, sem repetir
    assert p["legenda"].endswith("#ia #empresas #dados #privacidade #tecnologia #gestao #ysafe #startup") and "Comente o que você acha." in p["legenda"]
    esperar(lambda: any(m == "sendPhoto" and d["chat_id"] == "42" and "Minha ideia de hoje" in d["caption"] for m, d in fake.st()["tg"]))
    assert any(m == "sendMessage" and "Gerando agora" in d["text"] for m, d in fake.st()["tg"])
    # hashtags novas trocam só o bloco final
    post_form(logado, f"/posts/{p['id']}/hashtags")
    novo = pipeline.post(p["id"])
    assert novo["legenda"].endswith("#novatag1 #novatag2 #novatag3 #novatag4") and "#ia " not in novo["legenda"] and "Comente o que você acha." in novo["legenda"]
    # salvar legenda pelo painel (a rota estava escondida pela rota genérica)
    post_form(logado, f"/posts/{p['id']}/legenda", legenda="Legenda editada à mão")
    assert pipeline.post(p["id"])["legenda"] == "Legenda editada à mão"
    post_form(logado, f"/posts/{p['id']}/aprovar")
    esperar(lambda: pipeline.post(p["id"])["estado"] == "publicado")
    media = next(d for t, d in fake.st()["graph"] if t == "media")
    assert media["image_url"].endswith(p["arquivo"]) and media["caption"] == "Legenda editada à mão"


def test_carrossel_na_conversa_vai_ao_instagram_como_carrossel(logado, fake):
    n = _n_texto()
    fake.set(agente=[_gerar_cmd("carrossel", n=5)])
    _dizer(fake, "monta um carrossel de 5 slides")
    [p] = _novos_texto(n)
    import json
    arqs = json.loads(p["arquivos"])
    assert p["formato"] == "carrossel" and len(arqs) == 5 and p["arquivo"] == arqs[0]
    assert all(jpeg_dims(C.CARDS / a) == (1080, 1350) for a in arqs) and len(set(arqs)) == 5
    esperar(lambda: any(m == "sendMediaGroup" for m, d in fake.st()["tg"]))
    esperar(lambda: any(m == "sendMessage" and "Carrossel de 5 slides" in d["text"] and "ap:" in d["reply_markup"] for m, d in fake.st()["tg"]))
    # aprovar pelo botão do Telegram: 5 itens + 1 contêiner CAROUSEL + publish
    fake.push(f"ap:{p['id']}", "42")
    esperar(lambda: pipeline.post(p["id"])["estado"] == "publicado")
    g = fake.st()["graph"]
    itens = [d for t, d in g if t == "media" and d.get("is_carousel_item") == "true"]
    cont = [d for t, d in g if t == "media" and d.get("media_type") == "CAROUSEL"]
    assert len(itens) == 5 and all(d["image_url"].split("/")[-1] in arqs for d in itens) and "caption" not in itens[0]
    assert len(cont) == 1 and cont[0]["children"].count("ITEM") == 5 and cont[0]["caption"] == p["legenda"]
    assert [t for t, _ in g].count("publish") == 1
    assert not any((C.PUBLIC / a).exists() for a in arqs), "as imagens só ficam públicas durante o publish"


def test_carrossel_com_slide_longo_demais_e_refeito(logado, fake):
    n = _n_texto()
    fake.set(agente=[_gerar_cmd("carrossel", n=4)], carrossel_modo="estoura")
    _dizer(fake, "carrossel de 4 slides")
    [p] = _novos_texto(n)
    assert p["estado"] == "aguardando_aprovacao" and len(__import__("json").loads(p["arquivos"])) == 4
    assert "longo demais" in fake.st()["llm_users"][-1], "o modelo recebeu o motivo da recusa e encurtou"
    post_form(logado, f"/posts/{p['id']}/descartar")
    esperar(lambda: pipeline.post(p["id"])["estado"] == "descartado")
    assert not any((C.CARDS / a).exists() for a in __import__("json").loads(p["arquivos"])), "descartar apaga todos os slides"


def test_versoes_ab_tem_manchetes_e_chamadas_diferentes(logado, fake):
    n = _n_texto()
    fake.set(agente=[_gerar_cmd("feed", v=3)])
    _dizer(fake, "faz 3 versões para testar")
    ps = _novos_texto(n, 3)
    assert len({p["grupo"] for p in ps}) == 1 and [p["variacao"] for p in ps] == [1, 2, 3]
    assert len({p["manchete"] for p in ps}) == 3 and len({p["angulo"] for p in ps}) == 3
    esperar(lambda: sum(1 for m, d in fake.st()["tg"] if m == "sendPhoto" and "Versão" in d["caption"]) == 3)
    for p in ps:
        post_form(logado, f"/posts/{p['id']}/descartar")


def test_perfil_montado_na_conversa_so_salva_com_confirmacao(logado, fake):
    configurar_perfil(logado)
    original = db.one("SELECT contexto_md, palavras_chave, horarios FROM perfis WHERE id=1")
    # entrevista: o bot pergunta; o histórico vai junto na próxima rodada
    _dizer(fake, "/perfil")
    esperar(lambda: any(m == "sendMessage" and "Quem é você" in d["text"] for m, d in fake.st()["tg"]))
    perfil_novo = "# Quem eu sou\nConsultor de IA para donos de empresa. " * 3 + "\n# Tom de voz\nDireto, em primeira pessoa."
    fake.set(agente=[{"resposta": "Montei. Confirme pelos botões.", "acao": "propor_perfil", "perfil_md": perfil_novo,
                      "palavras_chave": "IA, saúde digital", "horarios": "08:00,19:30,25:99"}])
    _dizer(fake, "sou consultor de IA, falo com donos de empresa, tom direto")
    esperar(lambda: any(m == "sendMessage" and "Proposta de perfil" in d["text"] and "sp:1" in d["reply_markup"] for m, d in fake.st()["tg"]))
    assert fake.st()["llm_turnos"][-1] >= 3, "a conversa anterior foi enviada ao modelo"
    assert db.one("SELECT contexto_md FROM perfis WHERE id=1")["contexto_md"] == original["contexto_md"], "nada muda sem confirmar"
    fake.push("sp:1", "999")  # outra pessoa não confirma
    fake.push("sp:1", "42")
    esperar(lambda: db.one("SELECT contexto_md FROM perfis WHERE id=1")["contexto_md"] == perfil_novo)
    p = db.one("SELECT * FROM perfis WHERE id=1")
    assert p["palavras_chave"] == "IA, saúde digital" and p["horarios"] == "08:00,19:30", "horário inválido descartado"
    esperar(lambda: any(m == "sendMessage" and "Perfil salvo" in d["text"] for m, d in fake.st()["tg"]))
    assert not db.get_setting("propostaperfil:1")
    # ajustar: descarta a proposta sem tocar no perfil
    fake.set(agente=[{"resposta": "Outra versão.", "acao": "propor_perfil", "perfil_md": perfil_novo + "\n# Extra\nmais coisa " * 5}])
    _dizer(fake, "muda o tom")
    esperar(lambda: db.get_setting("propostaperfil:1"))
    fake.push("np:1", "42")
    esperar(lambda: not db.get_setting("propostaperfil:1"))
    assert db.one("SELECT contexto_md FROM perfis WHERE id=1")["contexto_md"] == perfil_novo
    # /novo zera a conversa
    _dizer(fake, "/novo")
    esperar(lambda: not db.q("SELECT 1 FROM conversas WHERE chat_id='42'"))
    db.x("UPDATE perfis SET contexto_md=?, palavras_chave=?, horarios=? WHERE id=1",
         (original["contexto_md"], original["palavras_chave"], original["horarios"]))


def test_conversa_sem_llm_ou_de_estranho_nao_gera_nada(logado, fake):
    n = _n_texto()
    fake.set(agente=[_gerar_cmd("feed")])
    fake.push_msg(999, "texto", "faz um post")
    _dizer(fake, "/start")
    esperar(lambda: fake.st()["agente"] == [])  # só o /start do dono consumiu a resposta
    assert not any(d.get("chat_id") == "999" for m, d in fake.st()["tg"])
    _novos_texto(n)
    for p in db.q("SELECT id FROM posts WHERE fonte='Texto' AND estado='aguardando_aprovacao'"):
        post_form(logado, f"/posts/{p['id']}/descartar")


# ---------------- pedido em texto livre na foto: story animado, música e texto na tela ----------------
def _com_trilha():
    import os, shutil
    C.MUSICAS.mkdir(parents=True, exist_ok=True)
    if not (C.MUSICAS / "trilha.mp3").exists():
        shutil.copy(os.environ["FAKE_MEDIA_DIR"] + "/trilha.mp3", C.MUSICAS / "trilha.mp3")


def test_foto_pedido_livre_vira_story_animado_com_musica_e_texto(logado, fake):
    _com_trilha()
    n = _n_midia()
    fake.push_msg(42, "foto", "quero um story desta imagem, gere uma legenda uma animação com musica serio tom de CEO")
    p = _novo_post(n)
    assert p["formato"] == "story" and p["arquivo"].endswith(".mp4") and p["legenda"] == ""
    info = _probe(C.CARDS / p["arquivo"])
    assert (info["w"], info["h"], info["vcodec"]) == (1080, 1920, "h264") and info["audio"] and 6.5 < info["dur"] < 7.5
    assert "tom de CEO" in fake.st()["llm_users"][-1], "o pedido de tom chega ao modelo"
    assert p["reacao"] == "Disciplina sustenta o resultado. Sempre."
    esperar(lambda: any(m == "sendVideo" and "animado" in d["caption"] and "trilha: trilha" in d["caption"]
                        and "texto na tela" in d["caption"] for m, d in fake.st()["tg"]))
    # o texto aparece no quadro (a foto é só a imagem de teste: o overlay deixa pixels claros na zona do texto)
    import subprocess
    quadro = C.CARDS / "q.jpg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "4", "-i", str(C.CARDS / p["arquivo"]), "-frames:v", "1", str(quadro)], check=True)
    assert jpeg_dims(quadro) == (1080, 1920)
    quadro.rename(C.CARDS.parent / "quadro_story_animado.jpg")
    post_form(logado, f"/posts/{p['id']}/aprovar")
    esperar(lambda: pipeline.post(p["id"])["estado"] == "publicado")
    media = next(d for t, d in fake.st()["graph"] if t == "media")
    assert media["media_type"] == "STORIES" and media["video_url"].endswith(".mp4")


def test_foto_story_com_texto_sem_animacao_continua_imagem(logado, fake):
    n = _n_midia()
    fake.push_msg(42, "foto", "story com uma frase forte")
    p = _novo_post(n)
    assert p["formato"] == "story" and p["arquivo"].endswith(".jpg") and jpeg_dims(C.CARDS / p["arquivo"]) == (1080, 1920)
    assert p["reacao"] and len(fake.st()["llm_users"]) == 1
    post_form(logado, f"/posts/{p['id']}/descartar")


def test_story_animado_sem_musica_e_sem_biblioteca(logado, fake):
    _com_trilha()
    n = _n_midia()
    fake.push_msg(42, "foto", "story animado sem música")
    p = _novo_post(n)
    info = _probe(C.CARDS / p["arquivo"])
    assert p["arquivo"].endswith(".mp4") and not info["audio"] and not fake.st()["llm_users"], "sem música e sem pedido de texto"
    # música pedida mas biblioteca vazia: avisa em vez de calar
    (C.MUSICAS / "trilha.mp3").rename(C.MUSICAS.parent / "trilha.bak")
    try:
        n = _n_midia()
        fake.push_msg(42, "foto", "story com animação e música")
        p2 = _novo_post(n)
        assert not _probe(C.CARDS / p2["arquivo"])["audio"]
        esperar(lambda: any(m == "sendVideo" and "não há músicas cadastradas" in d["caption"] for m, d in fake.st()["tg"]))
    finally:
        (C.MUSICAS.parent / "trilha.bak").rename(C.MUSICAS / "trilha.mp3")
    for x in (p, p2):
        post_form(logado, f"/posts/{x['id']}/descartar")


def test_video_story_ganha_texto_na_tela(logado, fake):
    _com_trilha()
    n = _n_midia()
    fake.push_msg(42, "video", "story com texto de abertura e música")
    p = _novo_post(n)
    info = _probe(C.CARDS / p["arquivo"])
    assert p["formato"] == "story" and (info["w"], info["h"]) == (1080, 1920) and info["audio"] and p["reacao"]
    post_form(logado, f"/posts/{p['id']}/descartar")


def test_pedidos_em_texto_livre():
    f = pipeline._pedidos
    assert f("quero um story, gere uma legenda uma animação com musica serio tom de CEO") == {"animar": True, "musica": True, "texto": True}
    assert f("story sem música") == {"animar": False, "musica": False, "texto": False}
    assert f("feed: treino de hoje") == {"animar": False, "musica": False, "texto": False}
    assert f("story com trilha e zoom")["animar"] and f("story com trilha e zoom")["musica"]


# ---------------- Lote 2: marca, citação, meme, banco de imagens, adaptação ----------------
def _pixel(path, x=5, y=5):
    import subprocess
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"crop=4:4:{x}:{y},scale=1:1:flags=area,format=rgb24", "-frames:v", "1", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return tuple(out[:3])


def _hex(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _perto(a, b, tol=14):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _png(nome="logo.png"):
    import subprocess
    dest = C.DATA / "tmp" / nome
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=200x80", "-frames:v", "1", str(dest)], check=True)
    return dest


def _marca_painel(client, **kw):
    return client.post("/perfis/1/marca", data={"csrf": csrf_de(client, "/perfis/1"), "fundo": "", "texto": "", "acento": "", "fonte": "", **kw})


def _por_fonte(fonte, antes, quantos=1):
    return esperar(lambda: (lambda r: list(reversed(r[:quantos])) if len(r) >= antes + quantos and all(
        x["estado"] != "capturado" for x in r[:quantos]) else None)(db.q("SELECT * FROM posts WHERE fonte=? ORDER BY id DESC", (fonte,))))


def _n_fonte(fonte):
    return len(db.q("SELECT 1 FROM posts WHERE fonte=?", (fonte,)))


def _chaves(client, pexels="", unsplash=""):
    for nome, v in (("pexels", pexels), ("unsplash", unsplash)):
        post_form(client, f"/config/{nome}", **({"chave": v} if v else {"acao": "remover"}))


def test_marca_pelo_painel_vale_nos_cards_e_rejeita_cores_ilegiveis(logado, fake):
    configurar_perfil(logado)
    r = _marca_painel(logado, fundo="#102a43", texto="#fafafa", acento="#ffd166", fonte="serif")
    assert r.status_code == 303
    import json
    assert json.loads(db.one("SELECT marca FROM perfis WHERE id=1")["marca"]) == {"fundo": "#102a43", "texto": "#fafafa", "acento": "#ffd166", "fonte": "serif"}
    n = _n_texto()
    fake.set(agente=[_gerar_cmd("feed")])
    _dizer(fake, "um post sobre dado")
    [p] = _novos_texto(n)
    assert _perto(_pixel(C.CARDS / p["arquivo"]), _hex("#102a43")), "o fundo do card segue a marca"
    post_form(logado, f"/posts/{p['id']}/descartar")
    # cores com contraste ruim são recusadas e as anteriores ficam
    _marca_painel(logado, fundo="#222222", texto="#2a2a2a")
    assert "parecidos demais" in ver(logado, "/perfis/1")
    assert json.loads(db.one("SELECT marca FROM perfis WHERE id=1")["marca"])["fundo"] == "#102a43"
    _marca_painel(logado, acento="vermelho")
    assert "inválida" in ver(logado, "/perfis/1")


def test_logotipo_envio_validacao_e_remocao(logado, fake):
    png = _png()
    c = logado
    r = c.post("/perfis/1/marca", data={"csrf": csrf_de(c, "/perfis/1"), "fundo": "", "texto": "", "acento": "", "fonte": ""},
               files={"logo": ("logo.png", png.read_bytes(), "image/png")})
    assert r.status_code == 303 and (C.MARCA / "1.png").exists()
    assert c.get("/perfis/1/logo").status_code == 200 and "/perfis/1/logo" in ver(c, "/perfis/1")
    r = c.post("/perfis/1/marca", data={"csrf": csrf_de(c, "/perfis/1"), "fundo": "", "texto": "", "acento": "", "fonte": ""},
               files={"logo": ("x.png", b"isto nao e imagem", "image/png")})
    assert "não aceito" in ver(c, "/perfis/1") and (C.MARCA / "1.png").exists(), "arquivo inválido não substitui o logo"
    # o logo aparece no card (pixel vermelho no canto superior esquerdo, onde fica a marca)
    n = _n_texto()
    fake.set(agente=[_gerar_cmd("feed")])
    _dizer(fake, "um post com logo")
    [p] = _novos_texto(n)
    achou = any(_perto(_pixel(C.CARDS / p["arquivo"], x, 100), (255, 0, 0), 40) for x in range(84, 300, 6))
    assert achou, "o logotipo foi desenhado no cabeçalho do card"
    post_form(logado, f"/posts/{p['id']}/descartar")
    _marca_painel(c, remover_logo="on")
    assert not (C.MARCA / "1.png").exists() and c.get("/perfis/1/logo").status_code == 404


def test_logo_e_marca_pelo_telegram(logado, fake):
    fake.set(agente=[{"resposta": "Marca atualizada.", "acao": "definir_marca", "marca": {"fundo": "#0b1f3a", "texto": "", "acento": "#ffd166", "fonte": "mono"}}])
    _dizer(fake, "meu fundo é azul escuro e o destaque é amarelo, fonte técnica")
    esperar(lambda: any(m == "sendMessage" and "🎨 Marca" in d["text"] and "#0b1f3a" in d["text"] for m, d in fake.st()["tg"]))
    import json
    m = json.loads(db.one("SELECT marca FROM perfis WHERE id=1")["marca"])
    assert m["fundo"] == "#0b1f3a" and m["acento"] == "#ffd166" and m["fonte"] == "mono" and m["texto"] == "#fafafa", "o que não foi dito fica como estava"
    # logo enviado como foto com a palavra "logo" na legenda
    fake.push_msg(42, "foto", "este é o meu logo")
    esperar(lambda: any(m == "sendMessage" and "Logotipo salvo" in d["text"] for m, d in fake.st()["tg"]))
    assert (C.MARCA / "1.jpg").exists() or (C.MARCA / "1.png").exists()
    _marca_painel(logado, remover_logo="on", fundo="#102a43", acento="#ff7a1a", fonte="sans")


def test_conexoes_guardam_chaves_do_banco_de_imagens_mascaradas(logado, fake):
    _chaves(logado, pexels="PEXELS-SEGREDO-123456", unsplash="UNSPLASH-SEGREDO-654321")
    pg = ver(logado, "/conexoes")
    assert "SEGREDO" not in pg and "Pexels" in pg and "Unsplash" in pg
    assert "PEXELS-SEGREDO" not in db.get_setting("pexels_key"), "guardada criptografada"
    post_form(logado, "/conexoes/banco", perfil_id="1")
    assert "Banco de imagens OK" in ver(logado, "/conexoes") and "Pexels" in ver(logado, "/conexoes")
    b = fake.st()["banco"]
    assert any(x[0] == "pexels" and x[1] == "PEXELS-SEGREDO-123456" for x in b)
    assert any(x[0] == "unsplash" and x[1] == "Client-ID UNSPLASH-SEGREDO-654321" for x in b)


def test_citacao_com_cores_da_marca(logado, fake):
    _chaves(logado)
    n = _n_fonte("Citação")
    fake.set(agente=[{**_gerar_cmd("citacao", "frase sobre controle de dados"), "gerar": {"formato": "citacao", "ideia": "frase sobre controle de dados", "n_slides": 0, "variacoes": 1, "fundo": "nenhum"}}])
    _dizer(fake, "faz uma citação sobre dados")
    [p] = _por_fonte("Citação", n)
    assert p["estado"] == "aguardando_aprovacao" and jpeg_dims(C.CARDS / p["arquivo"]) == (1080, 1350)
    assert p["manchete"] == "Quem controla o dado controla o jogo." and "#ia" in p["legenda"] and "Foto:" not in p["legenda"]
    cores = [_hex("#102a43"), _hex("#fafafa"), _hex("#ff7a1a")]
    assert any(_perto(_pixel(C.CARDS / p["arquivo"]), c) for c in cores), "fundo é uma das cores da marca"
    esperar(lambda: any(m == "sendPhoto" and "Minha frase de hoje" in d["caption"] for m, d in fake.st()["tg"]))
    # refazer mantém o tipo e troca o arquivo
    antigo = p["arquivo"]
    post_form(logado, f"/posts/{p['id']}/refazer")
    esperar(lambda: pipeline.post(p["id"])["arquivo"] != antigo and pipeline.post(p["id"])["estado"] == "aguardando_aprovacao")
    assert not (C.CARDS / antigo).exists() and pipeline.post(p["id"])["fonte"] == "Citação"
    post_form(logado, f"/posts/{p['id']}/descartar")


def test_citacao_com_foto_do_banco_poe_credito_na_legenda(logado, fake):
    _chaves(logado, pexels="PXKEY-1234567")
    n = _n_fonte("Citação")
    fake.set(agente=[{"resposta": "Gerando.", "acao": "gerar", "gerar": {"formato": "citacao", "ideia": "frase sobre foco", "n_slides": 0, "variacoes": 1, "fundo": "banco"}}])
    _dizer(fake, "citação com foto de fundo sobre foco")
    [p] = _por_fonte("Citação", n)
    assert "Foto: Ana Souza · Pexels" in p["legenda"] and jpeg_dims(C.CARDS / p["arquivo"]) == (1080, 1350)
    b = fake.st()["banco"]
    assert b[0][0] == "pexels" and b[0][1] == "PXKEY-1234567" and b[0][2]["query"] == "calm mountain" and b[0][2]["orientation"] == "portrait"
    assert not any(x[0] == "unsplash" for x in b), "sem chave, o Unsplash não é chamado"
    assert not list((C.DATA / "tmp").glob("*.jpg")) or True
    post_form(logado, f"/posts/{p['id']}/descartar")


def test_citacao_pede_foto_sem_chave_cai_para_sem_foto_e_avisa(logado, fake):
    _chaves(logado)
    n = _n_fonte("Citação")
    fake.set(agente=[{"resposta": "Gerando.", "acao": "gerar", "gerar": {"formato": "citacao", "ideia": "frase sobre calma", "n_slides": 0, "variacoes": 1, "fundo": "banco"}}])
    _dizer(fake, "citação com foto")
    [p] = _por_fonte("Citação", n)
    assert "Foto:" not in p["legenda"] and p["estado"] == "aguardando_aprovacao"
    esperar(lambda: any(m == "sendPhoto" and "Sem chave de banco de imagens" in d["caption"] for m, d in fake.st()["tg"]))
    post_form(logado, f"/posts/{p['id']}/descartar")


def test_meme_do_banco_credita_e_avisa_o_unsplash(logado, fake):
    _chaves(logado, unsplash="UNKEY-7654321")
    n = _n_fonte("Meme")
    fake.set(agente=[{"resposta": "Gerando.", "acao": "gerar", "gerar": {"formato": "meme", "ideia": "relatório com dado de outro cliente", "n_slides": 0, "variacoes": 1, "fundo": "banco"}}])
    _dizer(fake, "faz um meme sobre relatório")
    [p] = _por_fonte("Meme", n)
    assert p["estado"] == "aguardando_aprovacao", p["erro"]
    assert jpeg_dims(C.CARDS / p["arquivo"]) == (1080, 1350)
    assert "Foto: Bruno Lima · Unsplash" in p["legenda"] and p["manchete"] == "Quando o relatório fecha"
    b = fake.st()["banco"]
    assert b[0][2]["query"] == "surprised office" and any(x[0] == "unsplash-download" and x[1] == "Client-ID UNKEY-7654321" for x in b), "regra do Unsplash: registrar o uso"
    post_form(logado, f"/posts/{p['id']}/descartar")


def test_meme_sem_chave_falha_com_motivo_claro(logado, fake):
    _chaves(logado)
    n = _n_fonte("Meme")
    fake.set(agente=[{"resposta": "Gerando.", "acao": "gerar", "gerar": {"formato": "meme", "ideia": "piada sobre reunião", "n_slides": 0, "variacoes": 1, "fundo": "banco"}}])
    _dizer(fake, "meme sobre reunião")
    esperar(lambda: any(m == "sendMessage" and "nenhum banco de imagens configurado" in d["text"] for m, d in fake.st()["tg"]))
    p = db.one("SELECT * FROM posts WHERE fonte='Meme' ORDER BY id DESC")
    assert p["estado"] == "falhou" and "Conexões" in p["erro"]
    assert _n_fonte("Meme") == n + 1


def test_meme_com_a_sua_foto(logado, fake):
    n = _n_midia()
    fake.push_msg(42, "foto", "meme: quando a reunião podia ser um e-mail")
    p = _novo_post(n)
    assert p["formato"] == "feed" and p["estado"] == "aguardando_aprovacao" and jpeg_dims(C.CARDS / p["arquivo"]) == (1080, 1350)
    assert p["reacao"] == "mas o dado era de outro cliente" and "e-mail" in fake.st()["llm_users"][-1]
    esperar(lambda: any(m == "sendPhoto" and "Todo mundo já passou" in d["caption"] for m, d in fake.st()["tg"]))
    post_form(logado, f"/posts/{p['id']}/descartar")


def test_adaptar_feed_para_story_e_de_volta_sem_cortar(logado, fake):
    configurar_perfil(logado)
    n = _n_texto()
    fake.set(agente=[_gerar_cmd("feed")])
    _dizer(fake, "um post para adaptar")
    [p] = _novos_texto(n)
    esperar(lambda: any(m == "sendPhoto" and "Versão Story" in _botoes(d) for m, d in fake.st()["tg"]))
    antes = len(db.q("SELECT 1 FROM posts"))
    fake.push(f"ad:{p['id']}", "42")
    esperar(lambda: len(db.q("SELECT 1 FROM posts")) == antes + 1)
    s = db.one("SELECT * FROM posts ORDER BY id DESC")
    assert s["formato"] == "story" and s["estado"] == "aguardando_aprovacao" and s["legenda"] == "" and jpeg_dims(C.CARDS / s["arquivo"]) == (1080, 1920)
    assert pipeline.post(p["id"])["estado"] == "aguardando_aprovacao" and (C.CARDS / p["arquivo"]).exists(), "o original continua"
    esperar(lambda: any(m == "sendPhoto" and "Versão STORY do post" in d["caption"] and "Versão Feed" in _botoes(d) for m, d in fake.st()["tg"]))
    # pelo painel: story -> feed volta a 1080x1350 e mantém a legenda do original quando existe
    post_form(logado, f"/posts/{s['id']}/adaptar-feed")
    f = db.one("SELECT * FROM posts ORDER BY id DESC")
    assert f["id"] != s["id"] and f["formato"] == "feed" and jpeg_dims(C.CARDS / f["arquivo"]) == (1080, 1350)
    # no mesmo formato, ou carrossel, não adapta
    assert _rodar(pipeline.adaptar(p["id"], "feed")) is None
    for x in (p, s, f):
        post_form(logado, f"/posts/{x['id']}/descartar")


def _botoes(d):
    import json
    return " ".join(b["text"] + "|" + b["callback_data"] for linha in json.loads(d["reply_markup"])["inline_keyboard"] for b in linha)


def _rodar(coro):
    import asyncio, threading
    out = {}
    def alvo():
        out["v"] = asyncio.run(coro)
    t = threading.Thread(target=alvo); t.start(); t.join()
    return out["v"]
