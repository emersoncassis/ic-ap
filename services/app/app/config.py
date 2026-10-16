"""Só caminhos e ganchos técnicos. Toda a configuração do usuário vive no banco e é editada pela interface."""
import os
from pathlib import Path


def env(k: str, d: str = "") -> str:
    return os.getenv(k, d)


DATA = Path(env("DATA_DIR", "/data"))
PUBLIC = DATA / "public"      # servido na porta interna PUBLIC_PORT (e exposto só pelo túnel), apenas no momento do publish
MUSICAS = DATA / "musicas"
FUNDOS = DATA / "fundos"      # imagem de fundo de cada post (foto sua ou do banco de imagens), privada
MARCA = DATA / "marca"        # logotipos dos perfis
CARDS = DATA / "cards"        # cards privados (preview no painel)
DB_PATH = DATA / "app.db"
SECRET_FILE = DATA / "secret.key"
CARD_TEMPLATES = Path(env("TEMPLATES_DIR", "/srv/card-templates"))
CONTEXT_FILE = Path(env("CONTEXT_FILE", "/context/meu_contexto.md"))   # só semente do perfil inicial
FEEDS_FILE = Path(env("FEEDS_FILE", "/config/feeds.yml"))              # só semente dos feeds iniciais
CHROMIUM = env("CHROMIUM_PATH") or None
PUBLIC_PORT = int(env("PUBLIC_PORT", "8081"))
CLOUDFLARED_BIN = env("CLOUDFLARED_BIN", "cloudflared")

# Endpoints de terceiros (sobrescritos nos testes)
IG_BASE = env("IG_GRAPH_BASE") or f"https://graph.facebook.com/{env('IG_GRAPH_VERSION', 'v23.0')}"
IG_POLL_SECONDS = float(env("IG_POLL_SECONDS", "5"))
IG_POLL_TRIES = int(env("IG_POLL_TRIES", "12"))
TICK_SECONDS = float(env("SCHEDULER_TICK", "30"))
TELEGRAM_API = env("TELEGRAM_API_BASE", "https://api.telegram.org")
GEMINI_API_BASE = env("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta")
HIGGS_API_BASE = env("HIGGS_API_BASE", "https://api.higgsfield.ai")
HIGGS_POLL_SECONDS = float(env("HIGGS_POLL_SECONDS", "2"))
UNSPLASH_API_BASE = env("UNSPLASH_API_BASE", "https://api.unsplash.com")
ANTHROPIC_API_BASE = env("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1")
