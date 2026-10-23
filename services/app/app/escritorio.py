"""Módulo Escritório Virtual e Diagnóstico do Fluxo de Agentes.

Gera o estado em tempo real da produção, loops do sistema, telemetria dos agentes
e análise profunda de gargalos (onde está parando e por quê), no formato ilustrado
de um escritório/coworking virtual interativo.
"""
import re
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import config as C, db, pipeline, settings
from .tunnel import tunel


def obter_perfis() -> list[dict[str, Any]]:
    """Retorna perfis para o seletor do escritório."""
    return db.q("SELECT id, nome, handle, ativo, horarios, palavras_chave, max_idade_horas, llm_conexao_id FROM perfis ORDER BY id")


def diagnosticar_gargalos(perfil_id: int | None) -> list[dict[str, Any]]:
    """Identifica exatamente ONDE o fluxo está parando e POR QUÊ.
    
    Analisa os 7 principais pontos de retenção do pipeline:
    1. LLM / IA indisponível ou desconectada (bloqueio na Redação).
    2. Feeds vazios ou sem notícias recentes (bloqueio no Radar de Pauta).
    3. Posts gerados retidos aguardando aprovação humana (bloqueio na Pracinha de Pausa).
    4. Telegram bot sem token ou sem chat_id (bloqueio na Diretoria/Recepção).
    5. Túnel Cloudflare desconectado ou sem URL pública (bloqueio na Distribuição).
    6. Perfil desligado (bloqueio no Agendador / Scheduler).
    7. Posts em estado de falha recente (erro em render, mídia ou publicação).
    """
    gargalos = []
    
    # 1. Checagem de Conexão LLM
    conexoes = db.q("SELECT * FROM llm_conexoes WHERE modelo!=''")
    if not conexoes:
        gargalos.append({
            "id": "sem_llm",
            "sala_id": "sala_redacao",
            "sala_nome": "Mesa de Redação & Ganchos",
            "titulo": "Sem Modelo de Linguagem (LLM) Configurado",
            "motivo": "A equipe de redação não tem IA para gerar manchetes, legendas e roteiros. O pipeline não consegue produzir copy.",
            "gravidade": "critica",
            "icone": "🛑",
            "acao_texto": "Configurar LLM",
            "acao_url": "/llm",
            "solucao": "Cadastre um modelo local (Ollama) ou provedor de nuvem na aba LLM.",
        })
    elif perfil_id:
        p = pipeline.perfil(perfil_id)
        if p and p.get("llm_conexao_id"):
            con_especifica = db.one("SELECT * FROM llm_conexoes WHERE id=?", (p["llm_conexao_id"],))
            if not con_especifica:
                gargalos.append({
                    "id": "llm_perfil_inexistente",
                    "sala_id": "sala_redacao",
                    "sala_nome": "Mesa de Redação & Ganchos",
                    "titulo": "Conexão LLM do Perfil Não Encontrada",
                    "motivo": f"O perfil #{perfil_id} está apontando para uma conexão LLM que foi apagada.",
                    "gravidade": "critica",
                    "icone": "🛑",
                    "acao_texto": "Ajustar no Perfil",
                    "acao_url": f"/perfis/{perfil_id}",
                    "solucao": "Selecione uma conexão válida nas configurações do perfil.",
                })

    # 2. Checagem de Perfil Ativo / Desligado
    if perfil_id:
        p = pipeline.perfil(perfil_id)
        if p and not p.get("ativo"):
            gargalos.append({
                "id": "perfil_desligado",
                "sala_id": "sala_orquestrador",
                "sala_nome": "Diretoria & Orquestrador",
                "titulo": "Perfil Desligado (Modo Stand-by)",
                "motivo": "O perfil está configurado com 'ativo = 0'. O agendador automático está pausado e não criará posts nos horários marcados.",
                "gravidade": "aviso",
                "icone": "⏸️",
                "acao_texto": "Ativar Perfil",
                "acao_url": f"/perfis/{perfil_id}",
                "solucao": "Marque a caixa 'Ligado' nas configurações gerais do perfil.",
            })

    # 3. Checagem de Feeds e Matérias Primas (Radar)
    if perfil_id:
        p = pipeline.perfil(perfil_id)
        feeds_perfil = db.q("SELECT * FROM feeds WHERE ativo=1 AND perfil_id=?", (perfil_id,))
        feeds_globais = db.q("SELECT * FROM feeds WHERE ativo=1 AND perfil_id IS NULL")
        total_ativos = len(feeds_perfil) or len(feeds_globais)
        
        if total_ativos == 0 and not settings.segredo("meta_ai_cookies"):
            gargalos.append({
                "id": "sem_feeds",
                "sala_id": "sala_radar",
                "sala_nome": "Radar de Pauta & Tendências",
                "titulo": "Nenhum Feed RSS Ativo para o Perfil",
                "motivo": "O radar não possui nenhuma fonte RSS configurada para pesquisar notícias do seu nicho.",
                "gravidade": "critica",
                "icone": "📡",
                "acao_texto": "Vincular Feeds",
                "acao_url": f"/perfis/{perfil_id}#feeds",
                "solucao": "Importe um pacote temático ou adicione feeds RSS na página do perfil.",
            })
        else:
            # Verifica se o último ciclo de busca de pautas reportou zero candidatas
            max_h = p.get("max_idade_horas", 36) if p else 36
            ultimo_ev_pauta = db.one(
                "SELECT tipo, detalhe FROM eventos WHERE perfil_id=? AND tipo IN ('sem_candidatas', 'pauta_vazia') ORDER BY id DESC LIMIT 1",
                (perfil_id,)
            )
            tem_posts_recentes = bool(db.one("SELECT 1 FROM posts WHERE perfil_id=? LIMIT 1", (perfil_id,)))
            if ultimo_ev_pauta and not tem_posts_recentes and not (perfil_id in pipeline.RUNNING):
                gargalos.append({
                    "id": "feeds_sem_novidades",
                    "sala_id": "sala_radar",
                    "sala_nome": "Radar de Pauta & Tendências",
                    "titulo": f"Sem Notícias Novas nas Últimas {max_h} Horas",
                    "motivo": f"Os feeds foram consultados, mas nenhuma matéria fresca com as palavras-chave ('{p.get('palavras_chave') or 'todas'}') foi encontrada dentro da janela de tempo.",
                    "gravidade": "alerta",
                    "icone": "⏳",
                    "acao_texto": "Ajustar Horas/Temas",
                    "acao_url": f"/perfis/{perfil_id}",
                    "solucao": "Aumente a idade máxima das notícias (ex.: para 48h ou 72h) ou importe novos feeds no perfil.",
                })

    # 4. Checagem de Posts Retidos Aguardando Aprovação (Pracinha de Pausa / Sala de Espera)
    query_pendentes = "SELECT id, manchete, noticia_titulo, criado_em FROM posts WHERE estado='aguardando_aprovacao'"
    args_pend = ()
    if perfil_id:
        query_pendentes += " AND perfil_id=?"
        args_pend = (perfil_id,)
    query_pendentes += " ORDER BY id DESC"
    pendentes = db.q(query_pendentes, args_pend)
    
    if pendentes:
        qtd = len(pendentes)
        gargalos.append({
            "id": "aguardando_aprovacao",
            "sala_id": "sala_cafe",
            "sala_nome": "Pracinha de Pausa & Aprovação",
            "titulo": f"{qtd} Post(s) Aguardando Sua Aprovação no Telegram",
            "motivo": "A esteira produziu o conteúdo, gerou o card visual e enviou para o bot do Telegram. O fluxo está parado esperando seu clique em 'Postar' ou 'Agendar'.",
            "gravidade": "alerta",
            "icone": "☕",
            "acao_texto": "Ver Fila de Aprovação",
            "acao_url": "/",
            "solucao": "Abra seu Telegram ou vá até a aba 'Fila' para aprovar ou agendar as postagens.",
            "itens_pendentes": [p.get("manchete") or p.get("noticia_titulo") or f"Post #{p['id']}" for p in pendentes[:3]],
        })

    # 5. Checagem do Bot do Telegram
    tem_tg = bool(settings.telegram_token())
    if not tem_tg:
        gargalos.append({
            "id": "sem_telegram",
            "sala_id": "sala_orquestrador",
            "sala_nome": "Diretoria & Orquestrador",
            "titulo": "Bot do Telegram Desconectado (Sem Token)",
            "motivo": "O token do Telegram não está configurado. O Orquestrador não consegue enviar cards de aprovação nem responder seus comandos.",
            "gravidade": "critica",
            "icone": "🤖",
            "acao_texto": "Conectar Telegram",
            "acao_url": "/conexoes",
            "solucao": "Gere um bot no @BotFather e salve o token em 'Conexões e acesso'.",
        })
    elif perfil_id:
        p = pipeline.perfil(perfil_id)
        if p and not p.get("telegram_chat_id"):
            gargalos.append({
                "id": "sem_chat_id",
                "sala_id": "sala_orquestrador",
                "sala_nome": "Diretoria & Orquestrador",
                "titulo": "Perfil Sem Telegram Chat ID Vinculado",
                "motivo": "O bot existe, mas este perfil não sabe para qual chat privado enviar os cards aprováveis.",
                "gravidade": "alerta",
                "icone": "💬",
                "acao_texto": "Vincular Chat ID",
                "acao_url": f"/perfis/{perfil_id}",
                "solucao": "Envie /start para o seu bot no Telegram e preencha seu Chat ID no perfil.",
            })

    # 6. Checagem de Conexão com Instagram e Túnel Cloudflare (Torre de Transmissão)
    tem_tunel = bool(settings.tunnel_token())
    status_tunel = tunel.status
    if not tem_tunel:
        gargalos.append({
            "id": "sem_tunel",
            "sala_id": "sala_distribuicao",
            "sala_nome": "Torre de Transmissão & Distribuição",
            "titulo": "Túnel Cloudflare Não Configurado",
            "motivo": "A Meta exige que as imagens e vídeos estejam em uma URL pública HTTPS na hora de publicar no Instagram. Sem o túnel, publicações automáticas falharão.",
            "gravidade": "alerta",
            "icone": "🌐",
            "acao_texto": "Configurar Túnel",
            "acao_url": "/conexoes",
            "solucao": "Configure o Cloudflare Tunnel apontando para a porta 8081.",
        })
    elif status_tunel in ("erro", "caiu"):
        gargalos.append({
            "id": "tunel_fora",
            "sala_id": "sala_distribuicao",
            "sala_nome": "Torre de Transmissão & Distribuição",
            "titulo": f"Túnel Cloudflare com Status: {status_tunel.upper()}",
            "motivo": "O processo do túnel caiu ou não conseguiu se conectar à rede da Cloudflare.",
            "gravidade": "critica",
            "icone": "⚠️",
            "acao_texto": "Ver Conexões",
            "acao_url": "/conexoes",
            "solucao": "Confira o token do túnel e os logs em 'Conexões e acesso'.",
        })

    # 7. Checagem de Posts Falhos Recentes
    query_falhas = "SELECT id, manchete, noticia_titulo, erro, atualizado_em FROM posts WHERE estado='falhou'"
    args_falhas = ()
    if perfil_id:
        query_falhas += " AND perfil_id=?"
        args_falhas = (perfil_id,)
    query_falhas += " ORDER BY id DESC LIMIT 3"
    falhas = db.q(query_falhas, args_falhas)
    
    if falhas:
        ultima_falha = falhas[0]
        erro_msg = (ultima_falha.get("erro") or "Erro desconhecido na esteira").strip()
        
        # Mapeia onde o erro aconteceu
        sala_erro = "sala_render"
        if "llm" in erro_msg.lower() or "modelo" in erro_msg.lower() or "timeout" in erro_msg.lower():
            sala_erro = "sala_redacao"
        elif "instagram" in erro_msg.lower() or "meta" in erro_msg.lower() or "token" in erro_msg.lower():
            sala_erro = "sala_distribuicao"
        elif "telegram" in erro_msg.lower():
            sala_erro = "sala_orquestrador"

        gargalos.append({
            "id": "post_falhou",
            "sala_id": sala_erro,
            "sala_nome": "Post Quebrou na Esteira",
            "titulo": f"Falha na Produção do Post #{ultima_falha['id']}",
            "motivo": f"Motivo registrado: {erro_msg[:220]}",
            "gravidade": "critica",
            "icone": "💥",
            "acao_texto": "Ver na Fila",
            "acao_url": "/",
            "solucao": "Você pode clicar em 'Refazer' no painel ou no Telegram para reprocessar o post.",
        })

    return gargalos


def obter_estado_escritorio(perfil_id: int | None = None) -> dict[str, Any]:
    """Retorna o estado completo e reativo de todo o escritório virtual de agentes."""
    perfis = obter_perfis()
    
    # Perfil atual selecionado
    perfil_atual = None
    if perfil_id:
        for p in perfis:
            if p["id"] == perfil_id:
                perfil_atual = p
                break
    if not perfil_atual and perfis:
        perfil_atual = perfis[0]
        perfil_id = perfil_atual["id"]
        
    pid = perfil_atual["id"] if perfil_atual else None
    
    # 1. Diagnóstico de Gargalos
    gargalos = diagnosticar_gargalos(pid)
    gargalos_por_sala = {g["sala_id"]: g for g in gargalos}
    
    # 2. Status dos Loops em Segundo Plano
    agora_tz = datetime.now(ZoneInfo(settings.tz()))
    hoje_str = agora_tz.strftime("%Y-%m-%d")
    
    # Agendador / Scheduler
    horarios_perfil = [h.strip() for h in (perfil_atual.get("horarios") or "").split(",") if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h.strip())] if perfil_atual else []
    slots_hoje = []
    for h in horarios_perfil:
        chave_slot = f"slot:{pid}:{hoje_str}:{h}"
        ja_rodou = bool(db.get_setting(chave_slot))
        slots_hoje.append({"horario": h, "executado": ja_rodou})
        
    loop_agendador = {
        "status": "rodando" if (perfil_atual and perfil_atual.get("ativo")) else "pausado",
        "tick_segundos": C.TICK_SECONDS,
        "fuso_horario": settings.tz(),
        "hora_local": agora_tz.strftime("%H:%M:%S"),
        "horarios_cadastrados": horarios_perfil,
        "slots_hoje": slots_hoje,
    }
    
    # Supervisor
    loop_supervisor = {
        "status": "rodando",
        "telegram_token": bool(settings.telegram_token()),
        "telegram_status": "conectado" if settings.telegram_token() else "desconectado",
        "tunel_token": bool(settings.tunnel_token()),
        "tunel_status": tunel.status,
        "tunel_url": db.get_setting("public_base_url") or "",
    }
    
    # Pipeline ativo (em execução agora)
    esta_produzindo = (pid in pipeline.RUNNING) if pid else False
    loop_pipeline = {
        "esta_produzindo": esta_produzindo,
        "perfis_em_execucao": list(pipeline.RUNNING),
        "total_em_execucao": len(pipeline.RUNNING),
    }
    
    # 3. Estatísticas de Produção
    base_sql_args = (pid,) if pid else ()
    where_perfil = "WHERE perfil_id=?" if pid else ""
    
    contagens_brutas = db.q(f"SELECT estado, COUNT(*) as qtd FROM posts {where_perfil} GROUP BY estado", base_sql_args)
    contagens = {r["estado"]: r["qtd"] for r in contagens_brutas}
    
    estatisticas = {
        "capturados": contagens.get("capturado", 0),
        "extraidos": contagens.get("extraido", 0),
        "gerando": 1 if esta_produzindo else contagens.get("publicando", 0),
        "aguardando_aprovacao": contagens.get("aguardando_aprovacao", 0),
        "agendados": contagens.get("agendado", 0),
        "publicados": contagens.get("publicado", 0),
        "falhas": contagens.get("falhou", 0),
        "rascunhos": contagens.get("rascunho", 0),
        "total": sum(contagens.values()),
    }
    
    # 4. Feeds do Radar
    feeds_ativos = db.q("SELECT * FROM feeds WHERE ativo=1 AND perfil_id=?", (pid,)) if pid else []
    if not feeds_ativos and pid:
        feeds_ativos = db.q("SELECT * FROM feeds WHERE ativo=1 AND perfil_id IS NULL")
    
    # 5. Salas & Agentes no Escritório Ilustrado
    # Determina o humor e balão de fala dinâmico de cada sala baseado no estado real
    
    # Sala 1: Diretoria & Orquestrador
    g1 = gargalos_por_sala.get("sala_orquestrador")
    status_s1 = "bloqueado" if (g1 and g1["gravidade"] == "critica") else ("alerta" if g1 else ("trabalhando" if esta_produzindo else "ativo"))
    balao_s1 = g1["motivo"] if g1 else ("⚡ Despachando tarefas para o time agora!" if esta_produzindo else "Recepção aberta. Comandos do Telegram operacionais.")
    
    # Sala 2: Radar de Notícias & Pauta
    g2 = gargalos_por_sala.get("sala_radar")
    status_s2 = "bloqueado" if (g2 and g2["gravidade"] == "critica") else ("alerta" if g2 else ("trabalhando" if esta_produzindo else "ativo"))
    balao_s2 = g2["motivo"] if g2 else (f"Rastreando {len(feeds_ativos)} feeds ativos em busca de matérias quentes." if feeds_ativos else "Nenhum feed ativo configurado.")
    
    # Sala 3: Mesa de Redação & Ganchos
    g3 = gargalos_por_sala.get("sala_redacao")
    status_s3 = "bloqueado" if (g3 and g3["gravidade"] == "critica") else ("alerta" if g3 else ("trabalhando" if esta_produzindo else "ativo"))
    balao_s3 = g3["motivo"] if g3 else ("Redigindo copy de alta retenção com hook nos 125 chars..." if esta_produzindo else "Máquina de escrever pronta: frases diretas e sem enrolação.")
    
    # Sala 4: Estúdio de Carrossel & Adaptação
    g4 = gargalos_por_sala.get("sala_carrossel")
    status_s4 = "alerta" if g4 else ("trabalhando" if (esta_produzindo and estatisticas["extraidos"] > 0) else "ativo")
    balao_s4 = "Arquitetando carrosséis slide a slide com safe zones 4:5 e 9:16."
    
    # Sala 5: Posto de Qualidade & Humanização
    g5 = gargalos_por_sala.get("sala_qualidade")
    status_s5 = "alerta" if g5 else ("trabalhando" if esta_produzindo else "ativo")
    balao_s5 = "Auditoria Anti-IA: caçando clichês robóticos e garantindo tom 100% natural."
    
    # Sala 6: Laboratório Gráfico & Render
    g6 = gargalos_por_sala.get("sala_render")
    status_s6 = "bloqueado" if (g6 and g6["gravidade"] == "critica") else ("alerta" if g6 else ("trabalhando" if esta_produzindo else "ativo"))
    balao_s6 = g6["motivo"] if g6 else ("Renderizando card JPEG 1080x1350 via Playwright headless..." if esta_produzindo else "Chromium headless pronto para desenhar cards e artes vetoriais.")
    
    # Sala 7: Pracinha de Pausa & Aprovação (Lounge)
    g7 = gargalos_por_sala.get("sala_cafe")
    tem_cafe_esperando = estatisticas["aguardando_aprovacao"] > 0
    status_s7 = "alerta" if tem_cafe_esperando else "descanso"
    balao_s7 = f"☕ Ei! Você tem {estatisticas['aguardando_aprovacao']} post(s) aguardando sua aprovação no Telegram!" if tem_cafe_esperando else "Pracinha tranquila. Nenhuma postagem represada na mesa de aprovação."
    
    # Sala 8: Torre de Distribuição & Redes
    g8 = gargalos_por_sala.get("sala_distribuicao")
    tem_tunel = bool(settings.tunnel_token())
    status_s8 = "bloqueado" if (g8 and g8["gravidade"] == "critica") else ("alerta" if g8 else ("trabalhando" if estatisticas["gerando"] > 0 else "ativo"))
    balao_s8 = g8["motivo"] if g8 else (f"Túnel {tunel.status}. Antenas alinhadas para Instagram, Threads e redes locais." if tem_tunel else "Túnel Cloudflare não configurado.")

    salas = [
        {
            "id": "sala_orquestrador",
            "pos": "1",
            "nome": "Diretoria & Orquestração",
            "agente": "Agente Orquestrador Central",
            "icone": "👔",
            "avatar_tipo": "diretor",
            "status": status_s1,
            "balao": balao_s1,
            "gargalo": g1,
            "cor_accent": "#ff7a1a",
            "metricas": [
                {"label": "Bot Telegram", "val": "Ativo" if settings.telegram_token() else "Off"},
                {"label": "Chat ID", "val": perfil_atual.get("telegram_chat_id") or "Vazio" if perfil_atual else "-"},
            ],
            "descricao": "Recebe os briefings do Telegram, analisa intenções e despacha ordens para os especialistas.",
        },
        {
            "id": "sala_radar",
            "pos": "2",
            "nome": "Radar de Notícias & Pauta",
            "agente": "Audience Insights & Content Planner",
            "icone": "🛰️",
            "avatar_tipo": "analista",
            "status": status_s2,
            "balao": balao_s2,
            "gargalo": g2,
            "cor_accent": "#00d2ff",
            "metricas": [
                {"label": "Feeds Ativos", "val": len(feeds_ativos)},
                {"label": "Janela Máx", "val": f"{perfil_atual.get('max_idade_horas', 36) if perfil_atual else 36}h"},
            ],
            "descricao": "Varre RSS e Google Trends, filtra temas por palavras-chave e descobre pautas virais.",
        },
        {
            "id": "sala_redacao",
            "pos": "3",
            "nome": "Mesa de Redação & Estratégia",
            "agente": "Estrategista Editorial, Caption Writer & Hook Extractor",
            "icone": "✍️",
            "avatar_tipo": "redator",
            "status": status_s3,
            "balao": balao_s3,
            "gargalo": g3,
            "cor_accent": "#9d4edd",
            "metricas": [
                {"label": "Ganchos (125c)", "val": "Ativo"},
                {"label": "Redigidos", "val": estatisticas["publicados"] + estatisticas["agendados"] + estatisticas["aguardando_aprovacao"]},
            ],
            "descricao": "Define o ângulo editorial da matéria, redige copy irresistível com hook nos 125 chars e CTA único.",
        },
        {
            "id": "sala_carrossel",
            "pos": "4",
            "nome": "Estúdio de Carrossel & Adaptação",
            "agente": "Carousel Planner & Repurposer",
            "icone": "📐",
            "avatar_tipo": "designer",
            "status": status_s4,
            "balao": balao_s4,
            "gargalo": g4,
            "cor_accent": "#e0aaff",
            "metricas": [
                {"label": "Framework", "val": "Hook→Dor→CTA"},
                {"label": "Safe Zones", "val": "4:5 & 9:16"},
            ],
            "descricao": "Roteiriza apresentações slide a slide (de 4 a 10 telas) com retenção e clareza visual.",
        },
        {
            "id": "sala_qualidade",
            "pos": "5",
            "nome": "Posto de Qualidade & Crítica Visual",
            "agente": "Crítico Visual Multimodal & Humanizer (Anti-IA)",
            "icone": "🛡️",
            "avatar_tipo": "auditor",
            "status": status_s5,
            "balao": balao_s5,
            "gargalo": g5,
            "cor_accent": "#3fb950",
            "metricas": [
                {"label": "Anti-Clichê", "val": "Ativo"},
                {"label": "Crítico Visual", "val": "Nota ≥ 8/10"},
            ],
            "descricao": "Inspeciona o card renderizado (contraste, legibilidade e overflow) e elimina clichês robóticos de IA.",
        },
        {
            "id": "sala_render",
            "pos": "6",
            "nome": "Direção de Arte & Laboratório Render",
            "agente": "Diretor de Arte, VectorCraft, Playwright & FFmpeg",
            "icone": "🎨",
            "avatar_tipo": "render",
            "status": status_s6,
            "balao": balao_s6,
            "gargalo": g6,
            "cor_accent": "#ffb703",
            "metricas": [
                {"label": "Layouts", "val": "6 Templates"},
                {"label": "Playwright", "val": "Headless OK"},
            ],
            "descricao": "Escolhe dentre 6 layouts dinâmicos, define paleta cromática, compõe selos SVG VectorCraft e renderiza em alta definição.",
        },
        {
            "id": "sala_cafe",
            "pos": "7",
            "nome": "Pracinha de Pausa & Aprovação",
            "agente": "Lounge de Espera Humana (Você)",
            "icone": "☕",
            "avatar_tipo": "cafe",
            "status": status_s7,
            "balao": balao_s7,
            "gargalo": g7,
            "cor_accent": "#f72585",
            "metricas": [
                {"label": "Aguardando Você", "val": estatisticas["aguardando_aprovacao"]},
                {"label": "Agendados", "val": estatisticas["agendados"]},
            ],
            "descricao": "Onde os posts prontos descansam tomando um cafezinho até você clicar em 'Postar' no Telegram.",
        },
        {
            "id": "sala_distribuicao",
            "pos": "8",
            "nome": "Torre de Transmissão & Distribuição",
            "agente": "Central de Distribuição Multiplataforma",
            "icone": "📡",
            "avatar_tipo": "antena",
            "status": status_s8,
            "balao": balao_s8,
            "gargalo": g8,
            "cor_accent": "#4361ee",
            "metricas": [
                {"label": "Instagram", "val": "Pronto"},
                {"label": "Túnel", "val": tunel.status.upper()},
            ],
            "descricao": "Dispara publicações para a Instagram Graph API oficial e canais soberanos (Threads, YouTube, etc).",
        },
    ]
    
    # 6. Posts recentes com indicação de em qual sala cada um está
    sql_posts = f"SELECT id, perfil_id, estado, manchete, noticia_titulo, formato, arquivo, criado_em, atualizado_em, erro FROM posts {where_perfil} ORDER BY id DESC LIMIT 6"
    posts_brutos = db.q(sql_posts, base_sql_args)
    
    posts_recentes = []
    for po in posts_brutos:
        # Determina a localização do post no escritório
        sala_local = "sala_orquestrador"
        est = po.get("estado", "")
        if est in ("capturado", "extraido"):
            sala_local = "sala_radar" if est == "capturado" else "sala_redacao"
        elif est == "publicando":
            sala_local = "sala_render"
        elif est == "aguardando_aprovacao":
            sala_local = "sala_cafe"
        elif est in ("agendado", "publicado"):
            sala_local = "sala_distribuicao"
        elif est == "falhou":
            sala_local = "sala_render"
            
        posts_recentes.append({
            "id": po["id"],
            "estado": po["estado"],
            "manchete": po["manchete"] or po["noticia_titulo"] or f"Post #{po['id']}",
            "formato": po.get("formato", "feed"),
            "arquivo": po.get("arquivo", ""),
            "sala_local": sala_local,
            "erro": po.get("erro", ""),
            "quando": po.get("atualizado_em") or po.get("criado_em") or "",
        })
        
    # 7. Feed de eventos recentes (Logs ao vivo)
    sql_logs = f"SELECT e.*, p.nome as perfil_nome FROM eventos e LEFT JOIN perfis p ON e.perfil_id=p.id {where_perfil} ORDER BY e.id DESC LIMIT 10"
    logs = db.q(sql_logs, base_sql_args)

    return {
        "perfil_atual": perfil_atual,
        "perfis": perfis,
        "gargalos": gargalos,
        "tem_gargalos": len(gargalos) > 0,
        "estatisticas": estatisticas,
        "loops": {
            "agendador": loop_agendador,
            "supervisor": loop_supervisor,
            "pipeline": loop_pipeline,
        },
        "salas": salas,
        "posts_recentes": posts_recentes,
        "logs": logs,
        "timestamp": int(time.time()),
    }
