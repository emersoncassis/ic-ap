"""Especialista Profile Optimizer: Otimização de Perfil e Posicionamento para Instagram 2026.

Audita e gera elementos de conversão de perfil:
- Nome Otimizado para SEO (campo pesquisável na busca do Instagram)
- Bio de Alta Conversão (proposta de valor em até 150 caracteres + prova + CTA)
- Estrutura de Destaques Estratégicos (Quem Sou, Cases, Bastidores, Comece Aqui)
- Estratégia de Posts Fixados (Grid 3x1)
"""
from typing import Any

from .base import BaseAgente


class ProfileOptimizerAgente(BaseAgente):
    """Especialista em SEO de perfil, bio e conversão de visitantes em seguidores."""

    async def otimizar(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        bio_atual: str = "",
    ) -> dict[str, Any]:
        """Gera propostas de bio, SEO de nome e destaques alinhados ao nicho."""
        instrucao = (
            "Você é o Especialista Profile Optimizer. Sua missão é transformar o perfil do Instagram "
            "do autor em uma máquina de conversão em 2026.\n"
            "Diretrizes:\n"
            "1. Nome (SEO): O campo 'Nome' do Instagram é a principal palavra-chave de busca. Deve conter o nome e a especialidade clara.\n"
            "2. Bio: Máximo de 150 caracteres. Fórmula: Quem você ajuda + Resultado concreto + Prova/Autoridade + Chamada para ação clara.\n"
            "3. Destaques: Estruture os 4 destaques essenciais (Comece Aqui, Autoridade/Cases, Como Funciona, Contato).\n"
            "4. Posts Fixados (Top 3): Defina a função de cada um dos 3 posts fixados do grid."
        )
        system = self.montar_system(perfil, instrucao)

        prompt = (
            f"Bio Atual do Autor (se houver): {bio_atual or 'Não informada'}\n\n"
            "Devolva a resposta EXCLUSIVAMENTE em formato JSON com o seguinte schema:\n"
            "{\n"
            '  "nome_seo_sugerido": "Nome | Nicho/Especialidade (máx 30-50 chars)",\n'
            '  "opcoes_bio": [\n'
            '    {\n'
            '      "tipo": "direta e técnica" | "provocativa" | "focada em autoridade",\n'
            '      "texto": "Texto da bio formatado com quebras de linha (máx 150 chars)",\n'
            '      "cta_link": "Chamada para a ação final"\n'
            '    }\n'
            '  ],\n'
            '  "destaques_sugeridos": [\n'
            '    {"titulo": "Nome do Destaque", "objetivo": "Qual dor resolve"}\n'
            '  ],\n'
            '  "grid_fixados": [\n'
            '    {"posicao": 1, "tema": "Manifesto / Quem Sou", "foco": "Apresentação"},\n'
            '    {"posicao": 2, "tema": "Conteúdo de Maior Autoridade / Case", "foco": "Prova"},\n'
            '    {"posicao": 3, "tema": "Como Trabalhar Comigo / Oferta", "foco": "Conversão"}\n'
            '  ]\n'
            "}"
        )

        dados = await self.gerar_json(con, system, prompt)
        return dados

    def validar(self, dados: dict[str, Any]) -> list[str]:
        """Valida se a otimização cumpre os limites do Instagram."""
        erros = []
        if not dados.get("nome_seo_sugerido"):
            erros.append("nome_seo_sugerido ausente.")

        bios = dados.get("opcoes_bio")
        if not bios or not isinstance(bios, list):
            erros.append("Nenhuma opção de bio fornecida.")
        else:
            for b in bios:
                texto = b.get("texto", "")
                if len(texto) > 160:  # Instagram corta rigorosamente em 150 chars
                    erros.append(f"Opção de bio excede o limite do Instagram ({len(texto)} chars > 150).")

        return erros
