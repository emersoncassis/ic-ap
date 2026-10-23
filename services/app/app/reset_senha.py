"""Redefine a senha do painel: docker compose exec app python -m app.reset_senha"""
import getpass, sys

from . import crypto, db


def main() -> None:
    db.init()
    a, b = getpass.getpass("Nova senha: "), getpass.getpass("Repita: ")
    if a != b or len(a) < 8:
        sys.exit("As senhas não conferem ou têm menos de 8 caracteres.")
    db.set_setting("admin_hash", crypto.hash_password(a))
    print("Senha alterada.")


if __name__ == "__main__":
    main()
