"""Carregador dinâmico de skills a partir de arquivos SKILL.md.

Fonte única de verdade para as instruções e diretrizes dos agentes especialistas.
Recarrega automaticamente quando o arquivo SKILL.md é alterado no disco.
"""
import logging
from pathlib import Path
from typing import Any
import yaml

from .. import config as C

logger = logging.getLogger(__name__)

# Cache: {nome_skill: (mtime, dados_skill)}
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _extrair_frontmatter_e_corpo(conteudo: str) -> tuple[dict[str, Any], str]:
    """Separa o frontmatter YAML delimitado por '---' e o corpo markdown."""
    texto = conteudo.strip()
    if not texto.startswith("---"):
        return {}, texto

    partes = texto.split("---", 2)
    if len(partes) < 3:
        return {}, texto

    raw_yaml = partes[1].strip()
    corpo = partes[2].strip()

    try:
        meta = yaml.safe_load(raw_yaml) or {}
        if not isinstance(meta, dict):
            meta = {}
    except Exception as e:
        logger.warning(f"Erro ao parsear YAML frontmatter: {e}")
        meta = {}

    return meta, corpo


def localizar_arquivo_skill(nome: str) -> Path | None:
    """Procura pelo arquivo SKILL.md correspondente ao nome da skill."""
    dir_skills = C.SKILLS_DIR
    if not dir_skills or not dir_skills.exists():
        return None

    # Variações de nomes: ex: "caption-writer", "caption_writer", pasta direta
    candidatos = [
        dir_skills / nome / "SKILL.md",
        dir_skills / nome.replace("_", "-") / "SKILL.md",
        dir_skills / nome.replace("-", "_") / "SKILL.md",
        dir_skills / f"{nome}.md",
    ]

    for p in candidatos:
        if p.is_file():
            return p

    # Busca recursiva se não encontrar direto
    for p in dir_skills.glob("**/SKILL.md"):
        if p.parent.name.lower() in (nome.lower(), nome.replace("_", "-").lower(), nome.replace("-", "_").lower()):
            return p

    return None


def carregar_skill(nome: str) -> dict[str, Any]:
    """Carrega a skill pelo nome, utilizando cache com invalidação por mtime."""
    caminho = localizar_arquivo_skill(nome)
    if not caminho or not caminho.exists():
        return {
            "nome": nome,
            "descricao": "",
            "metadata": {},
            "instrucoes": "",
            "encontrada": False,
            "caminho": None,
        }

    try:
        mtime_atual = caminho.stat().st_mtime
    except Exception:
        mtime_atual = 0.0

    if nome in _CACHE:
        mtime_cache, dados_cache = _CACHE[nome]
        if mtime_cache == mtime_atual:
            return dados_cache

    try:
        conteudo = caminho.read_text(encoding="utf-8")
        meta, corpo = _extrair_frontmatter_e_corpo(conteudo)
        dados = {
            "nome": meta.get("name", nome),
            "descricao": meta.get("description", "").strip(),
            "metadata": meta,
            "instrucoes": corpo,
            "encontrada": True,
            "caminho": str(caminho),
        }
        _CACHE[nome] = (mtime_atual, dados)
        return dados
    except Exception as e:
        logger.error(f"Erro ao carregar skill '{nome}' de {caminho}: {e}")
        return {
            "nome": nome,
            "descricao": "",
            "metadata": {},
            "instrucoes": "",
            "encontrada": False,
            "caminho": str(caminho),
        }


def obter_prompt_skill(nome: str, padrao: str = "") -> str:
    """Devolve as instruções markdown da skill ou um texto padrão de fallback."""
    skill = carregar_skill(nome)
    if skill.get("encontrada") and skill.get("instrucoes"):
        return skill["instrucoes"].strip()
    return padrao.strip()


obter_skill = carregar_skill



def listar_skills() -> list[dict[str, Any]]:
    """Lista todas as skills disponíveis no diretório de skills."""
    dir_skills = C.SKILLS_DIR
    if not dir_skills or not dir_skills.exists():
        return []

    resultado = []
    for skill_md in sorted(dir_skills.glob("*/SKILL.md")):
        nome_pasta = skill_md.parent.name
        sk = carregar_skill(nome_pasta)
        resultado.append(sk)
    return resultado


listar_skills_disponiveis = listar_skills
