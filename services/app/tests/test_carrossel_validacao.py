"""Slides do carrossel: nenhum vazio e a quantidade pedida (llm.validar_slides, llm.carrossel_de_texto e o agente carousel_planner)."""
import asyncio

import pytest

from app import llm
from app.agentes import CarouselPlannerAgente
from app.agentes.carousel_planner import _N_PEDIDO
from tests.conftest import FAKE


def _slides(n, troca=None):
    return [{"titulo": f"Título {i}", "texto": f"Texto {i}.", **(troca or {}).get(i, {})} for i in range(1, n + 1)]


def test_validar_slides_aceita_carrossel_completo():
    assert llm.validar_slides(_slides(5), 5)[0] == {"titulo": "Título 1", "texto": "Texto 1."}


@pytest.mark.parametrize("slides,n,trecho", [
    (_slides(5, {1: {"texto": ""}}), 5, "slide 1 sem texto"),
    (_slides(5, {3: {"texto": "   "}}), 5, "slide 3 sem texto"),
    (_slides(5, {2: {"titulo": ""}}), 5, "slide 2 sem titulo"),
    (_slides(4), 5, "exatamente 5"),
    (_slides(6), 5, "exatamente 5"),
    ("não é lista", 5, "exatamente 5"),
    ([None, *_slides(4)[1:]], 4, "slide 1 sem titulo"),
])
def test_validar_slides_rejeita(slides, n, trecho):
    with pytest.raises(ValueError, match=trecho):
        llm.validar_slides(slides, n)


def _con():
    return {"tipo": "openai", "base_url": f"{FAKE}/v1", "api_key": "", "modelo": "modelo-a", "nome": "teste"}


def test_carrossel_de_texto_recusa_slide_vazio_e_aceita_a_tentativa_seguinte(client, fake):
    fake.set(carrossel_modo="vazio")
    with pytest.raises(ValueError, match="slide 1 sem texto"):
        asyncio.run(llm.carrossel_de_texto(_con(), "Perfil de teste", "ideia de teste para o carrossel", 5))
    res = asyncio.run(llm.carrossel_de_texto(_con(), "Perfil de teste", "ideia de teste para o carrossel", 5))
    assert len(res["slides"]) == 5 and all(s["titulo"] and s["texto"] for s in res["slides"])


def test_carrossel_de_texto_recusa_quantidade_errada(client, fake):
    fake.set(carrossel_modo="faltando")
    with pytest.raises(ValueError, match="exatamente 5"):
        asyncio.run(llm.carrossel_de_texto(_con(), "Perfil de teste", "ideia de teste para o carrossel", 5))


def test_agente_carousel_planner_confere_vazio_e_quantidade():
    agente = CarouselPlannerAgente()
    base = {"titulo_carrossel": "t", "total_slides": 4, "legenda_instagram": "l", "cta": "c", "hashtags": ["#a"]}
    completo = {**base, "slides": _slides(4)}
    assert agente.validar(completo) == []
    assert any("slide 2 sem texto" in e for e in agente.validar({**base, "slides": _slides(4, {2: {"texto": ""}})}))
    token = _N_PEDIDO.set(6)
    try:
        assert any("exatamente 6" in e for e in agente.validar(completo))
    finally:
        _N_PEDIDO.reset(token)


# ---------------- frases do contexto copiadas (T3) ----------------
CONTEXTO = """# Padrões que são meus
- Estrutura "Não é X, é Y."
- Pares de contraste: "Minha carreira subia. Minha saúde caía."
- Fecho em frase-síntese: "No fim, você sabe o que pegar, onde conseguir e como fazer."
Direto, pessoal, primeira pessoa. Trato por você e uso frases curtas com contraste marcante e sem enrolação corporativa.
"""


@pytest.mark.parametrize("texto,achado", [
    ("Hoje penso nisso. Minha carreira subia. Minha saúde caía. E eu nem via.", "minha carreira subia minha saúde caía"),
    ("MINHA CARREIRA SUBIA, MINHA SAÚDE CAÍA!", "minha carreira subia minha saúde caía"),
    ("No fim, você sabe o que pegar, onde conseguir e como fazer. Simples.", "no fim você sabe o que pegar onde"),
    ("Direto, pessoal, primeira pessoa. Trato por você e uso frases curtas com contraste", "direto pessoal primeira pessoa trato por você e"),
])
def test_trecho_copiado_acha_frase_modelo_e_oito_palavras_seguidas(texto, achado):
    assert llm.trecho_copiado(texto, CONTEXTO) == achado


@pytest.mark.parametrize("texto", [
    "Planilha demora, automação resolve. Não é moda, é controle.",   # estrutura "Não é X, é Y" é jeito, não frase copiada
    "Minha carreira subia rápido, mas a saúde piorou.",              # só parte da frase de exemplo
    "No fim, quem decide é o orçamento da empresa.",
    "",
])
def test_trecho_copiado_deixa_passar_texto_proprio(texto):
    assert llm.trecho_copiado(texto, CONTEXTO) is None


def test_posts_recusam_texto_copiado_do_contexto(client, fake):
    # o LLM falso devolve "Não é moda, é controle." no card e "Slide i da ideia" nos slides: o contexto abaixo os torna cópia
    ctx = 'Exemplos: "Não é moda, é controle." e "Texto curto do slide 1."'
    with pytest.raises(ValueError, match="copiou do perfil"):
        asyncio.run(llm.post_de_texto(_con(), ctx, "ideia de teste para o post"))
    with pytest.raises(ValueError, match="copiou do perfil"):
        asyncio.run(llm.carrossel_de_texto(_con(), ctx, "ideia de teste para o carrossel", 5))
    asyncio.run(llm.post_de_texto(_con(), "Perfil sem exemplos entre aspas.", "ideia de teste para o post"))


# ---------------- hashtags duplicadas na legenda (T4) ----------------
def _hashtags(texto):
    return [h.lower() for h in __import__("re").findall(r"#\w+", texto)]


def test_montar_legenda_nao_repete_hashtags_que_o_modelo_escreveu_no_texto():
    # o caso real do Qwen: hashtags no fim do corpo e de novo na lista "hashtags"
    corpo = "Planilhas demoram. Vem nos conhecer! #IAempresas #AutomaçãoIA #Produtividade"
    leg = llm.montar_legenda(corpo, "", ["#IAempresas", "#AutomaçãoIA", "#Produtividade", "#Inovação", "#iaempresas"])
    tags = _hashtags(leg)
    assert len(tags) == len(set(tags)) == 4, leg
    assert leg.startswith("Planilhas demoram. Vem nos conhecer!\n\n#IAempresas")
    assert leg.count("\n\n#") == 1, "um único bloco de hashtags, no fim"


def test_montar_legenda_linha_so_de_hashtags_e_cta_com_hashtag():
    leg = llm.montar_legenda("Texto.\n\n#um #dois\n\nMais texto.", "Siga e salve #dois #tres", ["#dois", "#quatro"])
    tags = _hashtags(leg)
    assert sorted(tags) == ["#dois", "#quatro", "#tres", "#um"], leg
    assert leg.index("Mais texto.") < leg.index("#um")


def test_montar_legenda_preserva_hashtag_no_meio_da_frase_e_nao_a_repete_no_bloco():
    leg = llm.montar_legenda("Eu uso #IA todo dia no trabalho.", "", ["#ia", "#Dados"])
    assert leg == "Eu uso #IA todo dia no trabalho.\n\n#Dados"


def test_montar_legenda_sem_hashtags_continua_igual():
    assert llm.montar_legenda("Só texto.", "Comente.", []) == "Só texto.\n\nComente."
    assert llm.montar_legenda("Só texto.", "", ["#a", "#b"]) == "Só texto.\n\n#a #b"
