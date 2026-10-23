"""Classe base para todos os Agentes Especialistas de Conteúdo do ic-ap."""
import json
import logging
from typing import Any

from .. import llm

logger = logging.getLogger(__name__)

DIRETRIZES_PT_BR_2026 = """
Diretrizes Culturais e de Qualidade (Português do Brasil - 2026):
1. Linguagem natural, direta, inteligente e sem rodeios.
2. NUNCA use frases clichês de IA (ex.: "no mundo dinâmico de hoje", "mergulhe fundo", "é crucial entender", "game changer", "divisor de águas", "desvende").
3. Sem falsa sinceridade, sem tempestades de emojis (máximo 1 a 3 emojis no texto inteiro quando pertinente; nunca como marcadores de lista em cada linha).
4. Controle de travessão: no máximo 1 travessão a cada 100 palavras.
5. Respeite estritamente o tom, as crenças e o vocabulário descritos no perfil do autor.
6. Nunca invente fatos, métricas ou histórias que não constem na ideia ou no contexto do perfil.
""".strip()


class BaseAgente:
    """Classe base que gerencia contexto, chamadas ao LLM e validação de schema."""

    nome: str = "base"
    descricao: str = "Agente Base"
    schema: dict[str, Any] = {}

    def montar_system(self, perfil: dict[str, Any], instrucoes_agente: str) -> str:
        """Monta o system prompt injetando contexto do perfil e diretrizes culturais."""
        contexto_autor = (perfil.get("contexto_md") or "").strip()
        nome_autor = perfil.get("nome") or "Autor"
        palavras = perfil.get("palavras_chave") or ""

        bloco_perfil = f"Você atua no perfil de: {nome_autor}.\n"
        if contexto_autor:
            bloco_perfil += f"\n=== CONTEXTO E TOM DE VOZ DO AUTOR ===\n{contexto_autor}\n"
        if palavras:
            bloco_perfil += f"\nTemas centrais do perfil: {palavras}\n"

        if perfil.get("id"):
            try:
                from .. import aprendizados
                sintese = aprendizados.sintetizar_aprendizados(int(perfil["id"]))
                if sintese:
                    bloco_perfil += f"\n{sintese}\n"
            except Exception:
                pass

        from .skills import obter_prompt_skill
        prompt_skill = obter_prompt_skill(self.nome, padrao="") if self.nome else ""
        if prompt_skill and instrucoes_agente and prompt_skill.strip() != instrucoes_agente.strip():
            instrucoes_finais = f"{prompt_skill.strip()}\n\n=== CONTRATO DE EXECUÇÃO E FORMATO JSON ===\n{instrucoes_agente.strip()}"
        else:
            instrucoes_finais = prompt_skill or instrucoes_agente

        return f"{bloco_perfil}\n=== REGRAS DE ESTILO E LINGUAGEM ===\n{DIRETRIZES_PT_BR_2026}\n\n=== SUA FUNÇÃO COMO AGENTE ({self.nome.upper()}) ===\n{instrucoes_finais.strip()}"

    async def executar(
        self,
        con: dict[str, Any],
        perfil: dict[str, Any],
        mensagem_user: str,
        instrucoes_agente: str = "",
        temperature: float = 0.7,
        max_tentativas: int = 3,
        historico: list[dict[str, Any]] | None = None,
        imagem: str | None = None,
    ) -> dict[str, Any]:
        """Executa a chamada ao LLM com retry automático e validação de schema."""
        system_prompt = self.montar_system(perfil, instrucoes_agente)
        ultimo_erro = ""

        for tentativa in range(1, max_tentativas + 1):
            feedback = f"\n\nAviso: A tentativa anterior falhou ({ultimo_erro}). Corrija e retorne SOMENTE o JSON válido." if ultimo_erro else ""
            user_prompt = f"{mensagem_user}{feedback}"

            try:
                raw = await llm._chat(
                    con=con,
                    system=system_prompt,
                    user=user_prompt,
                    temperature=temperature,
                    schema=self.schema or None,
                    historico=historico,
                    imagem=imagem,
                )
                dados = llm.parse(raw)
                erros = self.validar(dados)
                if erros:
                    raise ValueError("; ".join(erros))
                return dados
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                ultimo_erro = str(e)
                logger.warning(f"[{self.nome}] Tentativa {tentativa}/{max_tentativas} falhou: {ultimo_erro}")
            except llm.LLMError:
                # Erro de rede ou chave de API não deve ser mascarado por loop de retry
                raise

        raise ValueError(f"O agente {self.nome} não conseguiu gerar resposta válida após {max_tentativas} tentativas ({ultimo_erro})")

    def validar(self, dados: dict[str, Any]) -> list[str]:
        """Validação customizável de campos. Deve ser sobrescrita pelas subclasses se necessário."""
        erros: list[str] = []
        if not isinstance(dados, dict):
            return ["resposta não é um objeto JSON"]
        
        # Validação básica contra required no schema se presente
        obrigatorios = (self.schema.get("required") or []) if isinstance(self.schema, dict) else []
        for campo in obrigatorios:
            if campo not in dados or dados[campo] is None:
                erros.append(f"campo '{campo}' ausente")
            elif isinstance(dados[campo], str) and not dados[campo].strip():
                erros.append(f"campo '{campo}' vazio")
        return erros
