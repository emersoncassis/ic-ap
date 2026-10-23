"""SQLite simples. Volume baixo (uso pessoal), então acesso síncrono com lock."""
import sqlite3, threading
from typing import Any
from datetime import datetime, timezone

from . import config as C

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS perfis(
  id INTEGER PRIMARY KEY, nome TEXT NOT NULL, handle TEXT DEFAULT '', ativo INTEGER DEFAULT 1,
  ig_user_id TEXT DEFAULT '', ig_token_enc TEXT DEFAULT '', telegram_chat_id TEXT DEFAULT '',
  llm_conexao_id INTEGER, contexto_md TEXT DEFAULT '',
  horarios TEXT DEFAULT '09:00,18:00', musica_modo TEXT NOT NULL DEFAULT 'nenhuma', marca TEXT NOT NULL DEFAULT '', esteira TEXT NOT NULL DEFAULT 'reel', palavras_chave TEXT DEFAULT '', max_idade_horas INTEGER DEFAULT 36,
  meta_ai_analise TEXT DEFAULT '',
  criado_em TEXT);
CREATE TABLE IF NOT EXISTS feeds(
  id INTEGER PRIMARY KEY, perfil_id INTEGER, nome TEXT, url TEXT, tema TEXT DEFAULT '', ativo INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS posts(
  id INTEGER PRIMARY KEY, perfil_id INTEGER NOT NULL, estado TEXT NOT NULL,
  noticia_url TEXT, noticia_titulo TEXT, fonte TEXT, texto TEXT, json_llm TEXT, manchete TEXT, reacao TEXT,
  legenda TEXT, arquivo TEXT, media_id TEXT, erro TEXT, tg_message_id TEXT, criado_em TEXT, atualizado_em TEXT,
  variacao INTEGER NOT NULL DEFAULT 1, grupo INTEGER, agendado_para TEXT, formato TEXT NOT NULL DEFAULT 'feed',
  angulo TEXT DEFAULT '', arquivos TEXT NOT NULL DEFAULT '', mencoes TEXT NOT NULL DEFAULT '', capa TEXT NOT NULL DEFAULT '',
  UNIQUE(perfil_id, noticia_url, variacao));
CREATE TABLE IF NOT EXISTS eventos(
  id INTEGER PRIMARY KEY, perfil_id INTEGER, post_id INTEGER, tipo TEXT, detalhe TEXT, criado_em TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS conversas(
  id INTEGER PRIMARY KEY, chat_id TEXT NOT NULL, papel TEXT NOT NULL, texto TEXT NOT NULL, criado_em TEXT);
CREATE TABLE IF NOT EXISTS llm_conexoes(
  id INTEGER PRIMARY KEY, nome TEXT NOT NULL, tipo TEXT NOT NULL, base_url TEXT DEFAULT '', api_key_enc TEXT DEFAULT '',
  modelo TEXT DEFAULT '', padrao INTEGER DEFAULT 0, criado_em TEXT);
CREATE TABLE IF NOT EXISTS canais_distribuicao(
  id INTEGER PRIMARY KEY, perfil_id INTEGER NOT NULL, canal TEXT NOT NULL, ativo INTEGER DEFAULT 1,
  identificador TEXT DEFAULT '', token_enc TEXT DEFAULT '', extra_json TEXT DEFAULT '{}',
  criado_em TEXT, atualizado_em TEXT,
  UNIQUE(perfil_id, canal));
CREATE TABLE IF NOT EXISTS publicacoes_canais(
  id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL, canal TEXT NOT NULL, status TEXT NOT NULL,
  external_id TEXT DEFAULT '', detalhe TEXT DEFAULT '', criado_em TEXT);
CREATE TABLE IF NOT EXISTS aprendizados(
  id INTEGER PRIMARY KEY, perfil_id INTEGER NOT NULL, post_id INTEGER, hook TEXT DEFAULT '',
  formato TEXT DEFAULT 'feed', angulo TEXT DEFAULT '', alcance INTEGER DEFAULT 0,
  salvamentos INTEGER DEFAULT 0, compartilhamentos INTEGER DEFAULT 0, comentarios INTEGER DEFAULT 0,
  score_retencao REAL DEFAULT 0.0, licao_aprendida TEXT DEFAULT '', criado_em TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def init() -> None:
    """Abre o banco e garante o esquema. Idempotente: chamar de novo reaproveita a conexão aberta
    (antes cada chamada abria uma conexão nova e deixava a anterior pendurada, travando o SQLite)."""
    global _conn
    C.DATA.mkdir(parents=True, exist_ok=True)
    C.PUBLIC.mkdir(parents=True, exist_ok=True)
    C.CARDS.mkdir(parents=True, exist_ok=True)
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(C.DB_PATH, check_same_thread=False, timeout=30)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA busy_timeout=30000")
        _conn.executescript(SCHEMA)
        _migrar()
        _conn.commit()


def _colunas(tabela: str) -> set[str]:
    return {r["name"] for r in _conn.execute(f"PRAGMA table_info({tabela})").fetchall()}


def _migrar() -> None:
    """Bancos criados por versões anteriores: recria posts (nova UNIQUE com variação) e adiciona colunas."""
    if "musica_modo" not in _colunas("perfis"):
        _conn.execute("ALTER TABLE perfis ADD COLUMN musica_modo TEXT NOT NULL DEFAULT 'nenhuma'")
    if "esteira" not in _colunas("perfis"):
        _conn.execute("ALTER TABLE perfis ADD COLUMN esteira TEXT NOT NULL DEFAULT 'reel'")
    if "marca" not in _colunas("perfis"):
        _conn.execute("ALTER TABLE perfis ADD COLUMN marca TEXT NOT NULL DEFAULT ''")
    if "meta_ai_analise" not in _colunas("perfis"):
        _conn.execute("ALTER TABLE perfis ADD COLUMN meta_ai_analise TEXT NOT NULL DEFAULT ''")
    if "variacao" not in _colunas("posts"):
        antigas = ",".join(sorted(_colunas("posts")))
        _conn.executescript("ALTER TABLE posts RENAME TO posts_old;")
        _conn.executescript(SCHEMA)  # recria posts com o esquema novo
        _conn.execute(f"INSERT INTO posts({antigas}) SELECT {antigas} FROM posts_old")
        _conn.execute("DROP TABLE posts_old")
    else:
        for col in ("arquivos", "mencoes", "capa"):
            if col not in _colunas("posts"):
                _conn.execute(f"ALTER TABLE posts ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
    _conn.execute("""
    CREATE TABLE IF NOT EXISTS canais_distribuicao(
      id INTEGER PRIMARY KEY, perfil_id INTEGER NOT NULL, canal TEXT NOT NULL, ativo INTEGER DEFAULT 1,
      identificador TEXT DEFAULT '', token_enc TEXT DEFAULT '', extra_json TEXT DEFAULT '{}',
      criado_em TEXT, atualizado_em TEXT,
      UNIQUE(perfil_id, canal))
    """)
    _conn.execute("""
    CREATE TABLE IF NOT EXISTS publicacoes_canais(
      id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL, canal TEXT NOT NULL, status TEXT NOT NULL,
      external_id TEXT DEFAULT '', detalhe TEXT DEFAULT '', criado_em TEXT)
    """)
    _conn.execute("""
    CREATE TABLE IF NOT EXISTS aprendizados(
      id INTEGER PRIMARY KEY, perfil_id INTEGER NOT NULL, post_id INTEGER, hook TEXT DEFAULT '',
      formato TEXT DEFAULT 'feed', angulo TEXT DEFAULT '', alcance INTEGER DEFAULT 0,
      salvamentos INTEGER DEFAULT 0, compartilhamentos INTEGER DEFAULT 0, comentarios INTEGER DEFAULT 0,
      score_retencao REAL DEFAULT 0.0, licao_aprendida TEXT DEFAULT '', criado_em TEXT)
    """)
    _conn.execute("""
    CREATE TABLE IF NOT EXISTS llm_conexoes(
      id INTEGER PRIMARY KEY, nome TEXT NOT NULL, tipo TEXT NOT NULL, base_url TEXT DEFAULT '',
      api_key_enc TEXT DEFAULT '', modelo TEXT DEFAULT '', padrao INTEGER DEFAULT 0, criado_em TEXT)
    """)
    _conn.execute("DELETE FROM llm_conexoes WHERE tipo IN ('omniroute', 'freellmapi')")
    if "llm_conexao_id" in _colunas("perfis"):
        _conn.execute("UPDATE perfis SET llm_conexao_id=NULL WHERE llm_conexao_id NOT IN (SELECT id FROM llm_conexoes)")


def q(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict | None:
    r = q(sql, args)
    return r[0] if r else None


um = one


def x(sql: str, args: tuple = ()) -> int:
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount


def get_setting(k: str, d: str = "") -> str:
    r = one("SELECT v FROM settings WHERE k=?", (k,))
    return r["v"] if r else d

def valor(sql: str, args: tuple = ()) -> Any:
    """Execute a query and return the first column of the first row, or None.
    This mirrors the historic `db.valor` helper that was missing after refactor.
    """
    r = one(sql, args)
    if r:
        # Return the first value in the row dict
        return next(iter(r.values()))
    return None


def set_setting(k: str, v: str) -> None:
    x("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


def log(perfil_id, post_id, tipo: str, detalhe: str = "") -> None:
    x("INSERT INTO eventos(perfil_id,post_id,tipo,detalhe,criado_em) VALUES(?,?,?,?,?)",
      (perfil_id, post_id, tipo, detalhe[:500], now()))
