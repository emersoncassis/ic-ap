"""SQLite simples. Volume baixo (uso pessoal), então acesso síncrono com lock."""
import sqlite3, threading
from datetime import datetime, timezone

from . import config as C

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS perfis(
  id INTEGER PRIMARY KEY, nome TEXT NOT NULL, handle TEXT DEFAULT '', ativo INTEGER DEFAULT 1,
  ig_user_id TEXT DEFAULT '', ig_token_enc TEXT DEFAULT '', telegram_chat_id TEXT DEFAULT '',
  llm_conexao_id INTEGER, contexto_md TEXT DEFAULT '',
  horarios TEXT DEFAULT '09:00,18:00', musica_modo TEXT NOT NULL DEFAULT 'nenhuma', palavras_chave TEXT DEFAULT '', max_idade_horas INTEGER DEFAULT 36,
  criado_em TEXT);
CREATE TABLE IF NOT EXISTS feeds(
  id INTEGER PRIMARY KEY, perfil_id INTEGER, nome TEXT, url TEXT, tema TEXT DEFAULT '', ativo INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS posts(
  id INTEGER PRIMARY KEY, perfil_id INTEGER NOT NULL, estado TEXT NOT NULL,
  noticia_url TEXT, noticia_titulo TEXT, fonte TEXT, texto TEXT, json_llm TEXT, manchete TEXT, reacao TEXT,
  legenda TEXT, arquivo TEXT, media_id TEXT, erro TEXT, tg_message_id TEXT, criado_em TEXT, atualizado_em TEXT,
  variacao INTEGER NOT NULL DEFAULT 1, grupo INTEGER, agendado_para TEXT, formato TEXT NOT NULL DEFAULT 'feed',
  angulo TEXT DEFAULT '',
  UNIQUE(perfil_id, noticia_url, variacao));
CREATE TABLE IF NOT EXISTS eventos(
  id INTEGER PRIMARY KEY, perfil_id INTEGER, post_id INTEGER, tipo TEXT, detalhe TEXT, criado_em TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS llm_conexoes(
  id INTEGER PRIMARY KEY, nome TEXT NOT NULL, tipo TEXT NOT NULL, base_url TEXT DEFAULT '', api_key_enc TEXT DEFAULT '',
  modelo TEXT DEFAULT '', padrao INTEGER DEFAULT 0, criado_em TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def init() -> None:
    global _conn
    C.DATA.mkdir(parents=True, exist_ok=True)
    C.PUBLIC.mkdir(parents=True, exist_ok=True)
    C.CARDS.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(C.DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.executescript(SCHEMA)
        _migrar()
        _conn.commit()


def _colunas(tabela: str) -> set[str]:
    return {r["name"] for r in _conn.execute(f"PRAGMA table_info({tabela})").fetchall()}


def _migrar() -> None:
    """Bancos criados por versões anteriores: recria posts (nova UNIQUE com variação) e adiciona colunas."""
    if "musica_modo" not in _colunas("perfis"):
        _conn.execute("ALTER TABLE perfis ADD COLUMN musica_modo TEXT NOT NULL DEFAULT 'nenhuma'")
    if "variacao" not in _colunas("posts"):
        antigas = ",".join(sorted(_colunas("posts")))
        _conn.executescript("ALTER TABLE posts RENAME TO posts_old;")
        _conn.executescript(SCHEMA)  # recria posts com o esquema novo
        _conn.execute(f"INSERT INTO posts({antigas}) SELECT {antigas} FROM posts_old")
        _conn.execute("DROP TABLE posts_old")


def q(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict | None:
    r = q(sql, args)
    return r[0] if r else None


def x(sql: str, args: tuple = ()) -> int:
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount


def get_setting(k: str, d: str = "") -> str:
    r = one("SELECT v FROM settings WHERE k=?", (k,))
    return r["v"] if r else d


def set_setting(k: str, v: str) -> None:
    x("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


def log(perfil_id, post_id, tipo: str, detalhe: str = "") -> None:
    x("INSERT INTO eventos(perfil_id,post_id,tipo,detalhe,criado_em) VALUES(?,?,?,?,?)",
      (perfil_id, post_id, tipo, detalhe[:500], now()))
