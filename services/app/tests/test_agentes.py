"""Testes unitários para o pacote de Agentes Inteligentes e Especialistas."""
from app.agentes import (
    AudienceInsightsAgente,
    BaseAgente,
    CaptionWriterAgente,
    CarouselPlannerAgente,
    ContentPlannerAgente,
    CriticoAgente,
    DiretorArteAgente,
    EstrategistaAgente,
    HashtagStrategistAgente,
    HookExtractorAgente,
    HumanizerAgente,
    OrquestradorAgente,
    ProfileOptimizerAgente,
    RepurposerAgente,
    carregar_skill,
    listar_skills_disponiveis,
    obter_prompt_skill,
)


def test_base_agente_montar_system():
    agente = BaseAgente()
    perfil = {
        "nome": "Emerson",
        "contexto_md": "Especialista em segurança eletrônica e IA aplicada. Tom direto e provocativo.",
        "palavras_chave": "inteligencia artificial, cftv, automacao",
    }
    sys = agente.montar_system(perfil, "Você cria roteiros.")
    assert "Emerson" in sys
    assert "segurança eletrônica" in sys
    assert "Português do Brasil - 2026" in sys
    assert "NUNCA use frases clichês de IA" in sys
    assert "Você cria roteiros." in sys


def test_humanizer_auditoria_texto_limpo():
    texto_natural = (
        "Testei uma automação nova no escritório hoje. "
        "A esteira reduziu nosso tempo de resposta pela metade. "
        "O código completo está no GitHub para quem quiser ver."
    )
    resultado = HumanizerAgente.auditar(texto_natural)
    assert resultado["score_ia"] == 0
    assert resultado["nivel"] == "baixo"
    assert len(resultado["termos_encontrados"]) == 0
    assert "Texto soa natural" in resultado["diagnostico"][0]


def test_humanizer_auditoria_texto_cliche_ia():
    texto_ia = (
        "No mundo dinâmico de hoje, é crucial entender que a IA é um divisor de águas. "
        "Mergulhe fundo nessa jornada transformadora — e descubra o pulo do gato! 🚀🔥💡🎯\n"
        "🚀 Ponto um\n"
        "🚀 Ponto dois\n"
        "🚀 Ponto três\n"
    )
    resultado = HumanizerAgente.auditar(texto_ia)
    assert resultado["score_ia"] >= 50
    assert resultado["nivel"] in ("alto", "moderado")
    assert len(resultado["termos_encontrados"]) >= 3
    assert resultado["total_emojis"] >= 4


def test_caption_writer_validacao():
    agente = CaptionWriterAgente()

    # Dados válidos
    dados_ok = {
        "hook_125": "Pare de gastar 3 horas fazendo posts manuais. Veja essa esteira em 2026:",
        "corpo": "Conectamos um LLM local a um gerador de cards e publicador automático.",
        "cta": "Salve esse post para estruturar a sua.",
        "objetivo": "saves",
        "legenda_completa": "Pare de gastar 3 horas... Salve esse post.",
        "hashtags_sugeridas": ["#ia", "#automacao", "#instagram"],
    }
    assert agente.validar(dados_ok) == []

    # Hook excessivamente longo
    dados_hook_longo = dict(dados_ok)
    dados_hook_longo["hook_125"] = "A" * 200
    erros = agente.validar(dados_hook_longo)
    assert any("hook_125 longo demais" in e for e in erros)

    # Objetivo inválido
    dados_obj_invalido = dict(dados_ok)
    dados_obj_invalido["objetivo"] = "invalido"
    erros = agente.validar(dados_obj_invalido)
    assert any("objetivo deve ser" in e for e in erros)


def test_hashtag_strategist_normalizar_e_validar():
    agente = HashtagStrategistAgente()
    brutas = ["#Segurança Eletrônica!", "cftv", "IA-Aplicada", "#cftv"]
    normalizadas = agente.normalizar(brutas)
    assert "#segurançaeletrônica" in normalizadas or "#seguranaeletrnica" in normalizadas or any("cftv" in t for t in normalizadas)
    assert normalizadas.count("#cftv") == 1  # sem duplicatas

    dados_ok = {
        "nicho": ["#segurancaeletronica"],
        "medio": ["#cftvbrasil"],
        "amplo": ["#tecnologia"],
        "conjunto_final": ["#segurancaeletronica", "#cftvbrasil", "#tecnologia"],
        "justificativa_seo": "Palavras-chave de alto alinhamento com instaladores e gestores.",
    }
    assert agente.validar(dados_ok) == []


def test_hook_extractor_validacao():
    agente = HookExtractorAgente()
    dados_ok = {
        "formula_identificada": "Contraintuitivo / Quebra de Paradigma",
        "por_que_funciona": "Choca o leitor ao contradizer o senso comum.",
        "template_em_branco": "Pare de fazer [X] se você deseja [Y].",
        "variacoes_para_o_autor": [
            "Pare de configurar câmeras analógicas se você busca segurança corporativa de verdade.",
            "Pare de usar IA apenas como chatbot se você quer automação real.",
            "Pare de gastar horas em reuniões se você pode resolver com agentes locais.",
        ],
    }
    assert agente.validar(dados_ok) == []


def test_carousel_planner_validacao():
    agente = CarouselPlannerAgente()
    dados_ok = {
        "titulo_carrossel": "Como orquestrar agentes inteligentes locais",
        "total_slides": 4,
        "slides": [
            {"slide_n": 1, "tipo": "capa", "titulo": "Pare de usar IA sozinho", "texto": "Conheça a equipe autônoma"},
            {"slide_n": 2, "tipo": "conteudo", "titulo": "O Orquestrador", "texto": "Recebe o pedido e delega."},
            {"slide_n": 3, "tipo": "conteudo", "titulo": "Os Especialistas", "texto": "Fazem legendas e corte."},
            {"slide_n": 4, "tipo": "cta", "titulo": "Próximo passo", "texto": "Salve para estruturar sua equipe."},
        ],
        "legenda_instagram": "A esteira completa de agentes locais.",
        "cta": "Salve para consultar.",
        "hashtags": ["#ia", "#automacao", "#python"],
    }
    assert agente.validar(dados_ok) == []


def test_orquestrador_comandos():
    import asyncio
    async def _run():
        orquestrador = OrquestradorAgente()
        perfil = {"nome": "Emerson", "contexto_md": ""}
        con = {"tipo": "fake"}

        # Comando /auditar
        msg_auditar = "/auditar No mundo dinâmico de hoje, mergulhe fundo nessa jornada transformadora!"
        resp1 = await orquestrador.processar_mensagem(con, perfil, "12345", msg_auditar)
        assert resp1["acao"] == "auditar"
        assert "Auditoria Anti-IA" in resp1["resposta_telegram"]
        assert resp1["dados"]["score_ia"] > 0

        # Comando /hook com mensagem de ajuda quando vazio
        resp2 = await orquestrador.processar_mensagem(con, perfil, "12345", "/hook")
        assert resp2["acao"] == "ajuda_hook"
        assert "Envie o gancho viral" in resp2["resposta_telegram"]

        # Comando /hashtags com mensagem de ajuda quando vazio
        resp3 = await orquestrador.processar_mensagem(con, perfil, "12345", "/hashtags")
        assert resp3["acao"] == "ajuda_hashtags"
        assert "Informe o tema" in resp3["resposta_telegram"]

        # Comando /carrossel com mensagem de ajuda quando vazio
        resp4 = await orquestrador.processar_mensagem(con, perfil, "12345", "/carrossel")
        assert resp4["acao"] == "ajuda_carrossel"
        assert "Envie a ideia do carrossel" in resp4["resposta_telegram"]

    asyncio.run(_run())


def test_repurposer_limpeza_e_validacao():
    agente = RepurposerAgente()
    texto_com_artefato = "Artigo sobre CFTV. Leia o artigo completo no blog e veja o link nos comentários!"
    limpo = agente.limpar_artefatos_externos(texto_com_artefato)
    assert "link nos comentários" not in limpo
    assert "leia o artigo completo no blog" not in limpo.lower()

    dados_ok = {
        "formato": "carrossel",
        "hook_125": "Por que sistemas analógicos de CFTV estão deixando sua empresa vulnerável hoje:",
        "conteudo_adaptado": "Slides técnicos demonstrando falhas e como migrar para IP com IA.",
        "cta": "Salve para não esquecer.",
        "resumo_mudancas": "Convertido artigo de 1000 palavras em carrossel de 5 slides.",
        "hashtags": ["#cftv", "#seguranca", "#ia"],
    }
    assert agente.validar(dados_ok) == []

    dados_com_artefato = dict(dados_ok)
    dados_com_artefato["conteudo_adaptado"] = "Veja no link no primeiro comentário para mais."
    erros = agente.validar(dados_com_artefato)
    assert any("link no primeiro comentário" in e for e in erros)


def test_content_planner_validacao():
    agente = ContentPlannerAgente()
    dados_ok = {
        "foco": "Crescimento e Autoridade em Segurança",
        "dias": [
            {
                "dia": 1,
                "formato": "reel",
                "objetivo": "follows",
                "tema": "O erro de R$ 50 mil em câmeras",
                "gancho_sugerido": "Essa configuração estúpida queima câmeras IP todo mês:",
                "resumo_executivo": "Demonstração de switch sem PoE balanceado",
            },
            {
                "dia": 2,
                "formato": "carrossel",
                "objetivo": "saves",
                "tema": "Checklist de segurança perimetral",
                "gancho_sugerido": "Antes de gastar com alarmes caros, confira esses 5 pontos:",
                "resumo_executivo": "Slides práticos para gestores",
            },
        ],
        "recomendacao_geral": "Grave os Reels no ambiente real da oficina ou rack de TI.",
    }
    assert agente.validar(dados_ok) == []

    dados_invalido = dict(dados_ok)
    dados_invalido["dias"] = [{"dia": 1, "formato": "formato_estranho", "objetivo": "invalido", "tema": ""}]
    erros = agente.validar(dados_invalido)
    assert len(erros) >= 2


def test_profile_optimizer_validacao():
    agente = ProfileOptimizerAgente()
    dados_ok = {
        "nome_seo_sugerido": "Emerson | Segurança Eletrônica & IA",
        "opcoes_bio": [
            {
                "tipo": "direta e técnica",
                "texto": "Projetos de segurança eletrônica com IA integrada.\n+10 anos protegendo patrimônios.\nFale direto comigo no WhatsApp 👇",
                "cta_link": "Link direto para orçamento",
            }
        ],
        "destaques_sugeridos": [{"titulo": "Comece Aqui", "objetivo": "Apresentação"}],
        "grid_fixados": [{"posicao": 1, "tema": "Quem Sou", "foco": "Manifesto"}],
    }
    assert agente.validar(dados_ok) == []

    dados_bio_longa = dict(dados_ok)
    dados_bio_longa["opcoes_bio"] = [{"tipo": "longa", "texto": "A" * 200, "cta_link": "link"}]
    erros = agente.validar(dados_bio_longa)
    assert any("limite do Instagram" in e for e in erros)


def test_audience_insights_validacao():
    agente = AudienceInsightsAgente()
    dados_ok = {
        "perfil_do_seguidor_ideal": "Empresário ou gestor predial que precisa proteger seu patrimônio sem dor de cabeça.",
        "dores_principais": [{"dor": "Câmeras que gravam borrado quando mais precisa", "impacto_emocional": "Sensação de impotência"}],
        "objecoes_comuns": [{"objecao": "Segurança moderna é cara demais", "como_quebrar": "O custo de um roubo é 10x maior"}],
        "angulos_de_conteudo_virais": [
            {
                "tipo": "provocacao",
                "ideia_central": "Câmeras analógicas em 2026",
                "gancho_sugerido": "Se o seu técnico ainda instala isso, demita ele hoje:",
            }
        ],
    }
    assert agente.validar(dados_ok) == []


def test_skills_loader_e_agentes_estudio_criativo():
    skills = listar_skills_disponiveis()
    nomes = {s["nome"].lower() for s in skills}
    for req in ("estrategista", "diretor-de-arte", "critico-visual", "caption-writer"):
        assert req in nomes
        sk = carregar_skill(req)
        assert sk["instrucoes"]
        assert obter_prompt_skill(req)

    # Verifica que BaseAgente combina SKILL.md + contrato JSON do agente
    est = EstrategistaAgente()
    sys_est = est.montar_system({"nome": "Autor", "contexto_md": "Contexto X"}, "Responda em JSON: tese_central")
    assert "Estrategista" in sys_est
    assert "Responda em JSON: tese_central" in sys_est

    assert est.validar({
        "formato": "feed",
        "objetivo": "saves",
        "angulo": "contraintuitivo",
        "fatos_centrais": ["Ponto 1", "Ponto 2"],
        "proposta_de_valor": "Fato central comprovado na prática.",
        "palavras_chave": ["ia", "dados"],
    }) == []

    da = DiretorArteAgente()
    assert da.validar({
        "layout": "editorial",
        "justificativa_layout": "Tese forte",
        "paleta": {"fundo": "#080a0f", "texto_primario": "#ffffff", "texto_secundario": "#94a3b8", "destaque": "#00f0ff", "borda": "rgba(255,255,255,0.1)"},
        "palavras_destaque": ["Fato"],
        "selo": {"usar": False, "estilo": "nenhum", "texto": "", "subtexto": ""},
        "imagem": {"usar": False, "busca_ingles": "", "estilo_visual": ""},
    }) == []

    cr = CriticoAgente()
    assert cr.validar({
        "aprovado": True,
        "score": 9,
        "problemas": [],
        "sugestao_ajuste": "",
        "layout_alternativo": "",
    }) == []


