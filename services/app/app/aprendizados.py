"""Loop de Aprendizado Contínuo de Conteúdo (Padrão Viraloop).

Armazena o histórico de desempenho real dos posts e ganchos (salvamentos, retenção,
compartilhamentos) no SQLite (tabela `aprendizados`) e retroalimenta automaticamente
os Agentes Especialistas (Caption Writer, Carousel Planner, Content Planner) para que
o sistema fique progressivamente mais calibrado ao público real do perfil.
"""
import logging
from typing import Any

from . import db

logger = logging.getLogger(__name__)


def init_tabela() -> None:
    """Garante a existência da tabela de aprendizados."""
    db.x("""
    CREATE TABLE IF NOT EXISTS aprendizados(
      id INTEGER PRIMARY KEY,
      perfil_id INTEGER NOT NULL,
      post_id INTEGER,
      hook TEXT DEFAULT '',
      formato TEXT DEFAULT 'feed',
      angulo TEXT DEFAULT '',
      alcance INTEGER DEFAULT 0,
      salvamentos INTEGER DEFAULT 0,
      compartilhamentos INTEGER DEFAULT 0,
      comentarios INTEGER DEFAULT 0,
      score_retencao REAL DEFAULT 0.0,
      licao_aprendida TEXT DEFAULT '',
      criado_em TEXT
    )
    """)


def registrar(
    perfil_id: int,
    post_id: int | None = None,
    hook: str = "",
    formato: str = "feed",
    angulo: str = "",
    metricas: dict[str, Any] | None = None,
    licao: str = "",
) -> int:
    """Registra uma observação de performance ou aprendizado de conteúdo."""
    init_tabela()
    m = metricas or {}
    alcance = int(m.get("alcance") or m.get("reach") or 0)
    salvamentos = int(m.get("salvamentos") or m.get("saved") or 0)
    compartilhamentos = int(m.get("compartilhamentos") or m.get("shares") or 0)
    comentarios = int(m.get("comentarios") or m.get("comments") or 0)

    # Score de engajamento profundo (salvamento e share valem 3x mais que like para o algoritmo 2026)
    score = float((salvamentos * 3.0) + (compartilhamentos * 2.5) + (comentarios * 1.5))

    return db.x(
        "INSERT INTO aprendizados(perfil_id, post_id, hook, formato, angulo, alcance, salvamentos, compartilhamentos, comentarios, score_retencao, licao_aprendida, criado_em)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (perfil_id, post_id, hook[:200], formato, angulo[:100], alcance, salvamentos, compartilhamentos, comentarios, score, licao[:400], db.now()),
    )


def listar(perfil_id: int, limite: int = 15) -> list[dict[str, Any]]:
    """Lista os aprendizados mais recentes do perfil."""
    init_tabela()
    return db.q("SELECT * FROM aprendizados WHERE perfil_id=? ORDER BY score_retencao DESC, id DESC LIMIT ?", (perfil_id, limite))


def sintetizar_aprendizados(perfil_id: int) -> str:
    """Gera um bloco de síntese para injeção automática no System Prompt dos Agentes."""
    itens = listar(perfil_id, limite=8)
    if not itens:
        return ""

    linhas = ["--- APRENDIZADOS DE ALTA PERFORMANCE DO SEU PERFIL (VIRALOOP) ---"]
    for it in itens:
        partes = []
        if it.get("hook"):
            partes.append(f'Hook vencedor: "{it["hook"]}"')
        if it.get("formato"):
            partes.append(f"Formato: {it['formato']}")
        if it.get("licao_aprendida"):
            partes.append(f"Lição: {it['licao_aprendida']}")
        elif it.get("salvamentos"):
            partes.append(f"Salvamentos: {it['salvamentos']}, Shares: {it['compartilhamentos']}")

        if partes:
            linhas.append(f"• {' | '.join(partes)}")

    linhas.append("Priorize esses padrões vencedores de gancho e formato nas novas propostas.")
    return "\n".join(linhas)
