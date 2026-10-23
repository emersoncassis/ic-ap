"""Agente Diretor de Arte: Seleciona layout, paleta, tipografia, selos e busca de imagem."""
import logging
from typing import Any

from .base import BaseAgente

logger = logging.getLogger(__name__)

LAYOUTS_VALIDOS = ["impacto_foto", "editorial", "lista", "dado", "alerta", "citacao"]

SCHEMA_DIRETOR_ARTE = {
    "type": "object",
    "properties": {
        "layout": {
            "type": "string",
            "enum": LAYOUTS_VALIDOS,
        },
        "paleta": {
            "type": "object",
            "properties": {
                "fundo": {"type": "string"},
                "texto_primario": {"type": "string"},
                "texto_secundario": {"type": "string"},
                "destaque": {"type": "string"},
                "acento": {"type": "string"},
                "borda": {"type": "string"},
            },
            "required": ["fundo", "texto_primario", "destaque"],
        },
        "palavras_destaque": {
            "type": "array",
            "items": {"type": "string"},
        },
        "selo": {
            "type": "object",
            "properties": {
                "usar": {"type": "boolean"},
                "estilo": {
                    "type": "string",
                    "enum": ["neon_ciano", "neon_ouro", "alerta_vermelho", "pill_clean"],
                },
                "texto": {"type": "string"},
                "subtexto": {"type": "string"},
            },
            "required": ["usar"],
        },
        "imagem": {
            "type": "object",
            "properties": {
                "usar": {"type": "boolean"},
                "busca_ingles": {"type": "string"},
                "estilo_visual": {"type": "string"},
            },
            "required": ["usar"],
        },
        "justificativa_visual": {"type": "string"},
    },
    "required": ["layout", "paleta", "selo", "imagem"],
}


class DiretorArteAgente(BaseAgente):
    """Agente responsável pela direção de arte, layout e escolhas estéticas."""

    nome = "diretor-de-arte"
    descricao = "Escolhe layout, paleta de cores, palavras de destaque, selos e imagens."
    schema = SCHEMA_DIRETOR_ARTE

    async def conceber(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        pedido: str,
        estrategia: dict[str, Any],
        copy: dict[str, Any],
        layout_anterior: str | None = None,
        feedback_critico: str = "",
    ) -> dict[str, Any]:
        """Concebe a direção visual do post/card."""
        manchete = copy.get("manchete_card") or copy.get("hook_125", "")[:80]
        corpo = copy.get("corpo", "")
        formato = estrategia.get("formato", "feed")

        prompt_user = (
            f"=== DADOS DO POST PARA DIREÇÃO DE ARTE ===\n"
            f"Formato: {formato.upper()} ({'9:16 vertical' if formato == 'story' else '4:5 vertical'})\n"
            f"Objetivo: {estrategia.get('objetivo', 'saves')}\n"
            f"Ângulo Editorial: {estrategia.get('angulo', '')}\n"
            f"Fatos Reais do Pedido: {', '.join(estrategia.get('fatos_centrais', [pedido]))}\n"
            f"Manchete Principal: {manchete}\n"
            f"Corpo/Pontos: {corpo[:300]}\n"
        )

        if layout_anterior:
            outros_layouts = [l for l in LAYOUTS_VALIDOS if l != layout_anterior]
            prompt_user += (
                f"\n⚠️ O usuário solicitou 'MUDAR ESTILO'. O layout anterior foi '{layout_anterior}'. "
                f"Você DEVE escolher um layout DIFERENTE dele. Opções recomendadas: {', '.join(outros_layouts)}.\n"
            )

        if feedback_critico:
            prompt_user += f"\n🔍 Feedback do Crítico Visual para ajuste:\n{feedback_critico}\n"

        prompt_user += (
            "\nEscolha o layout mais adequado dentre os 6 disponíveis (impacto_foto, editorial, lista, dado, alerta, citacao).\n"
            "Defina a paleta hexadecimal com ótimo contraste, 1 a 3 palavras para destacar na manchete, "
            "se usará selo VectorCraft e sua calibração contextual ao assunto, e a busca de imagem em inglês (se o layout exigir foto)."
        )

        dados = await self.executar(
            con=con,
            perfil=perfil,
            mensagem_user=prompt_user,
            temperature=0.6,
        )

        # Regra de salvaguarda: se layout_anterior foi fornecido e o modelo repetiu, força outro
        if layout_anterior and dados.get("layout") == layout_anterior:
            alternativas = [l for l in LAYOUTS_VALIDOS if l != layout_anterior]
            dados["layout"] = alternativas[0]

        return dados
