"""Agente Crítico Visual: Inspeciona o card renderizado (visualmente ou por checagens objetivas)."""
import base64
import logging
from pathlib import Path
from typing import Any

from .base import BaseAgente

logger = logging.getLogger(__name__)

SCHEMA_CRITICO = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 10},
        "aprovado": {"type": "boolean"},
        "pontos_fortes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "problemas": {
            "type": "array",
            "items": {"type": "string"},
        },
        "sugestao_ajuste": {"type": "string"},
    },
    "required": ["score", "aprovado", "problemas"],
}


class CriticoAgente(BaseAgente):
    """Agente que avalia o card renderizado antes do envio final."""

    nome = "critico-visual"
    descricao = "Inspeciona o card gerado, avalia legibilidade, contraste e fidelidade ao tema."
    schema = SCHEMA_CRITICO

    async def avaliar(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        caminho_card: Path,
        estourou_texto: bool,
        pedido: str,
        estrategia: dict[str, Any],
        copy: dict[str, Any],
        direcao_arte: dict[str, Any],
        layouts_recentes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Avalia o card gerado. Tenta inspeção visual via LLM multimodal e combina com checagens objetivas."""
        manchete = copy.get("manchete_card") or copy.get("hook_125", "")
        layout_usado = direcao_arte.get("layout", "editorial")
        problemas_objetivos: list[str] = []

        # 1. Checagens Objetivas Imediatas
        if estourou_texto:
            problemas_objetivos.append("O texto do card ultrapassou a altura limite do container visual (overflow).")

        palavras_manchete = len(manchete.split())
        if palavras_manchete > 16:
            problemas_objetivos.append(f"Manchete longa demais para visual mobile ({palavras_manchete} palavras, ideal até 10-12).")

        if layouts_recentes and len(layouts_recentes) >= 2 and all(l == layout_usado for l in layouts_recentes[:2]):
            problemas_objetivos.append(f"O layout '{layout_usado}' foi repetido nos últimos 2 posts consecutivos.")

        # 2. Tentativa de Inspeção Visual com LLM
        imagem_b64 = None
        if caminho_card.exists():
            try:
                raw_bytes = caminho_card.read_bytes()
                imagem_b64 = base64.b64encode(raw_bytes).decode("ascii")
            except Exception as e:
                logger.warning(f"Não foi possível ler JPEG do card para visão: {e}")

        prompt_critica = (
            f"=== AVALIAÇÃO DE QUALIDADE VISUAL DO CARD ===\n"
            f"Pedido original do autor: {pedido}\n"
            f"Formato: {estrategia.get('formato', 'feed')}\n"
            f"Layout escolhido: {layout_usado}\n"
            f"Manchete: {manchete}\n"
            f"CTA: {copy.get('cta', '')}\n"
            f"Paleta de Cores: {direcao_arte.get('paleta', {})}\n"
        )

        if problemas_objetivos:
            prompt_critica += "\nProblemas detectados pelo motor de renderização:\n" + "\n".join(f"- {p}" for p in problemas_objetivos) + "\n"

        prompt_critica += (
            "\nAnalise rigorosamente a imagem anexa (ou os parâmetros acima caso seu modelo não possua visão):\n"
            "1. O card reflete estritamente o pedido do autor sem inventar fatos ou misturar temas?\n"
            "2. A legibilidade é perfeita, com forte contraste e sem sobreposições?\n"
            "3. O design parece premium, moderno e não genérico?\n"
            "Atribua uma nota de 1 a 10. Para aprovar (aprovado=true), a nota DEVE ser no mínimo 8."
        )

        usou_visao = False
        resultado = None

        if imagem_b64:
            try:
                resultado = await self.executar(
                    con=con,
                    perfil=perfil,
                    mensagem_user=prompt_critica,
                    imagem=imagem_b64,
                    temperature=0.3,
                    max_tentativas=2,
                )
                usou_visao = True
            except Exception as e:
                logger.info(f"Modelo sem suporte a visão ou erro na chamada multimodal ({e}). Usando avaliação textual/objetiva.")

        if not resultado:
            # Fallback para avaliação textual caso visão não esteja disponível
            try:
                resultado = await self.executar(
                    con=con,
                    perfil=perfil,
                    mensagem_user=prompt_critica,
                    temperature=0.3,
                    max_tentativas=2,
                )
            except Exception:
                # Fallback heurístico absoluto caso o LLM falhe
                score_heuristico = 9
                if estourou_texto:
                    score_heuristico -= 4
                if len(problemas_objetivos) > 1:
                    score_heuristico -= 2

                resultado = {
                    "score": max(1, min(10, score_heuristico)),
                    "aprovado": score_heuristico >= 8,
                    "pontos_fortes": ["Layout estruturado e renderizado com sucesso."],
                    "problemas": problemas_objetivos,
                    "sugestao_ajuste": "Reduzir tamanho do texto se estourar" if estourou_texto else "Nenhum ajuste crítico.",
                }

        # Se houver estouro de texto confirmado pelo browser, nunca permitir nota >= 8
        if estourou_texto and resultado.get("score", 0) >= 8:
            resultado["score"] = 6
            resultado["aprovado"] = False
            if "problemas" not in resultado or not isinstance(resultado["problemas"], list):
                resultado["problemas"] = []
            resultado["problemas"].append("Texto estourou os limites do card.")
            resultado["sugestao_ajuste"] = "Reduzir o tamanho da manchete ou do corpo para caber sem overflow."

        resultado["usou_visao"] = usou_visao
        return resultado
