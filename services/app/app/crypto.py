"""Criptografia dos tokens em repouso (Fernet, chave derivada de APP_SECRET_KEY)."""
import base64, hashlib, hmac, os, secrets

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    key = os.environ.get("APP_SECRET_KEY", "")
    if len(key) < 16:
        raise RuntimeError("APP_SECRET_KEY ausente ou curta (mínimo 16 caracteres)")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def enc(s: str) -> str:
    return _fernet().encrypt(s.encode()).decode() if s else ""


def dec(s: str) -> str:
    return _fernet().decrypt(s.encode()).decode() if s else ""


def mask(s: str) -> str:
    return ("••••••••" + s[-4:]) if s and len(s) > 8 else ("••••" if s else "")


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + "$" + h.hex()


def check_password(pw: str, stored: str) -> bool:
    try:
        salt_hex, h_hex = stored.split("$")
        h = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(h.hex(), h_hex)
    except Exception:
        return False
