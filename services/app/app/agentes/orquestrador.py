"""Agente Orquestrador Central: Roteador de intenções e coordenador do time de agentes.

Responsável por receber comandos e mensagens naturais do usuário (via Telegram ou Web),
identificar a intenção e delegar a execução para o especialista correto.
"""
import logging
import re
import time
from typing import Any

from .. import db
from .base import BaseAgente
from .caption_writer import CaptionWriterAgente
from .carousel_planner import CarouselPlannerAgente
from .hashtag_strategist import HashtagStrategistAgente
from .hook_extractor import HookExtractorAgente
from .humanizer import HumanizerAgente
from .vector_art import VectorArtAgente
from .content_planner import ContentPlannerAgente
from .audience_insights import AudienceInsightsAgente
from .repurposer import RepurposerAgente
from .profile_optimizer import ProfileOptimizerAgente
from .estudio import EstudioCriativo

logger = logging.getLogger(__name__)

SCHEMA_ORQUESTRADOR = {
    "type": "object",
    "properties": {
        "intencao": {
            "type": "string",
            "enum": [
                "conversar",
                "gerar_post",
                "reels",
                "story",
                "carrossel",
                "feed",
                "legenda",
                "extrair_hook",
                "hashtags",
                "auditar",
                "humanizar",
                "plano_semanal",
                "pesquisa",
                "repurposar",
                "propor_perfil",
                "definir_marca",
                "arte_vetorial",
            ],
        },
        "resposta_direta": {"type": "string"},
        "parametros": {
            "type": "object",
            "properties": {
                "ideia": {"type": "string"},
                "formato": {"type": "string", "enum": ["feed", "story", "carrossel", "reel", "citacao", "meme", "badge", "reels", "quadrado"]},
                "objetivo": {"type": "string", "enum": ["saves", "shares", "comments", "follows"]},
                "n_slides": {"type": "integer"},
                "texto_alvo": {"type": "string"},
                "link_alvo": {"type": "string"},
                "tipo_arte": {"type": "string", "enum": ["badge", "overlay_video", "slide_carrossel", "composicao"]},
                "estilo_arte": {"type": "string"},
                "subtexto": {"type": "string"},
            },
        },
    },
    "required": ["intencao", "resposta_direta"],
}

INSTR_ORQUESTRADOR = """
Você é o Orquestrador Central do ic-ap, coordenador de um time de especialistas em conteúdo para Instagram em 2026.
Você conversa com o autor pelo Telegram e identifica qual é o objetivo e formato a cada mensagem.

Mapeamento de Intenções:
- `reels`: Quando o autor pedir vídeo, Reel, Reels, vídeo curto ou roteiro com gancho inicial para gravação vertical 9:16.
  - parametros: ideia, objetivo (shares, saves, follows).
- `story`: Quando o autor pedir story, stories, aviso rápido, enquete, publicação temporária vertical 9:16 ou "gere um story com base no feed / post". ATENÇÃO: se o autor pedir "gere um story com base no feed", a intenção OBRIGATÓRIA é `story` e o formato é `story`, NUNCA `feed`.
  - parametros: ideia, objetivo.
- `carrossel`: Quando o autor pedir carrossel, sequência de slides ou passo a passo (ex.: "crie um carrossel de 6 slides sobre...", "monte um carrossel de...").
  - parametros: ideia, n_slides (de 4 a 10).
- `feed`: Quando o autor pedir post de feed, card de citação, insight ou opinião única (enquadramento 4:5 ou quadrado). NUNCA escolha feed quando o usuário tiver pedido explicitamente um story ou reel.
  - parametros: ideia, objetivo.
- `gerar_post`: Pedido genérico de criação de conteúdo (especifique o formato em parametros: reels, story, carrossel ou feed).
- `plano_semanal` / `pesquisa`: Quando pedir pauta da semana, ideias de conteúdo, calendário ou pesquisa de temas em alta.
- `extrair_hook`: Quando mandar um gancho, roteiro ou transcrição de vídeo viral para dissecar a fórmula psicológica.
  - parametros: texto_alvo.
- `hashtags`: Quando pedir hashtags ou palavras-chave de SEO 2026 para um tema ou texto.
  - parametros: texto_alvo ou ideia.
- `auditar` / `humanizar`: Quando mandar um texto e pedir para checar score de IA ou pedir para humanizar/limpar clichês.
  - parametros: texto_alvo.
- `repurposar`: Quando mandar link (LinkedIn, blog, X/Twitter) ou texto de outra rede para transformar em post de Instagram.
  - parametros: link_alvo ou texto_alvo.
- `arte_vetorial`: Quando pedir selos, badges, adesivos, overlays para vídeo/Reels ou gráficos vetoriais VectorCraft.
  - parametros: ideia, tipo_arte ("badge", "overlay_video", "slide_carrossel", "composicao"), estilo_arte ("neon_ciano", "neon_ouro", "alerta_vermelho", "pill_clean"), subtexto.
- `conversar`: Dúvidas, esclarecimentos gerais, brainstorming livre.

Em `resposta_direta`: Dê uma resposta amigável, concisa e direta em Português do Brasil, explicando em uma linha o que o time de especialistas está preparando.
Responda SOMENTE com JSON contendo: intencao, resposta_direta, parametros.
""".strip()


class OrquestradorAgente(BaseAgente):
    """Coordena a identificação de intenções e acionamento dos especialistas."""

    nome = "orquestrador"
    descricao = "Orquestra intenções, conversação e delegação para o time de especialistas."
    schema = SCHEMA_ORQUESTRADOR

    def __init__(self):
        self.caption_writer = CaptionWriterAgente()
        self.humanizer = HumanizerAgente()
        self.carousel_planner = CarouselPlannerAgente()
        self.hook_extractor = HookExtractorAgente()
        self.hashtag_strategist = HashtagStrategistAgente()
        self.vector_art = VectorArtAgente()
        self.content_planner = ContentPlannerAgente()
        self.audience_insights = AudienceInsightsAgente()
        self.repurposer = RepurposerAgente()
        self.profile_optimizer = ProfileOptimizerAgente()
        self.estudio = EstudioCriativo()

    async def _buscar_melhor_noticia_perfil(
        self,
        perfil: dict[str, Any],
        on_status: Any = None,
    ) -> str:
        """Direciona a pesquisa diretamente para o Meta AI dentro do Instagram com a técnica Blow Up (sem feeds RSS)."""
        handle = (perfil.get("handle") or "emery.carvalho").lstrip("@")
        if on_status:
            try:
                await on_status(f"💥 *Meta AI + Blow Up:* pesquisando tendências no Instagram para `@{handle}`...")
            except Exception:
                pass
        return (
            f"Pesquise dentro da plataforma do Instagram e nas tendências atuais para @{handle} "
            f"o tema mais relevante e viral hoje no nicho do perfil e aplique a técnica Blow Up."
        )

    async def processar_mensagem(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        chat_id: str,
        mensagem: str,
        historico: list[dict[str, Any]] | None = None,
        on_status: Any = None,
    ) -> dict[str, Any]:
        """Processa a mensagem do Telegram e roteia para o especialista correspondente."""
        texto_limpo = mensagem.strip()

        # 1. Comandos Diretos rápidos do Telegram
        if texto_limpo.startswith("/reels") or texto_limpo.startswith("/reel"):
            conteudo = texto_limpo.replace("/reels", "").replace("/reel", "").strip()
            if not conteudo:
                return {
                    "resposta_telegram": "Envie a ideia do Reels. Exemplo: `/reels 3 ferramentas de IA que economizam 10h na empresa`",
                    "acao": "ajuda_reels",
                }
            cap_res = await self.caption_writer.redigir(con, perfil, conteudo, objetivo="shares", formato="reels")
            legenda_final = cap_res["legenda_completa"]
            overlay_res = self.vector_art.gerar_overlay_reels(titulo=cap_res["hook_125"][:55], subtitulo="ROTEIRO & CENAS")
            nome_f = f"reels_overlay_{int(time.time() * 1000)}"
            svg_p, png_p = await self.vector_art.salvar_e_renderizar(overlay_res["svg"], nome_f, largura=1080, altura=1920)
            texto_pronto = (
                f"🎬 *Reels Estruturado (9:16 com Safe Zones)*\n\n"
                f"🎯 *Hook (0-3s):*\n_{cap_res['hook_125']}_\n\n"
                f"🎥 *Roteiro de Cenas:*\n"
            )
            for c in cap_res.get("cenas_reels", []):
                texto_pronto += f"- Cena {c['cena']}: {c['fala']} (Visual: _{c['busca_visual']}_)\n"
            texto_pronto += f"\n📝 *Legenda:*\n{legenda_final}"
            return {
                "resposta_telegram": texto_pronto,
                "acao": "reels",
                "dados": {
                    "caption": cap_res,
                    "legenda_final": legenda_final,
                    "arquivo_png": str(png_p),
                    "arquivo_svg": str(svg_p),
                    "ideia": conteudo,
                },
            }

        t_lower = texto_limpo.lower()

        # Detecção avançada de pedidos de Story (comando ou linguagem natural)
        eh_pedido_story = bool(
            texto_limpo.startswith(("/story", "/stories")) or
            (re.search(r'\b(story|stories)\b', t_lower) and
             not re.search(r'\b(feed|post|reels?|carrossel)\s+(sobre|com base em|de)\s+stor(y|ies)\b', t_lower))
        )

        if eh_pedido_story:
            base_feed = any(k in t_lower for k in ("com base no feed", "com base no post", "do feed", "do post", "ultimo feed", "último feed", "ultimo post", "último post", "baseado no feed", "baseado no post"))
            pede_noticia = any(k in t_lower for k in ("notícia", "notícias", "noticia", "noticias", "últimas", "ultimas", "matéria", "materia", "pauta", "rss"))
            conteudo = ""
            if base_feed:
                try:
                    p_ant = db.one(
                        "SELECT id, manchete, reacao, legenda, noticia_titulo FROM posts WHERE perfil_id=? ORDER BY id DESC LIMIT 1",
                        (perfil.get("id"),)
                    )
                    if p_ant:
                        conteudo = f"Baseado no post #{p_ant['id']}: {p_ant.get('manchete') or p_ant.get('noticia_titulo')}\n{p_ant.get('reacao') or p_ant.get('legenda')}"
                except Exception:
                    pass
            elif pede_noticia:
                not_ctx = await self._buscar_melhor_noticia_perfil(perfil, on_status=on_status)
                if not_ctx:
                    conteudo = f"{texto_limpo}\n\n{not_ctx}"

            if not conteudo:
                conteudo = re.sub(r'^(gere|crie|faça|faz|fazer|monte|quero)\s+(um\s+|uma\s+)?stor(y|ies)\s*(sobre|com base no feed|com base no post|de)?', '', texto_limpo, flags=re.I).strip()
                conteudo = conteudo.replace("/stories", "").replace("/story", "").strip() or texto_limpo

            res_estudio = await self.estudio.criar_post(
                con=con,
                perfil=perfil,
                pedido=conteudo,
                formato_forcado="story",
                on_status=on_status,
            )
            score = res_estudio["avaliacao_critico"].get("score", 8)
            texto_pronto = (
                f"📱 *Story Estruturado (9:16) pelo Estúdio Agêntico*\n\n"
                f"🎯 *Manchete:* {res_estudio['manchete']}\n"
                f"🎨 *Layout:* `{res_estudio['layout'].upper()}` (Nota: {score}/10)\n\n"
                f"📝 *Copy do Story:*\n{res_estudio['legenda']}"
            )
            return {
                "resposta_telegram": texto_pronto,
                "acao": "story",
                "dados": res_estudio,
            }

        if texto_limpo.startswith("/feed") or texto_limpo.startswith("/post"):
            conteudo = texto_limpo.replace("/feed", "").replace("/post", "").strip()
            if not conteudo:
                return {
                    "resposta_telegram": "Envie a ideia do post de feed. Exemplo: `/feed A melhor tecnologia é a que serve ao orçamento`",
                    "acao": "ajuda_feed",
                }
            res_estudio = await self.estudio.criar_post(
                con=con,
                perfil=perfil,
                pedido=conteudo,
                formato_forcado="feed",
                on_status=on_status,
            )
            score = res_estudio["avaliacao_critico"].get("score", 8)
            texto_pronto = (
                f"📌 *Post de Feed (4:5) pelo Estúdio Agêntico*\n\n"
                f"🎯 *Manchete:* {res_estudio['manchete']}\n"
                f"🎨 *Layout:* `{res_estudio['layout'].upper()}` (Nota: {score}/10)\n\n"
                f"📝 *Legenda:*\n{res_estudio['legenda']}"
            )
            return {
                "resposta_telegram": texto_pronto,
                "acao": "feed",
                "dados": res_estudio,
            }

        if texto_limpo.startswith("/planejar") or texto_limpo.startswith("/semana"):
            plano = await self.content_planner.planejar_semana(con, perfil)
            texto_pronto = f"📅 *Planejamento Semanal Estratégico*\n*Foco:* _{plano.get('foco', 'Crescimento e Autoridade')}_\n\n"
            for d in plano.get("dias", []):
                texto_pronto += f"• *Dia {d.get('dia')} ({d.get('formato', 'feed').upper()})*: {d.get('tema')}\n  🎯 _{d.get('gancho_sugerido')}_\n"
            if plano.get("recomendacao_geral"):
                texto_pronto += f"\n💡 *Dica:* {plano['recomendacao_geral']}"
            return {"resposta_telegram": texto_pronto, "acao": "plano_semanal", "dados": plano}

        if texto_limpo.startswith("/audiencia"):
            foco = texto_limpo.replace("/audiencia", "").strip()
            aud_res = await self.audience_insights.mapear_audiencia(con, perfil, sub_nicho=foco)
            texto_pronto = (
                f"🔍 *Raio-X de Audiência & Tendências*\n\n"
                f"👤 *Seguidor Ideal:* {aud_res.get('perfil_do_seguidor_ideal', '')}\n\n"
                f"⚡ *Dores Principais:*\n" + "\n".join(f"• {d['dor']}" for d in aud_res.get("dores_principais", [])[:3]) + "\n\n"
                "🎯 *Ângulos com Potencial Viral:*\n" + "\n".join(f"• {a['gancho_sugerido']}" for a in aud_res.get("angulos_de_conteudo_virais", [])[:3])
            )
            return {"resposta_telegram": texto_pronto, "acao": "audiencia", "dados": aud_res}

        if texto_limpo.startswith("/auditar"):
            conteudo = texto_limpo.replace("/auditar", "").strip()
            if not conteudo and historico:
                conteudo = historico[-1].get("content", "")
            if not conteudo:
                return {
                    "resposta_telegram": "Envie ou cole o texto que deseja auditar. Exemplo: `/auditar Seu texto aqui`",
                    "acao": "ajuda_auditar",
                }
            laudo = self.humanizer.auditar(conteudo)
            aviso = f"🔍 *Auditoria Anti-IA*\n- Score de IA: {laudo['score_ia']}% (Nível: {laudo['nivel']})\n"
            aviso += f"- Total de palavras: {laudo['total_palavras']} | Emojis: {laudo['total_emojis']} | Travessões: {laudo['total_travessoes']}\n\n"
            aviso += "*Diagnóstico:*\n" + "\n".join(f"• {d}" for d in laudo["diagnostico"])
            return {"resposta_telegram": aviso, "acao": "auditar", "dados": laudo}

        if texto_limpo.startswith("/humanizar"):
            conteudo = texto_limpo.replace("/humanizar", "").strip()
            if not conteudo:
                return {
                    "resposta_telegram": "Envie ou cole o texto para desintoxicação. Exemplo: `/humanizar Seu texto aqui`",
                    "acao": "ajuda_humanizar",
                }
            res = await self.humanizer.humanizar(con, perfil, conteudo)
            texto_pronto = (
                f"✨ *Texto Humanizado:*\n\n{res['texto_humanizado']}\n\n"
                f"📊 Score de IA reduzido de {res['auditoria_antes']['score_ia']}% para {res['auditoria_depois']['score_ia']}%."
            )
            return {"resposta_telegram": texto_pronto, "acao": "humanizar", "dados": res}

        if texto_limpo.startswith("/hook"):
            conteudo = texto_limpo.replace("/hook", "").strip()
            if not conteudo:
                return {
                    "resposta_telegram": "Envie o gancho viral que você quer dissecar. Exemplo: `/hook Pare de fazer X se você quer Y`",
                    "acao": "ajuda_hook",
                }
            res = await self.hook_extractor.extrair(con, perfil, conteudo)
            texto_pronto = (
                f"🎣 *Fórmula Identificada:* {res['formula_identificada']}\n\n"
                f"🧠 *Por que funciona:* {res['por_que_funciona']}\n\n"
                f"📋 *Template em Branco:*\n`{res['template_em_branco']}`\n\n"
                f"💡 *Variações para você:*\n" + "\n".join(f"• {v}" for v in res["variacoes_para_o_autor"])
            )
            return {"resposta_telegram": texto_pronto, "acao": "extrair_hook", "dados": res}

        if texto_limpo.startswith("/hashtags"):
            conteudo = texto_limpo.replace("/hashtags", "").strip()
            if not conteudo:
                return {
                    "resposta_telegram": "Informe o tema ou texto para gerar as hashtags. Exemplo: `/hashtags inteligência artificial local`",
                    "acao": "ajuda_hashtags",
                }
            res = await self.hashtag_strategist.gerar_estrategia(con, perfil, conteudo)
            texto_pronto = (
                f"🏷️ *Hashtags Estratégicas (2026 SEO):*\n\n"
                f"{' '.join(res['conjunto_final'])}\n\n"
                f"📌 *Detalhamento:*\n"
                f"• Nicho: {' '.join(res['nicho'])}\n"
                f"• Médio: {' '.join(res['medio'])}\n"
                f"• Amplo: {' '.join(res['amplo'])}\n\n"
                f"🎯 *SEO:* _{res['justificativa_seo']}_"
            )
            return {"resposta_telegram": texto_pronto, "acao": "hashtags", "dados": res}

        if texto_limpo.startswith("/carrossel"):
            conteudo = texto_limpo.replace("/carrossel", "").strip()
            if not conteudo:
                return {
                    "resposta_telegram": "Envie a ideia do carrossel. Exemplo: `/carrossel 5 erros ao implementar IA na empresa`",
                    "acao": "ajuda_carrossel",
                }
            res = await self.carousel_planner.planejar(con, perfil, conteudo, n_slides=6)
            texto_pronto = f"📑 *Carrossel Planejado:* {res['titulo_carrossel']} ({res['total_slides']} slides)\n\n"
            for sl in res["slides"]:
                icone = "🎯" if sl["tipo"] == "capa" else ("🚀" if sl["tipo"] == "cta" else "📄")
                sub = f"\n   _{sl['texto']}_" if sl.get("texto") else ""
                texto_pronto += f"{icone} *Slide {sl['slide_n']} ({sl['tipo'].upper()}):* {sl['titulo']}{sub}\n"
            texto_pronto += f"\n📝 *Legenda:*\n{res['legenda_instagram']}\n\n🏷️ {' '.join(res['hashtags'])}"
            return {"resposta_telegram": texto_pronto, "acao": "carrossel", "dados": res}

        if texto_limpo.startswith("/badge"):
            conteudo = texto_limpo.replace("/badge", "").strip()
            if not conteudo:
                return {
                    "resposta_telegram": "Envie o texto do badge. Exemplo: `/badge NOVO neon_ciano | Exclusivo`",
                    "acao": "ajuda_badge",
                }
            partes = [p.strip() for p in conteudo.split("|")]
            texto_p = partes[0]
            subtexto_p = partes[1] if len(partes) > 1 else ""
            tokens = texto_p.split()
            estilo = "neon_ciano"
            if len(tokens) > 1 and tokens[-1] in ("neon_ciano", "neon_ouro", "alerta_vermelho", "pill_clean"):
                estilo = tokens[-1]
                texto_badge = " ".join(tokens[:-1])
            else:
                texto_badge = texto_p

            res = self.vector_art.gerar_badge(texto=texto_badge, estilo=estilo, subtexto=subtexto_p)
            nome_f = f"badge_{estilo}_{int(time.time() * 1000)}"
            svg_p, png_p = await self.vector_art.salvar_e_renderizar(res["svg"], nome_f, largura=res["largura"], altura=res["altura"])
            res["arquivo_svg"] = str(svg_p)
            res["arquivo_png"] = str(png_p)
            return {
                "resposta_telegram": f"🎨 *Badge Vetorial Gerado (VectorCraft)*\n- Estilo: `{estilo}`\n- Dimensões: {res['largura']}x{res['altura']}px\n- Arquivo: `{png_p.name}`",
                "acao": "badge",
                "dados": res,
            }

        if texto_limpo.startswith("/overlay"):
            conteudo = texto_limpo.replace("/overlay", "").strip()
            if not conteudo:
                return {
                    "resposta_telegram": "Envie o título do overlay para Reels. Exemplo: `/overlay 3 FERRAMENTAS DE IA | Economize 10h/semana`",
                    "acao": "ajuda_overlay",
                }
            partes = [p.strip() for p in conteudo.split("|")]
            titulo = partes[0]
            subtitulo = partes[1] if len(partes) > 1 else ""
            res = self.vector_art.gerar_overlay_reels(titulo=titulo, subtitulo=subtitulo, badge_texto="DESTAQUE")
            nome_f = f"overlay_{int(time.time() * 1000)}"
            svg_p, png_p = await self.vector_art.salvar_e_renderizar(res["svg"], nome_f, largura=1080, altura=1920)
            res["arquivo_svg"] = str(svg_p)
            res["arquivo_png"] = str(png_p)
            return {
                "resposta_telegram": f"🎬 *Overlay Reels 9:16 Gerado (VectorCraft)*\n- Safe Zones ativas (Instagram / TikTok)\n- Título: *{titulo}*\n- Arquivo: `{png_p.name}`",
                "acao": "overlay",
                "dados": res,
            }

        if texto_limpo.startswith("/arte") or texto_limpo.startswith("/vetor"):
            conteudo = texto_limpo.replace("/arte", "").replace("/vetor", "").strip()
            if not conteudo:
                return {
                    "resposta_telegram": "Descreva a arte que deseja criar. Exemplo: `/arte card escuro neon sobre inteligência artificial local`",
                    "acao": "ajuda_arte",
                }
            res = await self.vector_art.criar_composicao(con, perfil, conteudo, formato="feed")
            nome_f = f"arte_{int(time.time() * 1000)}"
            svg_p, png_p = await self.vector_art.salvar_e_renderizar(res["svg"], nome_f, largura=res.get("largura", 1080), altura=res.get("altura", 1350))
            res["arquivo_svg"] = str(svg_p)
            res["arquivo_png"] = str(png_p)
            return {
                "resposta_telegram": f"🎨 *Arte Vetorial Criada (VectorCraft)*\n- Projeto: *{res.get('titulo_projeto')}*\n- Elementos: {len(res.get('elementos', []))}\n- Arquivo: `{png_p.name}`",
                "acao": "arte_vetorial",
                "dados": res,
            }

        # 2. Via Direta Meta AI + Blow Up: se o cookie do Meta AI estiver ativo, transforma qualquer mensagem
        # em post/story tangível imediatamente sem depender de chamadas intermediárias de roteamento LLM.
        from .. import settings
        if settings.segredo("meta_ai_cookies"):
            fmt_auto = "story" if eh_pedido_story else "feed"
            res_estudio = await self.estudio.criar_post(
                con=con,
                perfil=perfil,
                pedido=texto_limpo,
                formato_forcado=fmt_auto,
                on_status=on_status,
            )
            score = res_estudio["avaliacao_critico"].get("score", 10)
            texto_saida = (
                f"💥 *Conteúdo Gerado via Meta AI + Técnica Blow Up*\n\n"
                f"🎯 *Manchete:* {res_estudio['manchete']}\n"
                f"🎨 *Layout:* `{res_estudio['layout'].upper()}` (Nota: {score}/10)\n\n"
                f"📝 *Legenda:*\n{res_estudio['legenda']}"
            )
            return {
                "resposta_telegram": texto_saida,
                "acao": res_estudio["formato"],
                "dados": res_estudio,
            }

        # 3. Roteamento Semântico via LLM (fallback quando Meta AI não está configurado)
        roteamento = await self.executar(
            con=con,
            perfil=perfil,
            mensagem_user=f"Mensagem recebida do autor no Telegram:\n{texto_limpo}",
            instrucoes_agente=INSTR_ORQUESTRADOR,
            historico=historico,
            temperature=0.4,
        )

        intencao = roteamento.get("intencao", "conversar")
        resposta_direta = roteamento.get("resposta_direta", "Entendido, processando...")
        params = roteamento.get("parametros") or {}

        # 3. Execução de Especialistas
        if intencao == "carrossel" and params.get("ideia"):
            car_res = await self.carousel_planner.planejar(
                con=con,
                perfil=perfil,
                ideia=params["ideia"],
                n_slides=params.get("n_slides", 6),
            )
            texto_saida = f"{resposta_direta}\n\n📑 *Carrossel: {car_res['titulo_carrossel']}* ({car_res['total_slides']} slides)\n\n"
            for sl in car_res["slides"]:
                sub = f" - _{sl['texto']}_" if sl.get("texto") else ""
                texto_saida += f"• Slide {sl['slide_n']}: *{sl['titulo']}*{sub}\n"
            texto_saida += f"\n📝 *Legenda Sugerida:*\n{car_res['legenda_instagram']}\n\n{' '.join(car_res['hashtags'])}"
            return {"resposta_telegram": texto_saida, "acao": "carrossel", "dados": car_res}

        if intencao == "extrair_hook" and params.get("texto_alvo"):
            hook_res = await self.hook_extractor.extrair(con, perfil, params["texto_alvo"])
            texto_saida = (
                f"{resposta_direta}\n\n"
                f"🎣 *Fórmula:* {hook_res['formula_identificada']}\n\n"
                f"🧠 *Por que funciona:* {hook_res['por_que_funciona']}\n\n"
                f"📋 *Template:*\n`{hook_res['template_em_branco']}`\n\n"
                f"💡 *Para você:*\n" + "\n".join(f"• {v}" for v in hook_res["variacoes_para_o_autor"])
            )
            return {"resposta_telegram": texto_saida, "acao": "extrair_hook", "dados": hook_res}

        if intencao == "hashtags" and (params.get("texto_alvo") or params.get("ideia")):
            alvo = params.get("texto_alvo") or params.get("ideia") or ""
            hash_res = await self.hashtag_strategist.gerar_estrategia(con, perfil, alvo)
            texto_saida = (
                f"{resposta_direta}\n\n"
                f"🏷️ *Hashtags Selecionadas:* {' '.join(hash_res['conjunto_final'])}\n\n"
                f"🎯 *Justificativa:* _{hash_res['justificativa_seo']}_"
            )
            return {"resposta_telegram": texto_saida, "acao": "hashtags", "dados": hash_res}

        if intencao in ("reels", "reel") or (intencao in ("gerar_post", "legenda") and params.get("formato") in ("reels", "reel")):
            ideia = params.get("ideia") or texto_limpo
            obj = params.get("objetivo") or "shares"
            cap_res = await self.caption_writer.redigir(con, perfil, ideia, objetivo=obj, formato="reels")
            legenda_final = cap_res["legenda_completa"]
            overlay_res = self.vector_art.gerar_overlay_reels(titulo=cap_res["hook_125"][:55], subtitulo="ROTEIRO & CENAS")
            nome_f = f"reels_overlay_{int(time.time() * 1000)}"
            svg_p, png_p = await self.vector_art.salvar_e_renderizar(overlay_res["svg"], nome_f, largura=1080, altura=1920)
            texto_saida = (
                f"{resposta_direta}\n\n"
                f"🎬 *Reels Estruturado (9:16 com Safe Zones)*\n\n"
                f"🎯 *Hook (0-3s):*\n_{cap_res['hook_125']}_\n\n"
                f"🎥 *Roteiro de Cenas:*\n"
            )
            for c in cap_res.get("cenas_reels", []):
                texto_saida += f"- Cena {c['cena']}: {c['fala']} (Visual: _{c['busca_visual']}_)\n"
            texto_saida += f"\n📝 *Legenda:*\n{legenda_final}"
            return {
                "resposta_telegram": texto_saida,
                "acao": "reels",
                "dados": {
                    "caption": cap_res,
                    "legenda_final": legenda_final,
                    "arquivo_png": str(png_p),
                    "arquivo_svg": str(svg_p),
                    "ideia": ideia,
                },
            }

        if intencao in ("story", "stories", "feed", "gerar_post", "legenda") and (params.get("ideia") or texto_limpo):
            ideia = params.get("ideia") or texto_limpo
            if any(k in t_lower for k in ("notícia", "notícias", "noticia", "noticias", "últimas", "ultimas", "matéria", "materia", "pauta", "rss")):
                not_ctx = await self._buscar_melhor_noticia_perfil(perfil, on_status=on_status)
                if not_ctx:
                    ideia = f"{ideia}\n\n{not_ctx}"
            fmt_pedido = params.get("formato")
            if intencao in ("story", "stories") or eh_pedido_story:
                fmt_final = "story"
            elif fmt_pedido in ("story", "feed"):
                fmt_final = fmt_pedido
            else:
                fmt_final = "feed"

            res_estudio = await self.estudio.criar_post(
                con=con,
                perfil=perfil,
                pedido=ideia,
                formato_forcado=fmt_final,
                on_status=on_status,
            )
            score = res_estudio["avaliacao_critico"].get("score", 8)
            texto_saida = (
                f"{resposta_direta}\n\n"
                f"🎯 *Manchete:* {res_estudio['manchete']}\n"
                f"🎨 *Layout:* `{res_estudio['layout'].upper()}` (Nota: {score}/10)\n\n"
                f"📝 *Legenda:*\n{res_estudio['legenda']}"
            )
            return {
                "resposta_telegram": texto_saida,
                "acao": res_estudio["formato"],
                "dados": res_estudio,
            }

        if intencao in ("plano_semanal", "pesquisa"):
            plano = await self.content_planner.planejar_semana(con, perfil)
            texto_saida = f"{resposta_direta}\n\n📅 *Planejamento Semanal Estratégico*\n*Foco:* _{plano.get('foco', 'Crescimento e Autoridade')}_\n\n"
            for d in plano.get("dias", []):
                texto_saida += f"• *Dia {d.get('dia')} ({d.get('formato', 'feed').upper()})*: {d.get('tema')}\n  🎯 _{d.get('gancho_sugerido')}_\n"
            if plano.get("recomendacao_geral"):
                texto_saida += f"\n💡 *Recomendação:* {plano['recomendacao_geral']}"
            return {"resposta_telegram": texto_saida, "acao": "plano_semanal", "dados": plano}

        if intencao == "humanizar" and params.get("texto_alvo"):
            hum_res = await self.humanizer.humanizar(con, perfil, params["texto_alvo"])
            texto_saida = (
                f"{resposta_direta}\n\n"
                f"✨ *Texto Humanizado:*\n\n{hum_res['texto_humanizado']}\n\n"
                f"📊 Score de IA anterior: {hum_res['auditoria_antes']['score_ia']}% → Atual: {hum_res['auditoria_depois']['score_ia']}%"
            )
            return {"resposta_telegram": texto_saida, "acao": "humanizar", "dados": hum_res}

        if intencao == "auditar" and params.get("texto_alvo"):
            laudo = self.humanizer.auditar(params["texto_alvo"])
            aviso = f"🔍 *Auditoria Anti-IA*\n- Score de IA: {laudo['score_ia']}% ({laudo['nivel']})\n"
            aviso += "*Diagnóstico:*\n" + "\n".join(f"• {d}" for d in laudo["diagnostico"])
            return {"resposta_telegram": f"{resposta_direta}\n\n{aviso}", "acao": "auditar", "dados": laudo}

        if intencao == "arte_vetorial":
            tipo_arte = params.get("tipo_arte") or "composicao"
            estilo = params.get("estilo_arte") or "neon_ciano"
            ideia = params.get("ideia") or params.get("texto_alvo") or "Design Vetorial"
            subtexto = params.get("subtexto") or ""

            if tipo_arte == "badge":
                res_arte = self.vector_art.gerar_badge(texto=ideia, estilo=estilo, subtexto=subtexto)
                larg, alt = res_arte["largura"], res_arte["altura"]
            elif tipo_arte == "overlay_video":
                res_arte = self.vector_art.gerar_overlay_reels(titulo=ideia, subtitulo=subtexto)
                larg, alt = 1080, 1920
            elif tipo_arte == "slide_carrossel":
                res_arte = self.vector_art.gerar_slide_carrossel(titulo=ideia, corpo=subtexto)
                larg, alt = 1080, 1350
            else:
                res_arte = await self.vector_art.criar_composicao(con, perfil, ideia, formato=params.get("formato", "feed"), estilo=estilo)
                larg, alt = res_arte.get("largura", 1080), res_arte.get("altura", 1350)

            nome_f = f"arte_{tipo_arte}_{int(time.time() * 1000)}"
            svg_p, png_p = await self.vector_art.salvar_e_renderizar(res_arte["svg"], nome_f, largura=larg, altura=alt)
            res_arte["arquivo_svg"] = str(svg_p)
            res_arte["arquivo_png"] = str(png_p)

            texto_saida = (
                f"{resposta_direta}\n\n"
                f"🎨 *Arte Vetorial Gerada ({tipo_arte})*\n"
                f"- Dimensões: {larg}x{alt}px\n"
                f"- Arquivo: `{png_p.name}`"
            )
            return {"resposta_telegram": texto_saida, "acao": "arte_vetorial", "dados": res_arte}

        # Padrão: devolve a resposta direta do assistente
        return {
            "resposta_telegram": resposta_direta,
            "acao": intencao,
            "dados": params,
        }
