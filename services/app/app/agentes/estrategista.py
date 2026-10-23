"""Agente Estrategista: Define formato, objetivo, ângulo e fatos verificados do pedido."""
import logging
from typing import Any

from .base import BaseAgente

logger = logging.getLogger(__name__)

SCHEMA_ESTRATEGISTA = {
    "type": "object",
    "properties": {
        "formato": {
            "type": "string",
            "enum": ["story", "feed", "reels", "carrossel"],
        },
        "objetivo": {
            "type": "string",
            "enum": ["saves", "shares", "comments", "follows"],
        },
        "angulo": {"type": "string"},
        "fatos_centrais": {
            "type": "array",
            "items": {"type": "string"},
        },
        "proposta_de_valor": {"type": "string"},
        "palavras_chave": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["formato", "objetivo", "angulo", "fatos_centrais", "proposta_de_valor"],
}


class EstrategistaAgente(BaseAgente):
    """Agente que atua como curador e estrategista editorial do time."""

    nome = "estrategista"
    descricao = "Define formato, objetivo, ângulo e fatos verificados do pedido."
    schema = SCHEMA_ESTRATEGISTA

    async def planejar(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        pedido: str,
        formato_forcado: str | None = None,
        historico_recente: str = "",
    ) -> dict[str, Any]:
        """Elabora a estratégia editorial para o pedido do usuário."""
        prompt_user = f"Pedido / Notícia bruta do autor:\n{pedido.strip()}\n"

        if formato_forcado and formato_forcado in ("story", "feed", "reels", "carrossel"):
            prompt_user += f"\nATENÇÃO: O formato solicitado obrigatoriamente é: '{formato_forcado}'. Mantenha formato='{formato_forcado}'.\n"

        if historico_recente:
            prompt_user += f"\nÚltimos posts gerados recentemente (para evitar temas ou formatos idênticos):\n{historico_recente}\n"

        prompt_user += (
            "\nAnalise o pedido e devolva o JSON estruturado com: formato, objetivo, angulo, "
            "fatos_centrais (apenas o que está na mensagem, sem inventar fatos), proposta_de_valor e palavras_chave."
        )

        res = await self.executar(
            con=con,
            perfil=perfil,
            mensagem_user=prompt_user,
            temperature=0.4,
        )

        if formato_forcado and formato_forcado in ("story", "feed", "reels", "carrossel"):
            res["formato"] = formato_forcado

        return res
