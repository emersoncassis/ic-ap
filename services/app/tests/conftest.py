import glob, os, socket, stat, tempfile, threading, time
from pathlib import Path

import httpx
import pytest
import uvicorn

REPO = Path(__file__).resolve().parents[3]
TMP = Path(tempfile.mkdtemp(prefix="icap-test-"))


def _porta() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


PORTA, PUBLIC_PORT = _porta(), _porta()
FAKE = f"http://127.0.0.1:{PORTA}"
PUBLIC_URL = f"http://127.0.0.1:{PUBLIC_PORT}"
(TMP / "feeds.yml").write_text(f"""feeds:
  - {{nome: Feed Teste, url: "{FAKE}/feed.xml", tema: ia}}
filtros:
  palavras_chave: [IA]
  max_idade_horas: 36
""")
# cloudflared de mentira: imprime o log de "conectado" e o token (para provar que o app mascara)
(TMP / "cloudflared").write_text('#!/bin/sh\necho "INF Registered tunnel connection connIndex=0 token=$TUNNEL_TOKEN"\nexec sleep 600\n')
(TMP / "cloudflared").chmod(0o755)
chrome = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")
# Nenhuma configuração de usuário via ambiente: só caminhos e endereços de serviços simulados.
os.environ.update({
    "DATA_DIR": str(TMP / "data"), "TEMPLATES_DIR": str(REPO / "templates"),
    "CONTEXT_FILE": str(REPO / "context" / "meu_contexto.md"), "FEEDS_FILE": str(TMP / "feeds.yml"),
    "PUBLIC_PORT": str(PUBLIC_PORT), "CLOUDFLARED_BIN": str(TMP / "cloudflared"),
    "IG_GRAPH_BASE": f"{FAKE}/graph", "IG_POLL_SECONDS": "0.1", "TELEGRAM_API_BASE": FAKE,
    "GEMINI_API_BASE": f"{FAKE}/gemini", "ANTHROPIC_API_BASE": f"{FAKE}/anthropic",
    "CHROMIUM_PATH": chrome[0] if chrome else "",
})


@pytest.fixture(scope="session", autouse=True)
def fake_server():
    from tests.fake_services import make
    srv = uvicorn.Server(uvicorn.Config(make(PORTA), host="127.0.0.1", port=PORTA, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(50):
        try:
            httpx.get(f"{FAKE}/_st"); break
        except Exception:
            time.sleep(0.1)
    yield
    srv.should_exit = True


@pytest.fixture(scope="session")
def client(fake_server):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture
def fake():
    httpx.post(f"{FAKE}/_reset")
    class F:
        def st(self): return httpx.get(f"{FAKE}/_st").json()
        def set(self, **kw): httpx.post(f"{FAKE}/_set", json=kw)
        def push(self, data, chat_id): httpx.post(f"{FAKE}/_tg/push", json={"data": data, "chat_id": chat_id})
    return F()


def esperar(cond, tempo=40):
    fim = time.time() + tempo
    while time.time() < fim:
        v = cond()
        if v:
            return v
        time.sleep(0.2)
    raise AssertionError("tempo esgotado esperando a condição")
