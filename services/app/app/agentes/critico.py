"""Agente Crítico Visual: inspeciona o card renderizado com uma rubrica objetiva.

O modelo NÃO dá nota: responde sim/não (com uma justificativa curta) a cinco critérios verificáveis, e a nota de 1 a 10
e a aprovação são calculadas aqui, no código, a partir deles. Dois critérios também são checados pelo motor de renderização
(texto cortado e manchete longa) e a checagem do motor vence a resposta do modelo.
"""
import base64
import logging
from pathlib import Path
from typing import Any

from .base import BaseAgente

logger = logging.getLogger(__name__)

# critério -> (peso na nota, pergunta; ok=true quando a resposta é "sim, está certo"). A soma dos pesos é 10.
CRITERIOS: dict[str, tuple[int, str]] = {
    "texto_cortado": (3, "Todo o texto aparece inteiro, sem ser cortado nem passar das bordas do card?"),
    "contraste": (2, "O contraste entre o texto e o fundo é forte o bastante para ler no celular?"),
    "legibilidade": (2, "O tamanho e a fonte do texto são legíveis, sem sobreposição entre elementos?"),
    "hierarquia": (2, "A manchete se destaca de imediato e a ordem de leitura (manchete, corpo, chamada) é clara?"),
    "safe_zone": (1, "Nada importante está dentro das margens de segurança (story: 220 px no topo e 260 px no rodapé; feed: 60 px)?"),
}
# reprovar qualquer um destes reprova o card, qualquer que seja a nota
ELIMINATORIOS = ("texto_cortado", "contraste", "legibilidade")
NOTA_MINIMA = 8
MAX_PALAVRAS_MANCHETE = 16

_CRITERIO = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "justificativa": {"type": "string"}},
    "required": ["ok", "justificativa"],
}
SCHEMA_CRITICO = {
    "type": "object",
    "properties": {
        "criterios": {"type": "object", "properties": {k: _CRITERIO for k in CRITERIOS}, "required": list(CRITERIOS)},
        "sugestao_ajuste": {"type": "string"},
    },
    "required": ["criterios"],
}


def calcular_nota(criterios: dict[str, dict[str, Any]]) -> tuple[int, bool]:
    """(nota de 1 a 10, aprovado). Nota = soma dos pesos dos critérios que passaram; aprova com nota >= 8 e nenhum eliminatório reprovado."""
    nota = sum(peso for k, (peso, _) in CRITERIOS.items() if criterios[k]["ok"])
    aprovado = nota >= NOTA_MINIMA and all(criterios[k]["ok"] for k in ELIMINATORIOS)
    return max(1, nota), aprovado


def consolidar(criterios: dict[str, dict[str, Any]], estourou_texto: bool = False, palavras_manchete: int = 0,
               sugestao: str = "") -> dict[str, Any]:
    """Junta a resposta do modelo com as checagens do motor e calcula nota, aprovação e a lista de problemas."""
    c = {k: {"ok": bool(criterios[k]["ok"]), "justificativa": str(criterios[k].get("justificativa") or "").strip()} for k in CRITERIOS}
    if estourou_texto:  # medido pelo navegador: vale mais que a opinião do modelo
        c["texto_cortado"] = {"ok": False, "justificativa": "O motor de renderização detectou texto passando do limite do card (overflow)."}
    if palavras_manchete > MAX_PALAVRAS_MANCHETE:
        c["hierarquia"] = {"ok": False, "justificativa": f"Manchete longa demais para o celular ({palavras_manchete} palavras, ideal até 10-12)."}
    nota, aprovado = calcular_nota(c)
    problemas = [f"{k}: {v['justificativa'] or 'reprovado'}" for k, v in c.items() if not v["ok"]]
    return {
        "score": nota,
        "aprovado": aprovado,
        "criterios": c,
        "pontos_fortes": [k for k, v in c.items() if v["ok"]],
        "problemas": problemas,
        "sugestao_ajuste": sugestao.strip() or ("; ".join(problemas) if problemas else "Nenhum ajuste crítico."),
    }


class CriticoAgente(BaseAgente):
    """Agente que avalia o card renderizado antes do envio final."""

    nome = "critico-visual"
    descricao = "Inspeciona o card gerado com uma rubrica de cinco critérios sim/não; a nota é calculada no código."
    schema = SCHEMA_CRITICO

    def validar(self, dados: dict[str, Any]) -> list[str]:
        erros = super().validar(dados)
        if erros:
            return erros
        crit = dados.get("criterios")
        if not isinstance(crit, dict):
            return ["criterios deve ser um objeto com os cinco critérios"]
        for k in CRITERIOS:
            item = crit.get(k)
            if not isinstance(item, dict) or not isinstance(item.get("ok"), bool):
                erros.append(f"critério '{k}' ausente ou sem ok true/false")
            elif not item.get("ok") and not str(item.get("justificativa") or "").strip():
                erros.append(f"critério '{k}' reprovado sem justificativa")
        return erros

    @staticmethod
    def _prompt(pedido, estrategia, layout, manchete, copy, direcao_arte, problemas_motor, layouts_repetidos) -> str:
        prompt = (
            "=== AVALIAÇÃO DO CARD POR RUBRICA ===\n"
            f"Pedido original do autor: {pedido}\n"
            f"Formato: {estrategia.get('formato', 'feed')}\n"
            f"Layout escolhido: {layout}\n"
            f"Manchete: {manchete}\n"
            f"CTA: {copy.get('cta', '')}\n"
            f"Paleta de Cores: {direcao_arte.get('paleta', {})}\n"
        )
        if problemas_motor:
            prompt += "\nProblemas já medidos pelo motor de renderização (considere-os):\n" + "\n".join(f"- {p}" for p in problemas_motor) + "\n"
        if layouts_repetidos:
            prompt += f"\nObservação: o layout '{layout}' repetiu nos últimos posts (informe na sugestão de ajuste, não reprove por isso).\n"
        prompt += "\nOlhe a imagem anexa (ou os parâmetros acima, se não houver imagem) e responda cada pergunta com ok=true (sim) ou ok=false (não):\n"
        prompt += "\n".join(f"- {k}: {pergunta}" for k, (_, pergunta) in CRITERIOS.items())
        prompt += (
            "\n\nResponda SOMENTE com JSON: {\"criterios\": {\"texto_cortado\": {\"ok\": true, \"justificativa\": \"...\"}, ...os cinco critérios...}, "
            "\"sugestao_ajuste\": \"ajuste cirúrgico se algum for false\"}. "
            "A justificativa tem uma frase curta e é obrigatória quando ok=false. Não dê nota: ela é calculada depois."
        )
        return prompt

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
        """Avalia o card gerado. Tenta a inspeção visual por LLM multimodal e combina com as checagens do motor."""
        manchete = copy.get("manchete_card") or copy.get("hook_125", "")
        layout_usado = direcao_arte.get("layout", "editorial")
        palavras_manchete = len(manchete.split())

        problemas_motor: list[str] = []
        if estourou_texto:
            problemas_motor.append("O texto do card ultrapassou a altura limite do container visual (overflow).")
        if palavras_manchete > MAX_PALAVRAS_MANCHETE:
            problemas_motor.append(f"Manchete longa demais para visual mobile ({palavras_manchete} palavras, ideal até 10-12).")
        layouts_repetidos = bool(layouts_recentes and len(layouts_recentes) >= 2 and all(x == layout_usado for x in layouts_recentes[:2]))

        imagem_b64 = None
        if caminho_card.exists():
            try:
                imagem_b64 = base64.b64encode(caminho_card.read_bytes()).decode("ascii")
            except Exception as e:
                logger.warning(f"Não foi possível ler JPEG do card para visão: {e}")

        prompt = self._prompt(pedido, estrategia, layout_usado, manchete, copy, direcao_arte, problemas_motor, layouts_repetidos)

        resposta, usou_visao = None, False
        if imagem_b64:
            try:
                resposta = await self.executar(con=con, perfil=perfil, mensagem_user=prompt, imagem=imagem_b64, temperature=0.3, max_tentativas=2)
                usou_visao = True
            except Exception as e:
                logger.info(f"Modelo sem suporte a visão ou erro na chamada multimodal ({e}). Usando avaliação textual/objetiva.")
        if not resposta:
            try:
                resposta = await self.executar(con=con, perfil=perfil, mensagem_user=prompt, temperature=0.3, max_tentativas=2)
            except Exception:
                resposta = None

        if resposta:
            resultado = consolidar(resposta["criterios"], estourou_texto, palavras_manchete, str(resposta.get("sugestao_ajuste") or ""))
        else:
            # sem resposta do LLM: só valem as checagens do motor; o resto fica como "não avaliado" (aprovado)
            sem_llm = {k: {"ok": True, "justificativa": "não avaliado: o modelo não respondeu"} for k in CRITERIOS}
            resultado = consolidar(sem_llm, estourou_texto, palavras_manchete)
        resultado["usou_visao"] = usou_visao
        return resultado
