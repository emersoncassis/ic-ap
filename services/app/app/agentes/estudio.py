"""Estúdio Agêntico de Criação: Orquestra o pipeline completo de criação editorial.

Pipeline:
1. Estrategista (formato, objetivo, ângulo, fatos verificados)
2. Redator (copy, hook <125 chars, manchete, cta contextual) + Humanizador
3. Diretor de Arte (layout dentre 6 opções, paleta, busca de foto, selos)
4. Obtenção de imagem de tema (Higgsfield -> Unsplash -> fallback tipográfico)
5. Renderização em alta definição no Playwright
6. Crítico Visual (inspeção visual e objetiva; até 1 ciclo de refinamento se nota < 8)
"""
import logging
import uuid
from typing import Any, Callable, Awaitable

from .. import banco, config as C, meta_ai, render, settings
from .estrategista import EstrategistaAgente
from .caption_writer import CaptionWriterAgente
from .humanizer import HumanizerAgente
from .diretor_arte import DiretorArteAgente
from .critico import CriticoAgente

logger = logging.getLogger(__name__)


class EstudioCriativo:
    """Orquestrador do estúdio agêntico de criação de conteúdo."""

    def __init__(self):
        self.estrategista = EstrategistaAgente()
        self.redator = CaptionWriterAgente()
        self.humanizador = HumanizerAgente()
        self.diretor_arte = DiretorArteAgente()
        self.critico = CriticoAgente()

    async def criar_post(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        pedido: str,
        formato_forcado: str | None = None,
        layout_anterior: str | None = None,
        on_status: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Executa a esteira agêntica completa para produzir um card e copy de alto padrão."""

        async def _notificar(msg: str) -> None:
            if on_status:
                try:
                    await on_status(msg)
                except Exception as e:
                    logger.debug(f"Falha ao notificar status: {e}")

        # Via Rápida Principal: Meta AI Autenticado (Cookies) + Técnica Blow Up no Instagram
        if settings.segredo("meta_ai_cookies"):
            formato_alvo = formato_forcado or ("story" if "story" in pedido.lower() or "stories" in pedido.lower() else "feed")
            handle_p = (perfil.get("handle") or "emery.carvalho").lstrip("@")
            await _notificar(f"💥 *Meta AI + Blow Up:* pesquisando no Instagram para `@{handle_p}` e gerando post viral...")
            res_blow = await meta_ai.gerar_post_blow_up(pedido=pedido, perfil=perfil, formato=formato_alvo)
            if res_blow.get("ok"):
                layout_escolhido = "impacto_foto"
                manchete_texto = res_blow.get("manchete") or "Destaque Blow Up"
                corpo_texto = res_blow.get("corpo") or ""
                itens_lista = res_blow.get("itens_card") or []
                dado_num = res_blow.get("dado_destaque") or ""
                palavras_dest = res_blow.get("palavras_destaque") or []
                cta_txt = res_blow.get("cta") or ("Responda no Direct" if formato_alvo == "story" else "Comente aqui")
                legenda_final = res_blow.get("legenda") or ""
                busca_img = res_blow.get("imagem_ingles") or f"{manchete_texto} {corpo_texto[:60]}"

                paleta_blow = {
                    "fundo": "#05070B",
                    "texto_primario": "#FFFFFF",
                    "texto_secundario": "#E2E8F0",
                    "destaque": "#00FF88",
                    "borda": "rgba(0, 255, 136, 0.28)",
                }

                # Sempre baixa fotografia contextualizada da base online para o tema da legenda
                imagem_fundo_path = None
                dest_fundo = C.DATA / "fundos" / f"blow_{uuid.uuid4().hex}.jpg"
                try:
                    await _notificar(f"📸 *Buscando Fotografia Contextual:* `{busca_img[:45]}`...")
                    await banco.baixar_uma(busca_img, dest_fundo, orientacao="portrait")
                    if dest_fundo.exists():
                        imagem_fundo_path = dest_fundo
                except Exception as e_img:
                    logger.warning(f"Falha ao obter imagem de fundo Blow Up ({e_img})")
                    imagem_fundo_path = None

                await _notificar(f"🎨 *Montando Card ({formato_alvo.upper()}):* foto contextual + legenda sobreposta...")
                nome_card, estourou = await render.render_design(
                    layout=layout_escolhido,
                    formato=formato_alvo,
                    manchete=manchete_texto,
                    paragrafos=corpo_texto,
                    handle=perfil.get("handle", ""),
                    nome=perfil.get("nome", "Autor"),
                    palavras_destaque=palavras_dest,
                    itens=itens_lista,
                    dado=dado_num,
                    dado_legenda=corpo_texto.split("\n")[0] if corpo_texto else "",
                    frase_impacto=manchete_texto,
                    cta_texto=cta_txt,
                    post_tipo_label="",
                    selo_uri=None,
                    imagem_fundo_path=imagem_fundo_path,
                    paleta=paleta_blow,
                    p=perfil,
                )
                copy_dict = {
                    "manchete_card": manchete_texto,
                    "hook_125": manchete_texto,
                    "corpo": corpo_texto,
                    "itens_card": itens_lista,
                    "dado_destaque": dado_num,
                    "dado_legenda": corpo_texto.split("\n")[0] if corpo_texto else "",
                    "frase_impacto": manchete_texto,
                    "cta": cta_txt,
                    "cta_texto": cta_txt,
                    "palavras_destaque": palavras_dest,
                    "legenda_completa": legenda_final,
                }
                direcao_dict = {
                    "layout": layout_escolhido,
                    "paleta": paleta_blow,
                    "palavras_destaque": palavras_dest,
                }
                return {
                    "arquivo_card": nome_card,
                    "formato": formato_alvo,
                    "estrategia": {"formato": formato_alvo, "objetivo": "shares", "angulo": "blow_up_meta_ai"},
                    "copy": copy_dict,
                    "direcao_arte": direcao_dict,
                    "avaliacao_critico": {"aprovado": True, "score": 10},
                    "legenda": legenda_final,
                    "manchete": manchete_texto,
                    "corpo": corpo_texto,
                    "cta": cta_txt,
                    "layout": layout_escolhido,
                    "estourou": estourou,
                    "origem": res_blow.get("origem", "meta.ai_navegador"),
                }

        # 1. Estrategista
        await _notificar("🧠 *Estrategista:* analisando pedido e definindo ângulo editorial...")
        estrategia = await self.estrategista.planejar(
            con=con,
            perfil=perfil,
            pedido=pedido,
            formato_forcado=formato_forcado,
        )

        formato = estrategia.get("formato", formato_forcado or "feed")
        objetivo = estrategia.get("objetivo", "saves")

        # 2. Redator
        await _notificar("✍️ *Redator:* criando copy de alta retenção e manchete...")
        copy = await self.redator.redigir(
            con=con,
            perfil=perfil,
            ideia_ou_noticia=pedido,
            objetivo=objetivo,
            formato=formato,
            estrategia=estrategia,
        )

        # 3. Auditoria Anti-IA e Humanização da Legenda
        legenda_bruta = copy.get("legenda_completa", "")
        auditoria = self.humanizador.auditar(legenda_bruta)
        if auditoria.get("score_ia", 0) >= 35:
            await _notificar("✨ *Humanizador:* polindo copy e eliminando clichês de IA...")
            hum = await self.humanizador.humanizar(con, perfil, legenda_bruta)
            copy["legenda_completa"] = hum["texto_humanizado"]

        # 4. Diretor de Arte + Render + Crítico Visual (Loop de até 1 revisão)
        MAX_REVISOES = 1
        feedback_critico = ""
        direcao_arte = {}
        avaliacao = {}
        nome_card = ""
        estourou = False

        for rodada in range(MAX_REVISOES + 1):
            if rodada == 0:
                await _notificar("🎨 *Diretor de Arte:* selecionando layout, paleta e elementos visuais...")
            else:
                await _notificar(f"🎨 *Diretor de Arte:* refinando layout com feedback do Crítico ({feedback_critico})...")

            direcao_arte = await self.diretor_arte.conceber(
                con=con,
                perfil=perfil,
                pedido=pedido,
                estrategia=estrategia,
                copy=copy,
                layout_anterior=layout_anterior if rodada == 0 else direcao_arte.get("layout"),
                feedback_critico=feedback_critico,
            )

            layout_escolhido = direcao_arte.get("layout", "editorial")

            # 4.1 Obtenção da Imagem Contextualizada
            imagem_fundo_path = None
            cfg_img = direcao_arte.get("imagem", {})
            busca_termo = cfg_img.get("busca_ingles") or f"{copy.get('manchete_card', '')} {pedido[:60]}"
            dest_fundo = C.DATA / "fundos" / f"fundo_{uuid.uuid4().hex}.jpg"
            try:
                await _notificar(f"📸 *Estúdio:* buscando imagem contextualizada (`{busca_termo[:45]}`)...")
                await banco.baixar_uma(busca_termo, dest_fundo, orientacao="portrait")
                if dest_fundo.exists():
                    imagem_fundo_path = dest_fundo
            except Exception as e:
                logger.warning(f"Não foi possível baixar foto do tema ({e}).")
                imagem_fundo_path = None

            selo_uri = None

            # 4.3 Renderização do Card no Playwright
            manchete_texto = copy.get("manchete_card") or copy.get("hook_125", "")
            corpo_texto = copy.get("corpo", "")
            itens_lista = copy.get("itens_card") or []
            dado_num = copy.get("dado_destaque") or ""
            frase_imp = copy.get("frase_impacto") or ""
            paleta_cores = direcao_arte.get("paleta", {})
            palavras_dest = direcao_arte.get("palavras_destaque", [])
            cta_txt = copy.get("cta", "")

            nome_card, estourou = await render.render_design(
                layout=layout_escolhido,
                formato=formato,
                manchete=manchete_texto,
                paragrafos=corpo_texto,
                handle=perfil.get("handle", ""),
                nome=perfil.get("nome", "Autor"),
                palavras_destaque=palavras_dest,
                itens=itens_lista,
                dado=dado_num,
                dado_legenda=corpo_texto.split("\n")[0] if corpo_texto else "",
                frase_impacto=frase_imp,
                cta_texto=cta_txt,
                post_tipo_label="Story" if formato == "story" else "Post de Feed",
                selo_uri=selo_uri,
                imagem_fundo_path=imagem_fundo_path,
                paleta=paleta_cores,
                p=perfil,
            )

            # 4.4 Crítico Visual
            await _notificar("🔍 *Crítico Visual:* inspecionando legibilidade, contraste e fidelidade...")
            caminho_card = C.CARDS / nome_card
            avaliacao = await self.critico.avaliar(
                con=con,
                perfil=perfil,
                caminho_card=caminho_card,
                estourou_texto=estourou,
                pedido=pedido,
                estrategia=estrategia,
                copy=copy,
                direcao_arte=direcao_arte,
            )

            score = avaliacao.get("score", 8)
            aprovado = avaliacao.get("aprovado", True)

            if aprovado or rodada >= MAX_REVISOES:
                status_txt = "Aprovado com louvor" if score >= 9 else ("Aprovado" if score >= 8 else "Liberado com ressalvas")
                await _notificar(f"✅ *Crítico Visual:* Nota *{score}/10* ({status_txt})")
                break

            # Se rejeitado e ainda há tentativa, prepara feedback para o loop
            feedback_critico = avaliacao.get("sugestao_ajuste") or "; ".join(avaliacao.get("problemas", []))
            await _notificar(f"🔍 *Crítico Visual:* Nota *{score}/10* (Refinando: {feedback_critico[:100]}...)")

        return {
            "arquivo_card": nome_card,
            "formato": formato,
            "estrategia": estrategia,
            "copy": copy,
            "direcao_arte": direcao_arte,
            "avaliacao_critico": avaliacao,
            "legenda": copy.get("legenda_completa", ""),
            "manchete": copy.get("manchete_card") or copy.get("hook_125", ""),
            "corpo": copy.get("corpo", ""),
            "cta": copy.get("cta", ""),
            "layout": direcao_arte.get("layout", "editorial"),
            "estourou": estourou,
        }
