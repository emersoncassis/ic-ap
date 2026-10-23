"""Testes do Escritório Virtual dos Agentes e Diagnóstico de Gargalos."""
import pytest
from unittest.mock import AsyncMock, patch

from app import db, escritorio


@pytest.fixture(scope="module", autouse=True)
def _limpar_banco_apos_modulo():
    yield
    db.init()
    for tabela in ("posts", "perfis", "feeds", "settings", "eventos", "conversas"):
        db.x(f"DELETE FROM {tabela}")
    from app import seed
    seed.run()


def test_diagnosticar_gargalos():
    db.init()
    # Perfil desligado e sem LLM configurado
    pid = db.x("INSERT INTO perfis(nome, handle, ativo, criado_em) VALUES(?,?,0,?)", ("Perfil Inativo", "inativo", db.now()))
    
    gargalos = escritorio.diagnosticar_gargalos(pid)
    assert len(gargalos) > 0
    ids_gargalos = {g["id"] for g in gargalos}
    assert "perfil_desligado" in ids_gargalos

    # Adiciona post aguardando aprovação
    db.x("INSERT INTO posts(perfil_id, estado, noticia_url, noticia_titulo, criado_em, atualizado_em) VALUES(?,?,?,?,?,?)",
         (pid, "aguardando_aprovacao", "https://noticia.com/1", "Noticia Pendente", db.now(), db.now()))

    gargalos_com_pendente = escritorio.diagnosticar_gargalos(pid)
    ids_atualizados = {g["id"] for g in gargalos_com_pendente}
    assert "aguardando_aprovacao" in ids_atualizados


def test_obter_estado_escritorio():
    db.init()
    pid = db.x("INSERT INTO perfis(nome, handle, ativo, horarios, criado_em) VALUES(?,?,1,?,?)",
               ("Criador Alpha", "criador_alpha", "09:00,18:00", db.now()))

    estado = escritorio.obter_estado_escritorio(pid)
    assert estado is not None
    assert estado["perfil_atual"]["nome"] == "Criador Alpha"
    assert "estatisticas" in estado
    assert "loops" in estado
    assert "salas" in estado
    assert len(estado["salas"]) == 8

    # Verifica se a sala da pracinha de pausa está presente
    salas_ids = [s["id"] for s in estado["salas"]]
    assert "sala_cafe" in salas_ids
    assert "sala_orquestrador" in salas_ids
    assert "sala_redacao" in salas_ids




def test_rotas_escritorio(api_client):
    client = api_client
    db.init()
    from app import crypto
    db.set_setting("admin_hash", crypto.hash_password("senha12345"))
    client.post("/login", data={"senha": "senha12345"}, follow_redirects=True)

    pid = db.x("INSERT INTO perfis(nome, handle, ativo, criado_em) VALUES(?,?,1,?)", ("Perfil Escritorio", "escritorio_teste", db.now()))

    # 1. GET /escritorio (HTML)
    r_html = client.get("/escritorio")
    assert r_html.status_code == 200
    assert "Escritório dos Agentes" in r_html.text
    assert "Planta Baixa do Coworking" in r_html.text

    # 2. GET /api/escritorio/status (JSON)
    r_json = client.get(f"/api/escritorio/status?pid={pid}")
    assert r_json.status_code == 200
    dados = r_json.json()
    assert dados["perfil_atual"]["id"] == pid
    assert len(dados["salas"]) == 8
    assert "estatisticas" in dados

    # 3. POST /api/escritorio/disparar
    csrf = client.get("/escritorio").text
    import re
    match_csrf = re.search(r'name="csrf" value="([a-f0-9]+)"', csrf)
    token_csrf = match_csrf.group(1) if match_csrf else ""

    with patch("app.pipeline.gerar", new_callable=AsyncMock):
        r_disp = client.post("/api/escritorio/disparar", data={"csrf": token_csrf, "perfil_id": pid})
        assert r_disp.status_code == 200
        assert r_disp.json()["ok"] is True

    # 4. Testa renderização com tunel e telegram configurados (sem gargalo de túnel)
    from app import settings
    settings.guardar_segredo("tunnel_token", "token_valido_teste")
    settings.guardar_segredo("telegram_token", "tg_token_valido")
    r_html_com_tunel = client.get("/escritorio")
    assert r_html_com_tunel.status_code == 200
    assert "Escritório dos Agentes" in r_html_com_tunel.text

