"""Testes unitários para o Loop de Aprendizado Contínuo (Padrão Viraloop)."""
from app import aprendizados, db
from app.agentes import BaseAgente


def test_registrar_listar_e_sintetizar_aprendizados():
    db.init()
    perfil_id = 888

    # Limpa antes do teste
    db.x("DELETE FROM aprendizados WHERE perfil_id=?", (perfil_id,))

    # 1. Registra post de alto desempenho
    id1 = aprendizados.registrar(
        perfil_id=perfil_id,
        post_id=101,
        hook="O erro de R$ 50 mil que instaladores cometem em CFTV:",
        formato="carrossel",
        angulo="alerta técnico",
        metricas={"alcance": 5400, "salvamentos": 320, "compartilhamentos": 140, "comentarios": 45},
        licao="Ganchos com valores monetários e erros geraram 3x mais salvamentos",
    )
    assert id1 > 0

    # 2. Registra post de baixo desempenho
    id2 = aprendizados.registrar(
        perfil_id=perfil_id,
        post_id=102,
        hook="História da segurança eletrônica nos anos 90",
        formato="feed",
        angulo="histórico",
        metricas={"alcance": 800, "salvamentos": 5, "compartilhamentos": 2, "comentarios": 1},
        licao="Conteúdo histórico puro não gera retenção",
    )
    assert id2 > 0

    # 3. Lista aprendizados ordenados por score de retenção
    itens = aprendizados.listar(perfil_id)
    assert len(itens) == 2
    assert itens[0]["id"] == id1  # Maior score primeiro
    assert itens[0]["salvamentos"] == 320

    # 4. Síntese para injeção no prompt
    sintese = aprendizados.sintetizar_aprendizados(perfil_id)
    assert "VIRALOOP" in sintese
    assert "O erro de R$ 50 mil" in sintese
    assert "carrossel" in sintese

    # 5. Valida injeção automática no BaseAgente
    agente = BaseAgente()
    perfil = {
        "id": perfil_id,
        "nome": "Emerson",
        "contexto_md": "Especialista em segurança eletrônica e IA.",
    }
    sys_prompt = agente.montar_system(perfil, "Você cria roteiros.")
    assert "VIRALOOP" in sys_prompt
    assert "O erro de R$ 50 mil" in sys_prompt

    # Limpeza
    db.x("DELETE FROM aprendizados WHERE perfil_id=?", (perfil_id,))
