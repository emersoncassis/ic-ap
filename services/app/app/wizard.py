"""Wizard Inteligente de Onboarding e Criação de Perfil.

Projetado para usuários leigos ou criadores de conteúdo:
1. Permite criar o perfil via entrevista conversacional com IA (nicho, estilo, crenças).
2. Permite importar um relatório extraído do Meta AI e gerar o meu_contexto.md estruturado.
3. Fornece modelo determinístico de alta qualidade caso nenhuma IA esteja configurada ainda.
"""
import json
import logging
import urllib.parse
from typing import Any

from . import db, llm

logger = logging.getLogger(__name__)


PROMPT_SISTEMA_CONTEXTO = """
Você é um estrategista sênior de conteúdo para Instagram no Brasil (regras de 2026).
Sua missão é transformar as respostas ou o relatório do criador em um arquivo `meu_contexto.md`
extremamente autoral, autêntico e focado em alta retenção.

Regras de 2026 obrigatórias no documento:
- Ganchos visuais e verbais nos primeiros 125 caracteres (abertura de loop).
- Tom humano, assertivo e autoral (zero clichês de IA como "delve", "game-changer", "revolucionário").
- 1 CTA única orientada ao objetivo principal (salvar ou compartilhar).
- Máximo de 1 travessão a cada 100 palavras.

Estrutura exata do markdown a ser devolvido:
# Contexto e Tom de Voz: {Nome} ({Handle})

## 1. Quem sou eu & Posicionamento
[Resumo em primeira pessoa do nicho, experiência e autoridade]

## 2. Minhas Crenças Fortes (O que defendo)
- [Crença 1 com opinião firme]
- [Crença 2]
- [Crença 3]

## 3. Inimigos Comuns (O que combato)
- [Inimigo 1: mito ou erro comum do nicho]
- [Inimigo 2: fórmula pronta / superficialidade]

## 4. Diretrizes de Tom de Voz (2026)
- Estilo: [Descrição do ritmo, vocabulário e tom]
- Ganchos: [Como abrir os posts para segurar a atenção]
- O que NUNCA falar: [Palavras proibidas e clichês]

## 5. Pilares de Conteúdo
- [Pilar 1]
- [Pilar 2]
- [Pilar 3]
""".strip()


async def gerar_contexto_da_entrevista(
    nome: str,
    handle: str,
    nicho: str,
    estilo: str,
    temas: str,
    crencas: str = "",
    inimigos: str = "",
) -> str:
    """Gera o meu_contexto.md a partir de perguntas simples."""
    prompt_usuario = f"""
Nome: {nome}
Instagram: @{handle.lstrip('@')}
Nicho/Profissão: {nicho}
Estilo de comunicação preferido: {estilo}
Principais temas que domina: {temas}
O que você mais defende/acredita: {crencas or 'Praticidade, transparência e resultados reais sem enrolação'}
O que você mais critica no seu mercado: {inimigos or 'Gurus de palco, promessas fáceis e conteúdo genérico de IA'}

Gere o arquivo `meu_contexto.md` completo seguindo a estrutura solicitada.
""".strip()

    # Tenta usar a conexão padrão cadastrada (nuvem ou Ollama local)
    con = db.one("SELECT * FROM llm_conexoes WHERE padrao=1") or db.one("SELECT * FROM llm_conexoes ORDER BY id LIMIT 1")
    if con and con.get("modelo"):
        try:
            resposta = await llm._chat(
                con,
                system=PROMPT_SISTEMA_CONTEXTO,
                user=prompt_usuario,
                temperature=0.7,
                schema={"type": "string"},
            )
            if resposta and len(resposta.strip()) > 100:
                return resposta.strip()
        except Exception as e:
            logger.warning(f"Não foi possível gerar contexto via LLM: {e}. Usando modelo determinístico.")

    # Fallback Determinístico Inteligente (Funciona 100% offline e sem IA)
    return _template_deterministico(nome, handle, nicho, estilo, temas, crencas, inimigos)


PROMPT_ANALISE_META_AI_SISTEMA = """
Você é um estrategista sênior de conteúdo para Instagram no Brasil (regras de 2026).
Sua missão é transformar o relatório/análise do criador extraído do Meta AI em:
1. Um documento `meu_contexto.md` autoral de alta retenção (ganchos nos primeiros 125 chars, 1 CTA única, crenças fortes, inimigos comuns).
2. Palavras-chave estratégicas para busca de pautas e notícias que alimentam o feed do criador.
3. A identificação do nicho principal e temas de maior engajamento.

Responda EXCLUSIVAMENTE em formato JSON com o seguinte schema:
{
  "nicho": "Nome do nicho (ex.: IA Privada & Cibersegurança)",
  "palavras_chave": "8 a 15 termos separados por vírgula para monitorar notícias (ex.: ia privada, on-premise, lgpd, cibersegurança, vazamento de dados)",
  "temas": ["Tema 1", "Tema 2", "Tema 3"],
  "pacote_id": "ia_privada_seguranca" | "tecnologia_geral" | "negocios_gestao" | "marketing_vendas" | "financas_investimentos" | "saude_longevidade" | "direito_compliance",
  "contexto_md": "Markdown completo do meu_contexto.md com: # Contexto e Tom de Voz: [Nome] (@[Handle])\\n\\n## 1. Quem sou eu & Posicionamento\\n...\\n\\n## 2. Minhas Crenças Fortes\\n...\\n\\n## 3. Inimigos Comuns\\n...\\n\\n## 4. Destaques da Análise do Meta AI\\n...\\n\\n## 5. Diretrizes de Tom de Voz (2026)\\n- Gancho nos primeiros 125 caracteres...\\n- 1 CTA única...\\n\\n## 6. Pilares de Conteúdo\\n..."
}
""".strip()


def gerar_url_google_news(termo: str) -> str:
    """Gera feed RSS dinâmico do Google News para um termo ou conjunto de palavras."""
    q = urllib.parse.quote(termo.strip())
    return f"https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"


def gerar_feeds_contextuais(
    nicho: str,
    palavras_chave: str,
    temas: list[str] | None = None,
    pacote_id: str = "",
) -> list[dict[str, str]]:
    """Gera lista de feeds RSS em contexto direto com a análise do perfil."""
    feeds_result: list[dict[str, str]] = []
    
    # Se identificou pacote, inclui feeds curados do pacote
    pacote = PACOTES_FEEDS.get(pacote_id) or PACOTES_FEEDS.get("tecnologia_geral")
    if pacote:
        for f in pacote["feeds"]:
            feeds_result.append({"nome": f[0], "url": f[1], "tema": f[2]})
            
    # Adiciona Google News RSS específico das palavras-chave do nicho
    pks = [p.strip() for p in palavras_chave.split(",") if p.strip()]
    top_termos = pks[:3] if pks else [nicho]
    busca_query = " OR ".join([f'"{t}"' if " " in t else t for t in top_termos])
    gnews_url = gerar_url_google_news(busca_query)
    
    if not any(f["url"] == gnews_url for f in feeds_result):
        feeds_result.append({
            "nome": f"Google News: {nicho}",
            "url": gnews_url,
            "tema": "noticias-em-alta",
        })
        
    return feeds_result


def _analisar_deterministico(relatorio: str, nome: str, handle: str) -> dict[str, Any]:
    txt = relatorio.lower()
    
    scores = {}
    for pid, pdata in PACOTES_FEEDS.items():
        palavras = [p.strip().lower() for p in pdata["palavras_chave"].split(",") if p.strip()]
        sc = sum(1 for w in palavras if w in txt)
        scores[pid] = sc
        
    melhor_pacote = max(scores, key=scores.get) if scores and max(scores.values()) > 0 else "tecnologia_geral"
    pdata = PACOTES_FEEDS[melhor_pacote]
    nicho_detectado = pdata["nome"].split(" ", 1)[-1]
    
    linhas = [l.strip("- *# ").strip() for l in relatorio.splitlines() if len(l.strip()) > 10 and not l.strip().startswith(("#", "http"))]
    destaques = linhas[:5] if linhas else ["Foco em autoridade técnica e aplicações práticas."]
    destaques_md = "\n".join(f"- {d}" for d in destaques)
    temas = destaques[:3] if destaques else [pdata["nome"]]
    palavras_chave = pdata["palavras_chave"]
    
    h = handle.lstrip("@")
    contexto_md = f"""# Contexto e Tom de Voz: {nome} (@{h})

## 1. Quem sou eu & Posicionamento
Atuo com foco prático e autoridade no nicho de {nicho_detectado}. Construo conteúdo que resolve problemas reais e gera valor acionável para o meu público.

## 2. Minhas Crenças Fortes (O que defendo)
- Conteúdo deve gerar transformação real, prática e verificável.
- Honestidade, técnica e transparência superam qualquer hack de algoritmo passageiro.
- O foco deve ser na retenção qualificada de quem salva e compartilha o post.

## 3. Inimigos Comuns (O que combato)
- Textos robóticos e clichês de IA sem ponto de vista pessoal ou opinião autoral.
- Fórmulas mágicas, superficialidade e gurus sem experiência de campo.

## 4. Destaques Extraídos da Análise do Meta AI
{destaques_md}

## 5. Diretrizes de Tom de Voz (2026)
- Gancho obrigatório nos primeiros 125 caracteres (abertura de loop imediata).
- Frases curtas, ritmo ágil, sem palavras de preenchimento.
- 1 CTA única orientada ao objetivo principal (salvar para consultar ou compartilhar).
- Máximo de 1 travessão a cada 100 palavras.

## 6. Pilares de Conteúdo
{chr(10).join(f"- {t}" for t in temas)}
"""
    feeds = gerar_feeds_contextuais(nicho_detectado, palavras_chave, temas, melhor_pacote)
    return {
        "nicho": nicho_detectado,
        "palavras_chave": palavras_chave,
        "temas": temas,
        "pacote_id": melhor_pacote,
        "contexto_md": contexto_md.strip(),
        "feeds_sugeridos": feeds,
    }


async def analisar_relatorio_meta_ai(relatorio_meta_ai: str, nome: str, handle: str) -> dict[str, Any]:
    """Analisa o relatório extraído do Meta AI e gera contexto, palavras-chave e feeds contextuais."""
    prompt_usuario = f"""
Nome do criador: {nome}
Instagram: @{handle.lstrip('@')}

Aqui está o relatório/análise do perfil extraído do Meta AI:
---
{relatorio_meta_ai.strip()[:4000]}
---

Analise minuciosamente e devolva o JSON estruturado.
""".strip()

    con = db.one("SELECT * FROM llm_conexoes WHERE padrao=1") or db.one("SELECT * FROM llm_conexoes ORDER BY id LIMIT 1")
    if con and con.get("modelo"):
        try:
            resposta = await llm._chat(
                con,
                system=PROMPT_ANALISE_META_AI_SISTEMA,
                user=prompt_usuario,
                temperature=0.7,
                schema={"type": "object"},
            )
            if resposta and "{" in resposta and "}" in resposta:
                raw_json = resposta[resposta.find("{"):resposta.rfind("}") + 1]
                dados = json.loads(raw_json)
                if dados.get("contexto_md"):
                    nicho = dados.get("nicho", "Tecnologia & Inovação")
                    palavras_chave = dados.get("palavras_chave", "")
                    temas = dados.get("temas", [])
                    pacote_id = dados.get("pacote_id", "tecnologia_geral")
                    feeds = gerar_feeds_contextuais(nicho, palavras_chave, temas, pacote_id)
                    return {
                        "nicho": nicho,
                        "palavras_chave": palavras_chave,
                        "temas": temas,
                        "pacote_id": pacote_id,
                        "contexto_md": dados["contexto_md"].strip(),
                        "feeds_sugeridos": feeds,
                    }
        except Exception as e:
            logger.warning(f"Erro ao analisar relatório do Meta AI com LLM: {e}. Usando fallback determinístico.")

    return _analisar_deterministico(relatorio_meta_ai, nome, handle)


async def gerar_contexto_do_meta_ai(relatorio_meta_ai: str, nome: str, handle: str) -> str:
    """Sintetiza um relatório colado do Meta AI no formato de meu_contexto.md."""
    res = await analisar_relatorio_meta_ai(relatorio_meta_ai, nome, handle)
    return res["contexto_md"]


def _template_deterministico(
    nome: str,
    handle: str,
    nicho: str,
    estilo: str,
    temas: str,
    crencas: str,
    inimigos: str,
) -> str:
    """Gera um template estruturado e rico sem depender de chamada de rede."""
    h = handle.lstrip("@")
    temas_lista = [t.strip() for t in temas.split(",") if t.strip()] or [nicho]
    pilares = "\n".join(f"- {t}" for t in temas_lista)
    
    return f"""# Contexto e Tom de Voz: {nome} (@{h})

## 1. Quem sou eu & Posicionamento
- Sou {nome}, criador e especialista em {nicho}.
- Posicionamento: Traduzo conceitos de {nicho} em aplicações práticas, claras e sem rodeios para meu público.

## 2. Minhas Crenças Fortes (O que defendo)
- {crencas or 'A execução consistente e o aprendizado diário valem mais do que fórmulas mágicas.'}
- Profissionalismo com autenticidade: quem tenta agradar a todos não atrai ninguém.
- Foco em retenção real de conteúdo que vale a pena salvar e consultar depois.

## 3. Inimigos Comuns (O que combato)
- {inimigos or 'A superficialidade de quem repete clichês sem testar na prática.'}
- Modismos passageiros e posts genéricos gerados por IA sem personalidade.

## 4. Diretrizes de Tom de Voz (2026)
- Estilo: {estilo or 'Direto ao ponto, acessível, seguro e com ritmo dinâmico.'}
- Gancho: Sempre nos primeiros 125 caracteres, despertando curiosidade ou quebrando um mito.
- Vocabulário proibido: "No mundo agitado de hoje", "Embarque conosco", "Revolucionário", "Game changer".
- Formatação: Parágrafos curtos (1 a 2 frases), uso moderado de emojis (máximo 2 a 3 por post).

## 5. Pilares de Conteúdo
{pilares}
"""


PACOTES_FEEDS = {
    "ia_privada_seguranca": {
        "id": "ia_privada_seguranca",
        "nome": "🛡️ IA Privada, Cibersegurança & LGPD",
        "descricao": "Vazamentos, privacidade, compliance, riscos de IA e infraestrutura corporativa.",
        "palavras_chave": "ia privada, on-premise, lgpd, risco jurídico, infraestrutura, servidores locais, segurança de dados, compliance, vazamento, governança, dados corporativos, chatgpt",
        "feeds": [
            ("CISO Advisor Brasil", "https://www.cisoadvisor.com.br/feed/", "segurança-lgpd"),
            ("Canaltech Segurança", "https://canaltech.com.br/rss/seguranca/", "cibersegurança"),
            ("The Register Enterprise", "https://www.theregister.com/headlines.atom", "infraestrutura-onpremise"),
            ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "ia-corporativa"),
            ("MIT Technology Review", "https://www.technologyreview.com/feed/", "ia-pesquisa"),
        ],
    },
    "tecnologia_geral": {
        "id": "tecnologia_geral",
        "nome": "🚀 Tecnologia, Inovação & Startups",
        "descricao": "Tendências globais de tech, IA geral, automação, mercado de software e startups.",
        "palavras_chave": "inteligência artificial, inovação, startups, tecnologia, software, automação, produtividade, apps",
        "feeds": [
            ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "ia"),
            ("MIT Technology Review", "https://www.technologyreview.com/feed/", "ia"),
            ("Startupi", "https://startupi.com.br/feed/", "startups"),
            ("Tecnoblog", "https://tecnoblog.net/feed/", "tecnologia"),
            ("The Verge", "https://www.theverge.com/rss/index.xml", "tecnologia"),
        ],
    },
    "negocios_gestao": {
        "id": "negocios_gestao",
        "nome": "💼 Negócios, Gestão & Economia B2B",
        "descricao": "Estratégia corporativa, liderança, mercado financeiro e gestão empresarial.",
        "palavras_chave": "empresas, negócios, liderança, gestão, eficiência, produtividade, investimento, estratégia, b2b",
        "feeds": [
            ("Startupi", "https://startupi.com.br/feed/", "negocios"),
            ("Exame", "https://exame.com/feed/", "negocios"),
            ("The Register", "https://www.theregister.com/headlines.atom", "enterprise"),
        ],
    },
    "marketing_vendas": {
        "id": "marketing_vendas",
        "nome": "📈 Marketing Digital, Vendas & Creators",
        "descricao": "Tráfego pago, funis, mídias sociais, conversão e estratégia de creators.",
        "palavras_chave": "marketing digital, tráfego pago, conversão, instagram, criadores, vendas online, copy, e-commerce, audiência",
        "feeds": [
            ("Startupi Marketing", "https://startupi.com.br/feed/", "marketing"),
            ("E-Commerce Brasil", "https://www.ecommercebrasil.com.br/feed", "vendas-ecommerce"),
            ("Meio & Mensagem", "https://www.meioemensagem.com.br/feed", "publicidade-midia"),
        ],
    },
    "financas_investimentos": {
        "id": "financas_investimentos",
        "nome": "💰 Finanças, Investimentos & Cripto",
        "descricao": "Bolsa de valores, renda fixa, criptomoedas, macroeconomia e patrimônio.",
        "palavras_chave": "investimentos, mercado financeiro, renda fixa, ações, b3, dividendos, criptomoedas, bitcoin, taxa selic, inflação",
        "feeds": [
            ("InfoMoney", "https://www.infomoney.com.br/feed/", "mercados"),
            ("Exame Economia", "https://exame.com/feed/", "economia"),
            ("CoinTelegraph Brasil", "https://cointelegraph.com.br/rss", "cripto"),
        ],
    },
    "saude_longevidade": {
        "id": "saude_longevidade",
        "nome": "🌿 Saúde, Longevidade & Performance",
        "descricao": "Medicina preventiva, longevidade celular, biohacking, nutrição e bem-estar.",
        "palavras_chave": "saúde, longevidade, medicina preventiva, biohacking, sono, alimentação, suplementação, saúde mental, esportes",
        "feeds": [
            ("VivaBem UOL", "https://noticias.uol.com.br/saude/ultimas-noticias/index.xml", "saude"),
            ("STAT News", "https://www.statnews.com/feed/", "healthtech"),
        ],
    },
    "direito_compliance": {
        "id": "direito_compliance",
        "nome": "⚖️ Direito, Advocacia & Compliance",
        "descricao": "Legislação, tribunais, regulação de IA, segurança jurídica e direito digital.",
        "palavras_chave": "direito, advocacia, compliance, lgpd, stf, stj, regulação de ia, direito digital, processo civil, segurança jurídica",
        "feeds": [
            ("Consultor Jurídico (ConJur)", "https://www.conjur.com.br/feed/", "direito"),
            ("Migalhas", "https://www.migalhas.com.br/rss", "advocacia"),
        ],
    },
}


def vincular_feeds_perfil(perfil_id: int, feeds_lista: list[tuple[str, str, str] | dict[str, Any]]) -> int:
    """Insere feeds vinculados diretamente a um perfil específico."""
    inseridos = 0
    for item in feeds_lista:
        if isinstance(item, dict):
            nome = str(item.get("nome", ""))
            url = str(item.get("url", ""))
            tema = str(item.get("tema", ""))
        else:
            nome, url, tema = item
        url_limpa = url.strip()
        if not url_limpa:
            continue
        existe = db.one("SELECT id FROM feeds WHERE perfil_id=? AND url=?", (perfil_id, url_limpa))
        if not existe:
            db.x("INSERT INTO feeds(perfil_id, nome, url, tema, ativo) VALUES(?,?,?,?,1)",
                 (perfil_id, nome.strip() or url_limpa, url_limpa, tema.strip()))
            inseridos += 1
    return inseridos


async def aplicar_analise_meta_ai_ao_perfil(
    perfil_id: int,
    relatorio_meta_ai: str,
    substituir_feeds: bool = False,
) -> dict[str, Any]:
    """Processa a análise do Meta AI e aplica diretamente contexto e feeds ao perfil."""
    p = db.one("SELECT * FROM perfis WHERE id=?", (perfil_id,))
    if not p:
        raise ValueError("Perfil não encontrado.")

    analise = await analisar_relatorio_meta_ai(relatorio_meta_ai, p["nome"], p["handle"] or "perfil")
    
    db.x(
        "UPDATE perfis SET contexto_md=?, palavras_chave=?, meta_ai_analise=? WHERE id=?",
        (analise["contexto_md"], analise["palavras_chave"], relatorio_meta_ai.strip(), perfil_id),
    )

    if substituir_feeds:
        db.x("DELETE FROM feeds WHERE perfil_id=?", (perfil_id,))

    total_vinculados = vincular_feeds_perfil(perfil_id, analise["feeds_sugeridos"])
    db.log(
        perfil_id,
        None,
        "meta_ai_sync",
        f"Análise Meta AI aplicada: nicho '{analise['nicho']}', {total_vinculados} feeds vinculados",
    )

    return {
        "ok": True,
        "nicho": analise["nicho"],
        "palavras_chave": analise["palavras_chave"],
        "total_feeds": total_vinculados,
        "feeds": analise["feeds_sugeridos"],
        "contexto_md": analise["contexto_md"],
    }


def criar_perfil_wizard(
    nome: str,
    handle: str,
    contexto_md: str,
    palavras_chave: str = "",
    pacote_feeds: str = "",
    feeds_custom: list[tuple[str, str, str] | dict[str, Any]] | None = None,
    horarios: str = "09:00,18:00",
    telegram_chat_id: str = "",
    ativo: bool = True,
    meta_ai_analise: str = "",
) -> int:
    """Insere o perfil completo no banco de dados, vincula os feeds selecionados e ativa o perfil."""
    pk = palavras_chave.strip()
    if not pk and pacote_feeds in PACOTES_FEEDS:
        pk = PACOTES_FEEDS[pacote_feeds]["palavras_chave"]
    if not pk:
        pk = "inteligência artificial, tecnologia, inovação, automação, negócios"

    pid = db.x(
        "INSERT INTO perfis(nome, handle, ativo, contexto_md, horarios, palavras_chave, max_idade_horas, telegram_chat_id, meta_ai_analise, criado_em)"
        " VALUES(?,?,?,?,?,?,36,?,?,?)",
        (
            nome.strip(),
            handle.strip().lstrip("@"),
            1 if ativo else 0,
            contexto_md.strip(),
            horarios.strip() or "09:00,18:00",
            pk,
            telegram_chat_id.strip(),
            meta_ai_analise.strip(),
            db.now(),
        ),
    )

    feeds_para_vincular: list[tuple[str, str, str] | dict[str, Any]] = []
    if pacote_feeds in PACOTES_FEEDS:
        feeds_para_vincular.extend(PACOTES_FEEDS[pacote_feeds]["feeds"])

    if feeds_custom:
        feeds_para_vincular.extend(feeds_custom)

    if feeds_para_vincular:
        total = vincular_feeds_perfil(pid, feeds_para_vincular)
        db.log(pid, None, "wizard_feeds", f"{total} feeds vinculados ao perfil {nome}")

    db.log(pid, None, "wizard", f"Perfil {nome} criado e configurado via assistente inteligente")
    return pid
