"""Especialista Audience Insights: Mapeamento de Dores, Desejos e Tendências do Nicho 2026.

Mapeia os gatilhos emocionais e as dúvidas mais urgentes da audiência do autor:
- Dores latentes (problemas que eles sofrem mas não admitem)
- Objeções comuns a serviços/soluções
- Dúvidas de busca (o que o público pesquisa no Instagram Search e Google)
- Ângulos de conteúdo provocativos para furar a bolha
"""
from typing import Any

from .base import BaseAgente


class AudienceInsightsAgente(BaseAgente):
    """Especialista em inteligência de audiência e psicologia de consumo de conteúdo."""

    async def mapear_audiencia(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        sub_nicho: str = "",
    ) -> dict[str, Any]:
        """Gera um raio-x das maiores dores, desejos e dúvidas da audiência."""
        instrucao = (
            "Você é o Especialista Audience Insights. Sua missão é dissecar a mente da audiência "
            "do autor com base no contexto profissional, mercado e tom de voz.\n"
            "Diretrizes:\n"
            "1. Fuja do superficial: identifique as dores reais (ex: perda de dinheiro, sensação de incompetência, frustração com ferramentas ruins).\n"
            "2. Liste as objeções mais comuns que impedem essa audiência de contratar ou confiar.\n"
            "3. Sugira 5 ângulos de conteúdo com alto potencial de compartilhamento e comentários."
        )
        system = self.montar_system(perfil, instrucao)

        prompt = (
            f"Foco / Sub-nicho Específico: {sub_nicho or 'Público principal do perfil'}\n\n"
            "Devolva a resposta EXCLUSIVAMENTE em formato JSON com o seguinte schema:\n"
            "{\n"
            '  "perfil_do_seguidor_ideal": "Descrição sucinta de quem é a pessoa",\n'
            '  "dores_principais": [\n'
            '    {"dor": "Descrição da dor", "impacto_emocional": "Como ela se sente"}\n'
            '  ],\n'
            '  "objecoes_comuns": [\n'
            '    {"objecao": "O que pensam para hesitar", "como_quebrar": "Argumento irrefutável"}\n'
            '  ],\n'
            '  "angulos_de_conteudo_virais": [\n'
            '    {\n'
            '      "tipo": "provocacao" | "revelacao_de_bastidor" | "tutorial_descomplicado",\n'
            '      "ideia_central": "Resumo do post",\n'
            '      "gancho_sugerido": "Frase de abertura (< 125 chars)"\n'
            '    }\n'
            '  ]\n'
            "}"
        )

        dados = await self.gerar_json(con, system, prompt)
        return dados

    def validar(self, dados: dict[str, Any]) -> list[str]:
        """Valida se a análise de audiência contém os dados essenciais."""
        erros = []
        if not dados.get("dores_principais"):
            erros.append("dores_principais ausentes.")
        if not dados.get("angulos_de_conteudo_virais"):
            erros.append("angulos_de_conteudo_virais ausentes.")
        return erros
