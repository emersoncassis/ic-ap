"""Primeira execução: cria o perfil inicial do Emerson (desligado) a partir dos arquivos de exemplo do repo."""
import yaml

from . import config as C, db


def run() -> None:
    if db.q("SELECT 1 FROM perfis LIMIT 1"):
        return
    contexto = C.CONTEXT_FILE.read_text(encoding="utf-8") if C.CONTEXT_FILE.exists() else ""
    pid = db.x("INSERT INTO perfis(nome,handle,ativo,contexto_md,horarios,palavras_chave,max_idade_horas,criado_em)"
               " VALUES(?,?,?,?,?,?,?,?)", ("Emerson Assis", "", 0, contexto, "09:00,18:00", "", 36, db.now()))
    if C.FEEDS_FILE.exists():
        cfg = yaml.safe_load(C.FEEDS_FILE.read_text(encoding="utf-8")) or {}
        for f in cfg.get("feeds", []):
            db.x("INSERT INTO feeds(perfil_id,nome,url,tema,ativo) VALUES(NULL,?,?,?,1)",
                 (f["nome"], f["url"], f.get("tema", "")))
        filt = cfg.get("filtros", {})
        db.x("UPDATE perfis SET palavras_chave=?, max_idade_horas=? WHERE id=?",
             (", ".join(filt.get("palavras_chave", [])), filt.get("max_idade_horas", 36), pid))
    # Perfil nasce DESLIGADO: só liga depois de revisar contexto, token e conexões.
    db.log(pid, None, "seed", "perfil criado (desligado)")
