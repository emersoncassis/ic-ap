"""Configuração global editável pela interface. Segredos ficam criptografados."""
from zoneinfo import ZoneInfo

from . import crypto, db


def base_url() -> str:
    return db.get_setting("public_base_url").rstrip("/")


def tz() -> str:
    return db.get_setting("tz", "America/Sao_Paulo")


def tz_valido(nome: str) -> bool:
    try:
        ZoneInfo(nome)
        return True
    except Exception:
        return False


def segredo(k: str) -> str:
    try:
        return crypto.dec(db.get_setting(k))
    except Exception:
        return ""  # chave trocada/perdida: tratar como não configurado


def guardar_segredo(k: str, v: str) -> None:
    db.set_setting(k, crypto.enc(v) if v else "")


def telegram_token() -> str:
    return segredo("telegram_token")


def tunnel_token() -> str:
    return segredo("tunnel_token")


def pexels_key() -> str:
    return segredo("pexels_key")


def unsplash_key() -> str:
    return segredo("unsplash_key")
