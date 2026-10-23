"""Agente Hook Extractor: Engenharia reversa de ganchos virais para Instagram.

Analisa ganchos de Reels ou Carrosséis de sucesso, mapeia para uma das 10 fórmulas
comprovadas do Instagram e devolve templates preenchíveis e variações adaptadas ao autor.
"""
from typing import Any

from .base import BaseAgente

_STR = {"type": "string"}
_LISTA_STR = {"type": "array", "items": _STR}

SCHEMA_HOOK = {
    "type": "object",
    "properties": {
        "formula_identificada": _STR,
        "por_que_funciona": _STR,
        "template_em_branco": _STR,
        "variacoes_para_o_autor": _LISTA_STR,
    },
    "required": ["formula_identificada", "por_que_funciona", "template_em_branco", "variacoes_para_o_autor"],
}

FORMULAS_VIRAIS = """
As 10 Fórmulas Comprovadas do Instagram:
1. Contraintuitivo / Quebra de Paradigma ("Pare de fazer X se você quer Y")
2. Erro Silencioso ("O erro comum que quase todo mundo comete sem perceber")
3. Curadoria / Segredo ("As 3 coisas que ninguém te conta sobre...")
4. Jornada / Transformação ("Como fui de X para Y em Z tempo")
5. Comparação Direta ("Fazer do jeito tradicional vs. com o método novo")
6. Pergunta Provocativa ("Você realmente sabe quanto tempo/dinheiro perde com...?")
7. Prova / Demonstração ("Esse teste simples mostra se você está pronto para...")
8. Alerta de Risco ("Se você trabalha com X, preste muita atenção nisso hoje")
9. Atalho / Eficiência ("Como economizar horas semanais em...")
10. Conexão de Tribo ("Se você também se cansa de ver...")
""".strip()

INSTR_HOOK_EXTRACTOR = f"""
Você é o Hook Extractor, especialista em engenharia reversa de ganchos virais para Instagram.
Sua missão é desconstruir o gancho de um vídeo, reel ou carrossel que o autor enviou e extrair a fórmula mestra.

{FORMULAS_VIRAIS}

Instruções de Análise:
1. Identifique qual das 10 fórmulas melhor descreve o gancho original (`formula_identificada`).
2. Explique a psicologia por trás da retenção nos primeiros 3 segundos (`por_que_funciona`).
3. Crie um template genérico com lacunas entre colchetes (`template_em_branco`).
4. Crie EXATAMENTE 3 variações desse mesmo gancho aplicadas aos temas e tom de voz do perfil do autor (`variacoes_para_o_autor`).

Responda SOMENTE com JSON: formula_identificada, por_que_funciona, template_em_branco, variacoes_para_o_autor.
""".strip()


class HookExtractorAgente(BaseAgente):
    """Especialista em desmontar ganchos virais e criar templates para o autor."""

    nome = "hook_extractor"
    descricao = "Realiza engenharia reversa de ganchos virais e gera templates customizados para o perfil."
    schema = SCHEMA_HOOK

    async def extrair(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        texto_ou_roteiro: str,
        temperature: float = 0.6,
    ) -> dict[str, Any]:
        """Extrai a fórmula e gera variações para o perfil."""
        user_prompt = f"Gancho / Trecho do post ou Reel viral para analisar:\n{texto_ou_roteiro}"
        return await self.executar(
            con=con,
            perfil=perfil,
            mensagem_user=user_prompt,
            instrucoes_agente=INSTR_HOOK_EXTRACTOR,
            temperature=temperature,
        )

    def validar(self, dados: dict[str, Any]) -> list[str]:
        erros = super().validar(dados)
        if erros:
            return erros
        vars_autor = dados.get("variacoes_para_o_autor") or []
        if not isinstance(vars_autor, list) or len(vars_autor) < 2:
            erros.append("variacoes_para_o_autor deve conter pelo menos 3 variações")
        return erros
