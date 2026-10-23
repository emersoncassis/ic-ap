"""Crítico visual com rubrica objetiva (T5): a nota sai dos critérios sim/não, calculada no código."""
import asyncio

import pytest

from app.agentes.critico import CRITERIOS, ELIMINATORIOS, CriticoAgente, calcular_nota, consolidar
from tests.conftest import FAKE


def _crit(**reprovados):
    return {k: {"ok": k not in reprovados, "justificativa": reprovados.get(k, "ok")} for k in CRITERIOS}


def test_pesos_somam_dez_e_eliminatorios_existem():
    assert sum(p for p, _ in CRITERIOS.values()) == 10
    assert set(ELIMINATORIOS) <= set(CRITERIOS)


@pytest.mark.parametrize("reprovados,nota,aprovado", [
    ({}, 10, True),
    ({"safe_zone": "x"}, 9, True),
    ({"hierarquia": "x"}, 8, True),
    ({"hierarquia": "x", "safe_zone": "x"}, 7, False),     # abaixo de 8
    ({"contraste": "x"}, 8, False),                        # nota 8, mas eliminatório reprovado
    ({"legibilidade": "x"}, 8, False),
    ({"texto_cortado": "x"}, 7, False),
    ({k: "x" for k in CRITERIOS}, 1, False),               # a nota nunca fica abaixo de 1
])
def test_nota_e_aprovacao_saem_dos_criterios(reprovados, nota, aprovado):
    assert calcular_nota(_crit(**reprovados)) == (nota, aprovado)


def test_consolidar_monta_problemas_e_sugestao_a_partir_dos_criterios_reprovados():
    r = consolidar(_crit(contraste="texto cinza sobre foto clara"), sugestao="escurecer o fundo")
    assert (r["score"], r["aprovado"]) == (8, False)
    assert r["problemas"] == ["contraste: texto cinza sobre foto clara"]
    assert r["sugestao_ajuste"] == "escurecer o fundo" and "contraste" not in r["pontos_fortes"]
    # sem sugestão do modelo, o ciclo de refino recebe as justificativas
    assert consolidar(_crit(contraste="fraco"))["sugestao_ajuste"] == "contraste: fraco"
    assert consolidar(_crit())["problemas"] == []


def test_medicao_do_motor_vence_a_resposta_do_modelo():
    r = consolidar(_crit(), estourou_texto=True)           # o modelo disse que estava tudo certo
    assert r["criterios"]["texto_cortado"]["ok"] is False and r["aprovado"] is False and r["score"] == 7
    r = consolidar(_crit(), palavras_manchete=20)
    assert r["criterios"]["hierarquia"]["ok"] is False and r["score"] == 8 and r["aprovado"] is True
    assert consolidar(_crit(), palavras_manchete=16)["score"] == 10


def test_validar_exige_os_cinco_criterios_com_ok_booleano_e_justificativa_ao_reprovar():
    ag = CriticoAgente()
    assert ag.validar({"criterios": _crit()}) == []
    assert any("contraste" in e for e in ag.validar({"criterios": {k: v for k, v in _crit().items() if k != "contraste"}}))
    assert any("safe_zone" in e for e in ag.validar({"criterios": {**_crit(), "safe_zone": {"ok": "sim", "justificativa": ""}}}))
    assert any("sem justificativa" in e for e in ag.validar({"criterios": {**_crit(), "hierarquia": {"ok": False, "justificativa": " "}}}))
    assert ag.validar({"criterios": "ótimo"}) and ag.validar({})


def _avaliar(tmp_path, estourou=False, manchete="Dado na mão da empresa"):
    card = tmp_path / "card.jpg"
    card.write_bytes(b"\xff\xd8\xff\xd9")
    con = {"tipo": "openai", "base_url": f"{FAKE}/v1", "api_key": "", "modelo": "modelo-a", "nome": "teste"}
    return asyncio.run(CriticoAgente().avaliar(con, {"nome": "Teste", "contexto_md": ""}, card, estourou, "post sobre dados",
                                               {"formato": "feed"}, {"manchete_card": manchete, "cta": "Comente"}, {"layout": "editorial"}))


def test_avaliar_aprova_e_devolve_o_contrato_que_o_ciclo_de_refino_usa(client, fake, tmp_path):
    r = _avaliar(tmp_path)
    assert (r["score"], r["aprovado"], r["problemas"]) == (10, True, [])
    assert set(r["criterios"]) == set(CRITERIOS) and {"sugestao_ajuste", "usou_visao", "pontos_fortes"} <= set(r)


def test_avaliar_reprova_e_o_feedback_chega_ao_ciclo_de_refino(client, fake, tmp_path):
    fake.set(critico_modo="reprova")
    r = _avaliar(tmp_path)
    assert r["aprovado"] is False and r["score"] == 8
    assert r["problemas"] == ["contraste: texto cinza sobre foto clara"] and r["sugestao_ajuste"] == "escurecer o fundo"
    assert _avaliar(tmp_path)["aprovado"] is True            # o modo vale uma avaliação só: o refino seguinte aprova


def test_avaliar_texto_estourado_nunca_aprova_mesmo_com_modelo_otimista(client, fake, tmp_path):
    r = _avaliar(tmp_path, estourou=True)
    assert r["aprovado"] is False and r["score"] < 8 and any(p.startswith("texto_cortado") for p in r["problemas"])
