"""Criptografia dos tokens em repouso (Fernet, chave derivada de APP_SECRET_KEY)."""
import base64, hashlib, hmac, os, secrets

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None

from . import config as C

_key: str | None = None


def secret_key() -> str:
    """Chave do app: criada sozinha no primeiro boot em data/secret.key (modo 600). Fazer backup junto do banco."""
    global _key
    if _key is None:
        C.DATA.mkdir(parents=True, exist_ok=True)
        if C.SECRET_FILE.exists():
            _key = C.SECRET_FILE.read_text().strip()
        else:
            _key = secrets.token_urlsafe(48)
            fd = os.open(C.SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(_key)
    return _key


def _fernet():
    if Fernet is None:
        raise RuntimeError("biblioteca cryptography não está instalada neste ambiente")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret_key().encode()).digest()))


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
