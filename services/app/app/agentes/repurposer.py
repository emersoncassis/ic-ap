"""Especialista Repurposer: Adaptação de conteúdos de outras plataformas para o Instagram 2026.

Transforma textos longos de blogs, newsletters, threads do X (Twitter) e posts do LinkedIn
em formatos nativos do Instagram (Carrossel ou Feed com gancho de 125 caracteres),
eliminando referências de outras redes ("RT", "link nos comentários", "compartilhe na sua rede").
"""
import re
from typing import Any

from .base import BaseAgente


class RepurposerAgente(BaseAgente):
    """Especialista em repurposing multiplataforma sem deixar pistas de outras redes."""

    TERMOS_PROIBIDOS_OUTRAS_REDES = [
        "link nos comentários",
        "link no primeiro comentário",
        "leia o artigo completo no blog",
        "retuíte",
        "retweet",
        "thread no x",
        "conexões do linkedin",
        "arrasta pra cima",
        "clique no link da bio",  # Instagram 2026 prioriza engajamento nativo ou DM direta
    ]

    async def adaptar(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        conteudo_original: str,
        formato_destino: str = "carrossel",
    ) -> dict[str, Any]:
        """Transforma o conteúdo original em um formato Instagram de alta performance."""
        instrucao = (
            "Você é o Especialista Repurposer. Sua missão é transformar um conteúdo externo "
            "(artigo de blog, post do LinkedIn, newsletter ou thread do X) em um conteúdo NATIVO para o Instagram.\n"
            "Regras Inegociáveis:\n"
            "1. Elimine todo e qualquer resquício da plataforma de origem (ex: 'link no primeiro comentário', 'leia na íntegra').\n"
            "2. Respeite as regras de 2026: Hook nos primeiros 125 caracteres, parágrafos curtos, 1 único CTA.\n"
            "3. Se o formato de destino for 'carrossel', estruture de 4 a 8 slides com abertura de loop e entrega progressiva.\n"
            "4. Se for 'feed', estruture uma legenda altamente escaneável com gancho direto e memorável.\n"
            "5. Mantenha 100% da essência e tom de voz do autor."
        )
        system = self.montar_system(perfil, instrucao)

        prompt = (
            f"Formato de Destino Solicitado: {formato_destino}\n\n"
            f"--- CONTEÚDO ORIGINAL ---\n"
            f"{conteudo_original}\n\n"
            "Devolva a resposta EXCLUSIVAMENTE em formato JSON com o seguinte schema:\n"
            "{\n"
            '  "formato": "carrossel" ou "feed",\n'
            '  "hook_125": "Gancho matador com menos de 125 caracteres",\n'
            '  "conteudo_adaptado": "Texto completo adaptado",\n'
            '  "cta": "Chamada para ação única",\n'
            '  "resumo_mudancas": "Breve explicação das adaptações feitas",\n'
            '  "hashtags": ["#tag1", "#tag2", "#tag3"]\n'
            "}"
        )

        dados = await self.gerar_json(con, system, prompt)
        return dados

    @classmethod
    def limpar_artefatos_externos(cls, texto: str) -> str:
        """Remove preventivamente termos típicos de outras redes."""
        limpo = texto
        for termo in cls.TERMOS_PROIBIDOS_OUTRAS_REDES:
            limpo = re.sub(rf"(?i)\b{re.escape(termo)}\b", "", limpo)
        # Limpa espaços duplos resultantes
        limpo = re.sub(r" +", " ", limpo).strip()
        return limpo

    def validar(self, dados: dict[str, Any]) -> list[str]:
        """Valida se o conteúdo adaptado cumpre os critérios de publicação."""
        erros = []
        if not dados.get("hook_125"):
            erros.append("hook_125 ausente.")
        elif len(dados["hook_125"]) > 135:
            erros.append(f"hook_125 longo demais ({len(dados['hook_125'])} chars).")

        texto_completo = (dados.get("conteudo_adaptado") or "").lower()
        for termo in self.TERMOS_PROIBIDOS_OUTRAS_REDES:
            if termo in texto_completo:
                erros.append(f"Artefato proibido de outra rede detectado: '{termo}'.")

        return erros
