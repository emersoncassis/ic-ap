"""Especialista Content Planner: Planejamento estratégico de calendário editorial para Instagram 2026.

Gera cronogramas balanceados respeitando os formatos de alto desempenho:
- Reels (Alcance de novos públicos e descoberta)
- Carrosséis (Autoridade, densidade técnica e salvamentos)
- Posts Únicos / Citações (Identificação e compartilhamentos)
- Stories (Conversão e relacionamento íntimo)
"""
from typing import Any

from .base import BaseAgente


class ContentPlannerAgente(BaseAgente):
    """Especialista em distribuição de pautas e formatos estratégicos."""

    async def planejar_semana(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        dias: int = 5,
        foco_estrategico: str = "crescimento e autoridade",
    ) -> dict[str, Any]:
        """Elabora o plano editorial para os próximos dias."""
        instrucao = (
            "Você é o Especialista Content Planner. Sua função é criar um calendário semanal "
            "com pautas de alto impacto para o perfil do autor no Instagram em 2026.\n"
            "Diretrizes Estratégicas:\n"
            "1. Distribuição de formatos recomendada: 40% Reels (topo de funil), 40% Carrosséis (meio de funil/salvamentos), 20% Posts provocativos/Feed.\n"
            "2. Cada dia deve ter um objetivo claro: 'saves', 'shares', 'comments' ou 'follows'.\n"
            "3. O tom de voz deve ser rigorosamente alinhado ao contexto do autor (sem papo de coach, direto e técnico).\n"
            "4. Forneça o gancho preliminar e o resumo da ideia para cada dia."
        )
        system = self.montar_system(perfil, instrucao)

        prompt = (
            f"Foco Estratégico da Semana: {foco_estrategico}\n"
            f"Quantidade de Dias a Planejar: {dias}\n\n"
            "Devolva a resposta EXCLUSIVAMENTE em formato JSON com o seguinte schema:\n"
            "{\n"
            '  "foco": "resumo do foco da semana",\n'
            '  "dias": [\n'
            "    {\n"
            '      "dia": 1,\n'
            '      "formato": "reel" | "carrossel" | "feed",\n'
            '      "objetivo": "saves" | "shares" | "comments" | "follows",\n'
            '      "tema": "Tema da publicação",\n'
            '      "gancho_sugerido": "Frase de abertura impactante (< 125 chars)",\n'
            '      "resumo_executivo": "O que deve ser abordado"\n'
            "    }\n"
            "  ],\n"
            '  "recomendacao_geral": "Dica prática para a gravação ou design desta semana"\n'
            "}"
        )

        dados = await self.gerar_json(con, system, prompt)
        return dados

    def validar(self, dados: dict[str, Any]) -> list[str]:
        """Valida se o cronograma cumpre os requisitos de consistência."""
        erros = []
        dias = dados.get("dias")
        if not dias or not isinstance(dias, list):
            erros.append("A lista de dias está vazia ou ausente.")
            return erros

        for item in dias:
            if item.get("formato") not in ("reel", "carrossel", "feed", "story"):
                erros.append(f"Formato inválido no dia {item.get('dia')}: {item.get('formato')}")
            if item.get("objetivo") not in ("saves", "shares", "comments", "follows"):
                erros.append(f"Objetivo inválido no dia {item.get('dia')}: {item.get('objetivo')}")
            if not item.get("tema"):
                erros.append(f"Dia {item.get('dia')} está sem tema definido.")

        return erros
