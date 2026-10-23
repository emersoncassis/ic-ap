"""Testes para Feeds integrados ao Perfil e Sincronização com Meta AI."""
import asyncio

from app import db, pipeline, wizard


def test_analisar_relatorio_meta_ai_deterministico():
    async def _test():
        db.init()
        relatorio = """
        Análise do perfil @ciber_seguro:
        1. Nicho e Autoridade:
        Especialista em IA privada on-premise, governança de dados corporativos e adequação à LGPD.
        2. Tom de Voz:
        Técnico, assertivo, sem rodeios e focado em riscos jurídicos e conformidade.
        3. Temas mais abordados:
        - Vulnerabilidades de LLMs em nuvem pública
        - Riscos de multas pela LGPD e vazamento de dados
        - Servidores locais para inteligência artificial corporativa
        """
        resultado = await wizard.analisar_relatorio_meta_ai(relatorio, "Carlos Silva", "ciber_seguro")
        assert resultado["nicho"] is not None
        assert "ia privada" in resultado["palavras_chave"] or "segurança" in resultado["palavras_chave"]
        assert len(resultado["feeds_sugeridos"]) > 0
        assert any("Google News" in f["nome"] for f in resultado["feeds_sugeridos"])
        assert "# Contexto e Tom de Voz: Carlos Silva" in resultado["contexto_md"]
        assert "Diretrizes de Tom de Voz (2026)" in resultado["contexto_md"]

    asyncio.run(_test())


def test_aplicar_analise_meta_ai_ao_perfil():
    async def _test():
        db.init()
        pid = db.x(
            "INSERT INTO perfis(nome, handle, ativo, criado_em) VALUES(?,?,1,?)",
            ("Dr. Marcos", "dr_marcos_saude", db.now())
        )
        relatorio = """
        Análise do perfil @dr_marcos_saude:
        Nicho: Medicina preventiva, longevidade celular, biohacking e qualidade do sono.
        Público busca práticas para viver mais com alta disposição e saúde integrativa.
        """
        res = await wizard.aplicar_analise_meta_ai_ao_perfil(pid, relatorio, substituir_feeds=True)
        assert res["ok"] is True
        assert res["total_feeds"] > 0

        # Verifica se o perfil no banco foi atualizado
        p = db.one("SELECT * FROM perfis WHERE id=?", (pid,))
        assert p is not None
        assert p["meta_ai_analise"] == relatorio.strip()
        assert "saúde" in p["palavras_chave"] or "longevidade" in p["palavras_chave"]

        # Verifica se os feeds foram vinculados diretamente ao perfil
        feeds = db.q("SELECT * FROM feeds WHERE perfil_id=?", (pid,))
        assert len(feeds) == res["total_feeds"]
        assert all(f["perfil_id"] == pid for f in feeds)

    asyncio.run(_test())


def test_prioridade_feeds_exclusivos_do_perfil():
    async def _test():
        db.init()
        # Perfil A com feeds exclusivos
        pid_a = db.x("INSERT INTO perfis(nome, handle, ativo, criado_em) VALUES(?,?,1,?)", ("Perfil A", "perfil_a", db.now()))
        db.x("INSERT INTO feeds(perfil_id, nome, url, tema, ativo) VALUES(?,?,?,?,1)",
             (pid_a, "Feed Exclusivo A", "https://exemplo.com/a.xml", "tema_a"))

        # Perfil B sem feeds exclusivos (deve usar globais como fallback)
        pid_b = db.x("INSERT INTO perfis(nome, handle, ativo, criado_em) VALUES(?,?,1,?)", ("Perfil B", "perfil_b", db.now()))

        # Feed Global
        db.x("INSERT INTO feeds(perfil_id, nome, url, tema, ativo) VALUES(NULL,?,?,?,1)",
             ("Feed Global", "https://exemplo.com/global.xml", "global"))

        # Busca para perfil A
        fl_a = db.q("SELECT * FROM feeds WHERE ativo=1 AND perfil_id=?", (pid_a,))
        if not fl_a:
            fl_a = db.q("SELECT * FROM feeds WHERE ativo=1 AND (perfil_id IS NULL OR perfil_id=?)", (pid_a,))
        assert len(fl_a) == 1
        assert fl_a[0]["nome"] == "Feed Exclusivo A"

        # Busca para perfil B
        fl_b = db.q("SELECT * FROM feeds WHERE ativo=1 AND perfil_id=?", (pid_b,))
        if not fl_b:
            fl_b = db.q("SELECT * FROM feeds WHERE ativo=1 AND (perfil_id IS NULL OR perfil_id=?)", (pid_b,))
        assert any(f["nome"] == "Feed Global" for f in fl_b)

    asyncio.run(_test())




def test_rotas_perfil_feeds_e_meta_ai(api_client):
    client = api_client
    # Setup de admin e login
    db.init()
    from app import crypto
    db.set_setting("admin_hash", crypto.hash_password("senha12345"))
    r_login = client.post("/login", data={"senha": "senha12345"}, follow_redirects=True)
    assert r_login.status_code == 200

    # Cria perfil para teste
    pid = db.x("INSERT INTO perfis(nome, handle, ativo, criado_em) VALUES(?,?,1,?)", ("Testador Feeds", "testador_feeds", db.now()))

    # 1. Adicionar feed ao perfil
    csrf = client.get(f"/perfis/{pid}").text
    import re
    match_csrf = re.search(r'name="csrf" value="([a-f0-9]+)"', csrf)
    token_csrf = match_csrf.group(1) if match_csrf else ""

    r_add = client.post(
        f"/perfis/{pid}/feeds",
        data={"csrf": token_csrf, "nome": "Meu Feed Teste", "url": "https://teste.com/feed.xml", "tema": "tech"},
        follow_redirects=False,
    )
    assert r_add.status_code == 303
    f_db = db.one("SELECT * FROM feeds WHERE perfil_id=? AND url=?", (pid, "https://teste.com/feed.xml"))
    assert f_db is not None
    assert f_db["nome"] == "Meu Feed Teste"
    assert f_db["ativo"] == 1

    # 2. Alternar status do feed
    fid = f_db["id"]
    r_alt = client.post(
        f"/perfis/{pid}/feeds/{fid}/alternar",
        data={"csrf": token_csrf},
        follow_redirects=False,
    )
    assert r_alt.status_code == 303
    f_db2 = db.one("SELECT * FROM feeds WHERE id=?", (fid,))
    assert f_db2["ativo"] == 0

    # 3. Importar pack para o perfil
    r_pack = client.post(
        f"/perfis/{pid}/feeds/importar-pack",
        data={"csrf": token_csrf, "pack_id": "financas_investimentos"},
        follow_redirects=False,
    )
    assert r_pack.status_code == 303
    feeds_pack = db.q("SELECT * FROM feeds WHERE perfil_id=?", (pid,))
    assert len(feeds_pack) >= 3

    # 4. Sincronizar com relatório do Meta AI
    relatorio = """
    Análise do perfil @testador_feeds:
    Nicho: Direito digital e cibersegurança empresarial.
    Gera alto salvamento em compliance e privacidade.
    """
    r_meta = client.post(
        f"/perfis/{pid}/meta-analise",
        data={"csrf": token_csrf, "relatorio": relatorio, "substituir_feeds": "1"},
        follow_redirects=False,
    )
    assert r_meta.status_code == 303
    p_atual = db.one("SELECT * FROM perfis WHERE id=?", (pid,))
    assert p_atual["meta_ai_analise"] == relatorio.strip()

    # 5. Remover feed
    f_rem = db.one("SELECT id FROM feeds WHERE perfil_id=? LIMIT 1", (pid,))
    if f_rem:
        r_del = client.post(f"/perfis/{pid}/feeds/{f_rem['id']}/remover", data={"csrf": token_csrf}, follow_redirects=False)
        assert r_del.status_code == 303
        assert db.one("SELECT 1 FROM feeds WHERE id=?", (f_rem["id"],)) is None


def test_excluir_perfil_pipeline():
    db.init()
    pid = db.x("INSERT INTO perfis(nome, handle, ativo, criado_em) VALUES(?,?,1,?)", ("Para Excluir", "excluir_me", db.now()))
    db.x("INSERT INTO feeds(perfil_id, nome, url, tema, ativo) VALUES(?,?,?,?,1)", (pid, "Feed Exclusivo", "https://teste.com/rss", "tema"))
    db.x("INSERT INTO posts(perfil_id, estado, noticia_url, noticia_titulo, criado_em, atualizado_em) VALUES(?,?,?,?,?,?)",
                   (pid, "rascunho", "https://teste.com/n1", "Titulo Noticia", db.now(), db.now()))
    db.x("INSERT INTO canais_distribuicao(perfil_id, canal, identificador, ativo) VALUES(?,?,?,1)", (pid, "instagram", "123"))
    db.x("INSERT INTO eventos(perfil_id, tipo, detalhe, criado_em) VALUES(?,?,?,?)", (pid, "teste", "detalhe", db.now()))

    # Executa exclusão
    assert pipeline.excluir_perfil(pid) is True

    # Verifica que tudo foi limpo
    assert db.one("SELECT 1 FROM perfis WHERE id=?", (pid,)) is None
    assert db.one("SELECT 1 FROM feeds WHERE perfil_id=?", (pid,)) is None
    assert db.one("SELECT 1 FROM posts WHERE perfil_id=?", (pid,)) is None
    assert db.one("SELECT 1 FROM canais_distribuicao WHERE perfil_id=?", (pid,)) is None
    assert db.one("SELECT 1 FROM eventos WHERE perfil_id=?", (pid,)) is None

    # Exclusão de ID inexistente retorna False
    assert pipeline.excluir_perfil(999999) is False


def test_rota_excluir_perfil(api_client):
    client = api_client
    db.init()
    from app import crypto
    db.set_setting("admin_hash", crypto.hash_password("senha12345"))
    client.post("/login", data={"senha": "senha12345"}, follow_redirects=True)

    pid = db.x("INSERT INTO perfis(nome, handle, ativo, criado_em) VALUES(?,?,1,?)", ("Perfil Rota Excluir", "rota_excluir", db.now()))
    db.x("INSERT INTO feeds(perfil_id, nome, url, tema, ativo) VALUES(?,?,?,?,1)", (pid, "Feed Rota", "https://rota.com/rss", "tema"))

    # Extrai CSRF
    csrf = client.get(f"/perfis/{pid}").text
    import re
    match_csrf = re.search(r'name="csrf" value="([a-f0-9]+)"', csrf)
    token_csrf = match_csrf.group(1) if match_csrf else ""

    # POST /perfis/{pid}/excluir
    res = client.post(f"/perfis/{pid}/excluir", data={"csrf": token_csrf}, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/perfis"

    # Confirma que foi excluído do banco
    assert db.one("SELECT 1 FROM perfis WHERE id=?", (pid,)) is None
    assert db.one("SELECT 1 FROM feeds WHERE perfil_id=?", (pid,)) is None

    # Tentativa em perfil inexistente deve dar 404
    res_404 = client.post(f"/perfis/{pid}/excluir", data={"csrf": token_csrf}, follow_redirects=False)
    assert res_404.status_code == 404


