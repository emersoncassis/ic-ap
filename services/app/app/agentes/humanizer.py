"""Agente Humanizer: Filtro Anti-IA determinístico e polidor de tom natural PT-BR.

Detecta e remove vícios clássicos de LLMs, tempestades de emojis, travessões excessivos
e termos publicitários artificiais, garantindo que o texto soe escrito por um humano.
"""
import re
from typing import Any

from .base import BaseAgente

TERMOS_BANIDOS = [
    r"\bno mundo din[aâ]mico de hoje\b",
    r"\bno cen[aá]rio atual\b",
    r"\b[eé] crucial (entender|lembrar|destacar)\b",
    r"\b[eé] fundamental (ressaltar|compreender)\b",
    r"\bmergulhe fundo\b",
    r"\bgame changer\b",
    r"\bdivisor de [aá]guas\b",
    r"\bjornada transformadora\b",
    r"\bdesvende( os)? segredos?\b",
    r"\bem suma\b",
    r"\bportanto\b",
    r"\brevolucion[aá]ri[oa]\b",
    r"\bimperativo\b",
    r"\bvislumbrar\b",
    r"\btecer considera[cç][oõ]es\b",
    r"\bmas espere[,!] tem mais\b",
    r"\be a melhor parte\??\b",
    r"\bo pulo do gato\b",
    r"\bpara ser bem sincero\b",
    r"\bpreciso confessar uma coisa\b",
]

_STR = {"type": "string"}
_LISTA_STR = {"type": "array", "items": _STR}

SCHEMA_HUMANIZER = {
    "type": "object",
    "properties": {
        "texto_humanizado": _STR,
        "pontos_corrigidos": _LISTA_STR,
        "densidade_ia_estimada": {"type": "integer"},
    },
    "required": ["texto_humanizado", "pontos_corrigidos", "densidade_ia_estimada"],
}

INSTR_HUMANIZER = """
Você é o Humanizer, especialista em desintoxicação de textos gerados por inteligência artificial.
Sua missão é pegar um texto de Instagram e limpá-lo de qualquer vício artificial, mantendo 100% da mensagem original e a voz autêntica do autor.

Checklist de Desintoxicação (Português do Brasil 2026):
1. **Eliminar clichês de IA**: Remova aberturas empoladas ("no mundo dinâmico", "é crucial", "mergulhe fundo", "divisor de águas").
2. **Eliminar pontes teatrais**: Corte expressões forçadas como "Mas espere, tem mais", "E a melhor parte?", "O segredo que ninguém conta".
3. **Controlar travessões (em-dash)**: No máximo 1 travessão a cada 100 palavras. Substitua por vírgula ou ponto quando excessivo.
4. **Acabar com tempestades de emojis**: Mantenha no máximo 1 a 2 emojis no post inteiro, contextualizados. Nunca use emojis como marcadores de cada linha.
5. **Cortar frases fragmentadas em estacato**: Evite sequências artificiais de uma palavra só ("Rápido. Prático. Seguro.").
6. **Ritmo de fala real**: Frases com variação de tamanho, conectivos naturais do dia a dia brasileiro, sem formalismo artificial de redação corporativa.

Responda SOMENTE com JSON contendo: texto_humanizado, pontos_corrigidos (lista do que foi ajustado), densidade_ia_estimada (de 0 a 100).
""".strip()


class HumanizerAgente(BaseAgente):
    """Agente de auditoria e humanização de conteúdo."""

    nome = "humanizer"
    descricao = "Audita e remove vícios de inteligência artificial, tempestades de emojis e expressões clichês."
    schema = SCHEMA_HUMANIZER

    @classmethod
    def auditar(cls, texto: str) -> dict[str, Any]:
        """Auditoria determinística rápida sem chamada de IA. Devolve diagnóstico com score de 0 a 100%."""
        txt = texto or ""
        palavras = [p for p in re.findall(r"\w+", txt) if p]
        total_palavras = max(len(palavras), 1)

        # 1. Termos banidos
        termos_encontrados = []
        for pat in TERMOS_BANIDOS:
            matches = re.findall(pat, txt, flags=re.IGNORECASE)
            if matches:
                termos_encontrados.extend([m if isinstance(m, str) else m[0] for m in matches])

        # 2. Travessões (em-dash / en-dash / traço duplo)
        travessoes = len(re.findall(r"(—|–|--)", txt))
        travessoes_por_100_palavras = (travessoes / total_palavras) * 100

        # 3. Emojis
        # Regex Unicode para faixas comuns de emojis
        emojis = re.findall(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF]", txt)
        total_emojis = len(emojis)

        # 4. Cálculo de Pontuação de Densidade de IA (0% limpo, 100% robô)
        score = 0
        penalidades = []

        if termos_encontrados:
            peso_termos = min(len(termos_encontrados) * 20, 50)
            score += peso_termos
            penalidades.append(f"{len(termos_encontrados)} clichê(s) de IA detectado(s): {', '.join(set(termos_encontrados))}")

        if travessoes_por_100_palavras > 1.2:
            score += 20
            penalidades.append(f"Excesso de travessões ({travessoes} travessões para {total_palavras} palavras)")

        if total_emojis > 4:
            score += 15
            penalidades.append(f"Tempestade de emojis ({total_emojis} emojis)")

        # Detecção de listas com emoji no início de cada linha
        linhas_com_emoji = re.findall(r"^\s*[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF]", txt, flags=re.M)
        if len(linhas_com_emoji) >= 3:
            score += 15
            penalidades.append("Lista padronizada com emoji no início de cada linha (marca clássica de IA)")

        score = min(score, 100)
        return {
            "score_ia": score,
            "nivel": "alto" if score >= 50 else ("moderado" if score >= 25 else "baixo"),
            "total_palavras": total_palavras,
            "total_emojis": total_emojis,
            "total_travessoes": travessoes,
            "termos_encontrados": termos_encontrados,
            "diagnostico": penalidades or ["Texto soa natural e sem marcas evidentes de IA."],
        }

    async def humanizar(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        texto: str,
        temperature: float = 0.5,
    ) -> dict[str, Any]:
        """Aplica a reescrita de humanização via LLM se o texto contiver marcas de IA."""
        auditoria_previa = self.auditar(texto)
        user_prompt = (
            f"Texto original para desintoxicação:\n{texto}\n\n"
            f"Diagnóstico prévio detectado:\n"
            f"- Score de IA: {auditoria_previa['score_ia']}%\n"
            f"- Problemas encontrados: {'; '.join(auditoria_previa['diagnostico'])}\n\n"
            "Reescreva mantendo a essência, porém em linguagem 100% natural brasileira."
        )

        resultado = await self.executar(
            con=con,
            perfil=perfil,
            mensagem_user=user_prompt,
            instrucoes_agente=INSTR_HUMANIZER,
            temperature=temperature,
        )
        resultado["auditoria_antes"] = auditoria_previa
        resultado["auditoria_depois"] = self.auditar(resultado["texto_humanizado"])
        return resultado
