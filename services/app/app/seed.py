"""Primeira execução: cria a senha do painel e o perfil do Emerson a partir do .env e dos arquivos do repo."""
import os

import yaml

from . import config as C, crypto, db


def run() -> None:
    if not db.get_setting("admin_hash"):
        pw = os.getenv("ADMIN_PASSWORD", "")
        if len(pw) < 8:
            raise RuntimeError("Defina ADMIN_PASSWORD (mínimo 8 caracteres) no .env para o primeiro boot")
        db.set_setting("admin_hash", crypto.hash_password(pw))

    if db.q("SELECT 1 FROM perfis LIMIT 1"):
        return
    contexto = C.CONTEXT_FILE.read_text(encoding="utf-8") if C.CONTEXT_FILE.exists() else ""
    pid = db.x(
        "INSERT INTO perfis(nome,handle,ativo,ig_user_id,ig_token_enc,telegram_chat_id,llm_provider,llm_model,"
        "contexto_md,horarios,palavras_chave,max_idade_horas,criado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (os.getenv("CARD_NAME", "Emerson Assis"), os.getenv("CARD_HANDLE", "@usuario"), 0,
         os.getenv("IG_USER_ID", ""), crypto.enc(os.getenv("IG_ACCESS_TOKEN", "")),
         os.getenv("TELEGRAM_CHAT_ID", ""), os.getenv("LLM_PROVIDER", "ollama"), "",
         contexto, "09:00,18:00", "", 36, db.now()))
    if C.FEEDS_FILE.exists():
        cfg = yaml.safe_load(C.FEEDS_FILE.read_text(encoding="utf-8")) or {}
        for f in cfg.get("feeds", []):
            db.x("INSERT INTO feeds(perfil_id,nome,url,tema,ativo) VALUES(NULL,?,?,?,1)",
                 (f["nome"], f["url"], f.get("tema", "")))
        filt = cfg.get("filtros", {})
        db.x("UPDATE perfis SET palavras_chave=?, max_idade_horas=? WHERE id=?",
             (", ".join(filt.get("palavras_chave", [])), filt.get("max_idade_horas", 36), pid))
    # Perfil nasce DESLIGADO: só liga depois de você revisar contexto, token e conexões.
    db.log(pid, None, "seed", "perfil criado (desligado)")
