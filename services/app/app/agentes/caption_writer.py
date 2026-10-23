"""Agente Caption Writer: Cria legendas de alta retenção com hook nos primeiros 125 caracteres.

Calibrado para as regras de engajamento do Instagram em 2026 e adaptado ao tom do autor.
"""
from typing import Any

from .base import BaseAgente

_STR = {"type": "string"}
_TAGS = {"type": "array", "items": _STR}

SCHEMA_CAPTION = {
    "type": "object",
    "properties": {
        "hook_125": _STR,
        "manchete_card": _STR,
        "corpo": _STR,
        "itens_card": {"type": "array", "items": _STR},
        "dado_destaque": _STR,
        "frase_impacto": _STR,
        "cta": _STR,
        "objetivo": {"type": "string", "enum": ["saves", "shares", "comments", "follows"]},
        "legenda_completa": _STR,
        "hashtags_sugeridas": _TAGS,
        "cenas_reels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cena": {"type": "integer"},
                    "fala": _STR,
                    "busca_visual": _STR,
                },
                "required": ["cena", "fala", "busca_visual"],
            },
        },
    },
    "required": ["hook_125", "corpo", "cta", "objetivo", "legenda_completa", "hashtags_sugeridas"],
}

INSTR_CAPTION_WRITER = """
Você é o Caption Writer, especialista em redação de legendas nativas de alta performance para Instagram em 2026.
Seu trabalho é pegar a ideia, notícia ou contexto do autor e redigir uma legenda irresistível.

Regras Obrigatórias de Redação (2026):
1. **Hook Inquebrável nos Primeiros 125 Caracteres (`hook_125`)**:
   - O Instagram corta o texto com o botão "... mais" logo por volta de 125 caracteres.
   - O hook DEVE caber inteiramente antes dessa quebra e despertar curiosidade imediata, sem enrolação.
2. **Corpo Escaneável (`corpo`)**:
   - Parágrafos curtíssimos (1 a 3 frases).
   - Espaçamento limpo entre ideias. Nada de paredes de texto.
   - Entrega valor direto sem clichês de IA.
3. **Um Único CTA Claro (`cta`)**:
   - Escolha exatamente 1 objetivo baseado no pedido ou na natureza do post:
     - `saves`: Para conteúdo útil, tutoriais ou listas (ex.: "Salve esse post para aplicar na sua próxima sprint.").
     - `shares`: Para opiniões contraintuitivas ou alertas (ex.: "Mande para quem precisa parar de cometer esse erro.").
     - `comments`: Para debates e perguntas polarizantes (ex.: "Você concorda com isso ou faz diferente? Comente.").
     - `follows`: Para autoridade e visão de futuro (ex.: "Siga o perfil para acompanhar essa esteira na prática.").
4. **Legenda Completa (`legenda_completa`)**:
   - A junção fluida de: hook + corpo + cta + hashtags.
   - Total de até 1800 caracteres.
5. **Hashtags Sugeridas (`hashtags_sugeridas`)**:
   - Exatamente 3 a 5 hashtags (1-2 nicho específico, 1-2 médio volume, 1 ampla).
6. **Cenas para Reels (`cenas_reels`)**:
   - Se a ideia for para formato Reel ou vídeo curto, divida o roteiro em 3 a 5 cenas curtas contendo a fala e os termos em inglês para busca no Pexels (`busca_visual`). Caso contrário, deixe como lista vazia `[]`.

Responda SOMENTE com JSON contendo: hook_125, corpo, cta, objetivo, legenda_completa, hashtags_sugeridas, cenas_reels.
""".strip()


class CaptionWriterAgente(BaseAgente):
    """Especialista em redação de legendas com hook de 125 caracteres e CTA por objetivo."""

    nome = "caption_writer"
    descricao = "Redige legendas com gancho nos primeiros 125 caracteres, corpo escaneável e CTA alinhado a meta."
    schema = SCHEMA_CAPTION

    async def redigir(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        ideia_ou_noticia: str,
        objetivo: str = "saves",
        formato: str = "feed",
        estrategia: dict[str, Any] | None = None,
        feedback_critico: str = "",
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Gera a legenda estruturada e textos do card."""
        prompt_user = f"Tema/Ideia do Post:\n{ideia_ou_noticia}\n\n"
        if estrategia:
            prompt_user += (
                f"Estratégia Editorial Definida:\n"
                f"- Formato: {estrategia.get('formato', formato)}\n"
                f"- Objetivo: {estrategia.get('objetivo', objetivo)}\n"
                f"- Ângulo Editorial: {estrategia.get('angulo', '')}\n"
                f"- Fatos Centrais (respeite estritamente): {', '.join(estrategia.get('fatos_centrais', []))}\n"
                f"- Proposta de Valor: {estrategia.get('proposta_de_valor', '')}\n\n"
            )
        else:
            prompt_user += (
                f"Objetivo desejado: {objetivo} (saves, shares, comments, follows)\n"
                f"Formato da postagem: {formato}\n\n"
            )

        if feedback_critico:
            prompt_user += f"Ajuste solicitado pelo Crítico Visual:\n{feedback_critico}\n\n"

        prompt_user += (
            "Gere o JSON com: hook_125, manchete_card (máximo 10 palavras de alto impacto para o card), corpo, "
            "itens_card (2 a 4 pontos objetivos para o layout do card), dado_destaque (número/métrica se houver), "
            "frase_impacto (punchline), cta (específico do tema, NUNCA genérico), objetivo, legenda_completa, "
            "hashtags_sugeridas e cenas_reels."
        )

        dados = await self.executar(
            con=con,
            perfil=perfil,
            mensagem_user=prompt_user,
            instrucoes_agente=INSTR_CAPTION_WRITER,
            temperature=temperature,
        )
        if not dados.get("manchete_card"):
            dados["manchete_card"] = dados.get("hook_125", "")[:80]
        return dados

    def validar(self, dados: dict[str, Any]) -> list[str]:
        erros = super().validar(dados)
        if erros:
            return erros

        hook = str(dados.get("hook_125") or "").strip()
        if len(hook) > 160:
            erros.append(f"hook_125 longo demais ({len(hook)} chars, limite ideal até 125-140)")

        obj = dados.get("objetivo")
        if obj not in ("saves", "shares", "comments", "follows"):
            erros.append("objetivo deve ser saves, shares, comments ou follows")

        tags = dados.get("hashtags_sugeridas")
        if not isinstance(tags, list) or len(tags) < 2:
            erros.append("hashtags_sugeridas deve conter entre 3 e 5 hashtags")

        return erros
