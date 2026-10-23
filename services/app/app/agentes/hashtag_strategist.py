"""Agente Hashtag Strategist: Estratégia de hashtags SEO para Instagram em 2026.

Elimina o bloco arcaico de 30 tags e gera um conjunto cirúrgico de 3 a 5 hashtags
balanceadas (nicho, volume médio e amplo) indexáveis pela busca semântica da plataforma.
"""
import re
from typing import Any

from .base import BaseAgente

_STR = {"type": "string"}
_TAGS = {"type": "array", "items": _STR}

SCHEMA_HASHTAGS = {
    "type": "object",
    "properties": {
        "nicho": _TAGS,
        "medio": _TAGS,
        "amplo": _TAGS,
        "conjunto_final": _TAGS,
        "justificativa_seo": _STR,
    },
    "required": ["nicho", "medio", "amplo", "conjunto_final", "justificativa_seo"],
}

INSTR_HASHTAG_STRATEGIST = """
Você é o Hashtag Strategist, especialista em SEO semântico para Instagram em 2026.
O algoritmo do Instagram não usa mais blocos gigantes de 30 hashtags. Em vez disso,
a busca funciona por indexação semântica e palavras-chave contextualizadas.

Regras de Estratégia (3 a 5 tags no total):
1. **Nicho (1 a 2 tags)**: Específicas do setor, público qualificado, baixa dispersão (ex.: #segurancaeletronica, #iaaplicada).
2. **Médio Volume (1 a 2 tags)**: Categorias consolidadas no Brasil (ex.: #cftv, #automacaointeligente).
3. **Amplo (1 tag)**: Termo guarda-chuva que contextualiza o ecossistema (ex.: #tecnologia, #gestao).
4. Todas as tags devem ser em Português do Brasil (ou termos técnicos universais aceitos no nicho), sem acentos, sem pontuação, precedidas por '#'.
5. O campo `conjunto_final` deve conter a seleção unificada de EXATAMENTE 3 a 5 hashtags prontas para inserção no post.

Responda SOMENTE com JSON: nicho, medio, amplo, conjunto_final, justificativa_seo.
""".strip()


class HashtagStrategistAgente(BaseAgente):
    """Especialista em seleção de 3 a 5 hashtags de SEO para Instagram."""

    nome = "hashtag_strategist"
    descricao = "Gera conjunto calibrado de 3 a 5 hashtags (nicho, média e ampla) para indexação semântica."
    schema = SCHEMA_HASHTAGS

    @staticmethod
    def normalizar(tags: list[Any]) -> list[str]:
        """Garante formatação uniforme de hashtag (#palavra sem caracteres especiais)."""
        resultado: list[str] = []
        for t in tags or []:
            limpa = re.sub(r"[^\w]", "", str(t).replace("#", ""), flags=re.U).lower()
            if limpa and f"#{limpa}" not in resultado:
                resultado.append(f"#{limpa}")
        return resultado

    async def gerar_estrategia(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        conteudo_post: str,
        temperature: float = 0.5,
    ) -> dict[str, Any]:
        """Gera as hashtags calibradas para o conteúdo."""
        user_prompt = f"Conteúdo do post para análise de palavras-chave e SEO:\n{conteudo_post}"
        dados = await self.executar(
            con=con,
            perfil=perfil,
            mensagem_user=user_prompt,
            instrucoes_agente=INSTR_HASHTAG_STRATEGIST,
            temperature=temperature,
        )
        dados["conjunto_final"] = self.normalizar(dados.get("conjunto_final") or [])
        dados["nicho"] = self.normalizar(dados.get("nicho") or [])
        dados["medio"] = self.normalizar(dados.get("medio") or [])
        dados["amplo"] = self.normalizar(dados.get("amplo") or [])
        return dados

    def validar(self, dados: dict[str, Any]) -> list[str]:
        erros = super().validar(dados)
        if erros:
            return erros
        final = dados.get("conjunto_final") or []
        if not isinstance(final, list) or len(final) < 2 or len(final) > 7:
            erros.append("conjunto_final deve conter entre 3 e 5 hashtags")
        return erros
