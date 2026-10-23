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


def bancos_abertos() -> bool:
    """Liga/desliga o plano B de imagens SEM chave (Bing, Wikimedia, Wallhaven, Picsum, Pollinations).
    Ligado por padrão. As imagens vêm de terceiros e podem ter direitos autorais: desligue para usar só Higgsfield/Unsplash/sua foto."""
    return db.get_setting("bancos_abertos", "1") != "0"


def unsplash_key() -> str:
    return segredo("unsplash_key")


def meta_ai_cookies() -> str:
    return segredo("meta_ai_cookies")


def guardar_meta_ai_cookies(v: str) -> None:
    guardar_segredo("meta_ai_cookies", v)
