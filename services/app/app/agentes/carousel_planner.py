"""Agente Carousel Planner: Planejador de carrosséis de alta conversão (4 a 10 slides).

Estruturado para retenção no Instagram:
- Slide 1: Capa com abertura de loop (curiosity gap) dentro das safe zones.
- Slides 2 ao penúltimo: Valor concentrado no início (front-loaded) sem enrolação.
- Slide final: Payoff (resolução do aprendizado) + Duplo CTA (salvar e seguir).
"""
from contextvars import ContextVar
from typing import Any

from .. import llm
from .base import BaseAgente

# quantidade de slides pedida na chamada em curso (ContextVar: duas chamadas ao mesmo tempo não se misturam)
_N_PEDIDO: ContextVar[int | None] = ContextVar("carousel_n_pedido", default=None)

_STR = {"type": "string"}
_TAGS = {"type": "array", "items": _STR}

SCHEMA_CAROUSEL = {
    "type": "object",
    "properties": {
        "titulo_carrossel": _STR,
        "total_slides": {"type": "integer"},
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slide_n": {"type": "integer"},
                    "tipo": {"type": "string", "enum": ["capa", "conteudo", "cta"]},
                    "titulo": _STR,
                    "texto": _STR,
                },
                "required": ["slide_n", "tipo", "titulo", "texto"],
            },
        },
        "legenda_instagram": _STR,
        "cta": _STR,
        "hashtags": _TAGS,
    },
    "required": ["titulo_carrossel", "total_slides", "slides", "legenda_instagram", "cta", "hashtags"],
}

INSTR_CAROUSEL_PLANNER = """
Você é o Carousel Planner, especialista em carrosséis de alta retenção no Instagram em 2026.
Seu trabalho é transformar uma ideia, processo ou ensinamento em uma sequência de 4 a 10 slides impecáveis.

Estrutura Obrigatória de Slides (Safe Zones 1080×1350):
1. **Slide 1 (Capa)**:
   - `tipo`: "capa"
   - `titulo`: Frase de impacto de até 10 palavras que abre um loop (curiosity gap).
   - `texto`: Subtítulo de apoio curto (até 90 caracteres), nunca vazio.
2. **Slides Intermediários (Valor Front-Loaded)**:
   - `tipo`: "conteudo"
   - Entregue o insight mais forte já no Slide 2 e 3 (quem rola os primeiros 3 slides lê o carrossel inteiro).
   - `titulo`: Até 8 palavras.
   - `texto`: Texto escaneável, direto e objetivo (até 220 caracteres).
3. **Slide Final (Payoff & CTA)**:
   - `tipo`: "cta"
   - `titulo`: Conclusão ou resumo em poucas palavras (até 8 palavras).
   - `texto`: Chamada clara para ação dupla: Salvar para consultar depois e seguir o perfil (até 160 caracteres).

Legenda e Tags:
- `legenda_instagram`: Legenda completa conectada ao carrossel com gancho nos primeiros 125 caracteres, até 1200 caracteres no total.
- `cta`: A chamada para ação final.
- `hashtags`: 3 a 5 hashtags estratégicas (nicho, média, ampla).

Responda SOMENTE com JSON: titulo_carrossel, total_slides, slides, legenda_instagram, cta, hashtags.
""".strip()


class CarouselPlannerAgente(BaseAgente):
    """Planeja carrosséis estruturados por slide com foco em swipe rate e conversão."""

    nome = "carousel_planner"
    descricao = "Estrutura carrosséis de 4 a 10 slides com loop de abertura, valor front-loaded e payoff final."
    schema = SCHEMA_CAROUSEL

    async def planejar(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        ideia: str,
        n_slides: int = 6,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Gera o planejamento completo slide a slide."""
        qtd = max(4, min(int(n_slides or 6), 10))
        user_prompt = (
            f"Ideia/Tema para o Carrossel:\n{ideia}\n\n"
            f"Quantidade exata de slides solicitada: {qtd}"
        )
        token = _N_PEDIDO.set(qtd)
        try:
            return await self.executar(
                con=con,
                perfil=perfil,
                mensagem_user=user_prompt,
                instrucoes_agente=INSTR_CAROUSEL_PLANNER,
                temperature=temperature,
            )
        finally:
            _N_PEDIDO.reset(token)

    def validar(self, dados: dict[str, Any]) -> list[str]:
        erros = super().validar(dados)
        if erros:
            return erros

        try:
            llm.validar_slides(dados.get("slides"), _N_PEDIDO.get())  # sem n pedido (chamada direta), só confere o conteúdo
        except ValueError as e:
            erros.append(str(e))
        return erros
