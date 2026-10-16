"""Configuração lida do ambiente (.env)."""
import os
from pathlib import Path


def env(k: str, d: str = "") -> str:
    return os.getenv(k, d)


DATA = Path(env("DATA_DIR", "/data"))
PUBLIC = DATA / "public"      # servido pelo nginx/túnel, só no momento do publish
CARDS = DATA / "cards"        # cards privados (preview no painel)
DB_PATH = DATA / "app.db"
CARD_TEMPLATES = Path(env("TEMPLATES_DIR", "/srv/card-templates"))
CONTEXT_FILE = Path(env("CONTEXT_FILE", "/context/meu_contexto.md"))
FEEDS_FILE = Path(env("FEEDS_FILE", "/config/feeds.yml"))
BASE_URL = env("PUBLIC_BASE_URL").rstrip("/")
TZ = env("TZ", "America/Sao_Paulo")
CHROMIUM = env("CHROMIUM_PATH") or None

OLLAMA_URL = env("OLLAMA_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = env("OLLAMA_MODEL", "qwen2.5:7b-instruct")
GEMINI_API_BASE = env("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta")
ANTHROPIC_API_BASE = env("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1")

IG_BASE = env("IG_GRAPH_BASE") or (
    f"https://{env('IG_API_HOST', 'graph.facebook.com')}/{env('IG_GRAPH_VERSION', 'v23.0')}")
IG_POLL_SECONDS = float(env("IG_POLL_SECONDS", "5"))
IG_POLL_TRIES = int(env("IG_POLL_TRIES", "12"))

TELEGRAM_API = env("TELEGRAM_API_BASE", "https://api.telegram.org")
TELEGRAM_TOKEN = env("TELEGRAM_BOT_TOKEN")
