import glob, os, socket, sys, tempfile, threading, time
from pathlib import Path

import httpx
import pytest
try:
    import uvicorn
except ImportError:
    uvicorn = None

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
(TMP / "cloudflared_fake.py").write_text(
    'import os, sys, time\n'
    'print("INF Registered tunnel connection connIndex=0 token=" + os.environ.get("TUNNEL_TOKEN", ""), flush=True)\n'
    'time.sleep(120)\n')
if os.name == "nt":  # o app executa CLOUDFLARED_BIN direto: no Windows o executável é um .bat que chama o Python do teste
    FAKE_CLOUDFLARED = TMP / "cloudflared.bat"
    FAKE_CLOUDFLARED.write_text(f'@"{sys.executable}" "{TMP / "cloudflared_fake.py"}" %*\r\n')
else:
    FAKE_CLOUDFLARED = TMP / "cloudflared"
    FAKE_CLOUDFLARED.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{TMP / "cloudflared_fake.py"}" "$@"\n')
    FAKE_CLOUDFLARED.chmod(0o755)
# mídias de teste geradas com ffmpeg (o que o "usuário" manda pelo Telegram)
MEDIA = TMP / "media"; MEDIA.mkdir()
def _ff(*a):
    import subprocess; subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)
_ff("-f", "lavfi", "-i", "testsrc=size=800x600:rate=1", "-frames:v", "1", str(MEDIA / "foto.jpg"))
_ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(MEDIA / "video.mp4"))
_ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(MEDIA / "mudo.mp4"))
_ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=4", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
    "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-filter_complex", "[2:a]atrim=duration=2[s];[1:a][s][3:a]concat=n=3:v=0:a=1[a]",
    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "4", str(MEDIA / "silencio.mp4"))
_ff("-f", "lavfi", "-i", "sine=frequency=220:duration=2", "-c:a", "libmp3lame", str(MEDIA / "trilha.mp3"))
chrome = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")
# Nenhuma configuração de usuário via ambiente: só caminhos e endereços de serviços simulados.
os.environ.update({
    "DATA_DIR": str(TMP / "data"), "FAKE_MEDIA_DIR": str(MEDIA), "TEMPLATES_DIR": str(REPO / "templates"),
    "CONTEXT_FILE": str(REPO / "context" / "meu_contexto.md"), "FEEDS_FILE": str(TMP / "feeds.yml"),
    "PUBLIC_PORT": str(PUBLIC_PORT), "CLOUDFLARED_BIN": str(FAKE_CLOUDFLARED),
    "IG_GRAPH_BASE": f"{FAKE}/graph", "IG_POLL_SECONDS": "0.1", "SCHEDULER_TICK": "1", "TELEGRAM_API_BASE": FAKE,
    "GEMINI_API_BASE": f"{FAKE}/gemini", "HIGGS_API_BASE": f"{FAKE}/higgs", "HIGGS_POLL_SECONDS": "0.1", "UNSPLASH_API_BASE": f"{FAKE}/unsplash", "ANTHROPIC_API_BASE": f"{FAKE}/anthropic",
    "CHROMIUM_PATH": chrome[0] if chrome else "",
})


@pytest.fixture(scope="session", autouse=True)
def fake_server():
    if uvicorn is None:
        yield
        return
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
def estado_isolado():
    """Para testes unitários que assumem um banco "virgem" de LLM/configuração (o banco é um só para a sessão inteira
    e os testes de fluxo deixam conexões e chaves nele). Guarda o estado, limpa, e restaura ao final."""
    from app import db, telegram
    db.init()
    conexoes, ajustes = db.q("SELECT * FROM llm_conexoes"), db.q("SELECT * FROM settings")
    db.x("DELETE FROM llm_conexoes")
    db.x("DELETE FROM settings WHERE k='ultimo_chat_tg'")  # chat "detectado" pelo polling de outro teste
    telegram._ultimo_chat_detectado = None
    yield
    db.x("DELETE FROM llm_conexoes")
    for r in conexoes:
        db.x(f"INSERT INTO llm_conexoes({','.join(r)}) VALUES({','.join('?' * len(r))})", tuple(r.values()))
    db.x("DELETE FROM settings")
    for r in ajustes:
        db.x("INSERT INTO settings(k,v) VALUES(?,?)", (r["k"], r["v"]))
    telegram._ultimo_chat_detectado = None


@pytest.fixture
def api_client(client):
    """Cliente compartilhado para testes que trocam a senha do painel: restaura a senha original no fim.
    (Subir um segundo app no mesmo processo derrubava o cliente da sessão e travava o SQLite.)"""
    from app import db
    original = db.get_setting("admin_hash")
    yield client
    if original:
        db.set_setting("admin_hash", original)
    client.cookies.clear()


@pytest.fixture
def fake():
    httpx.post(f"{FAKE}/_reset")
    from app import db
    db.set_setting("whisper_local", "0")  # sem servidor configurado, os testes antigos esperam "sem transcrição"
    db.set_setting("bancos_abertos", "0")  # nenhum teste pode depender da internet real (Bing/Wikimedia/...)
    db.x("UPDATE perfis SET esteira='off'")  # os testes antigos cobrem o fluxo manual; a esteira tem testes próprios
    class F:
        def st(self): return httpx.get(f"{FAKE}/_st").json()
        def set(self, **kw): httpx.post(f"{FAKE}/_set", json=kw)
        def push_msg(self, chat_id, tipo, caption='', **kw): httpx.post(f"{FAKE}/_tg/push_msg", json={"chat_id": chat_id, "tipo": tipo, "caption": caption, **kw})
        def push(self, data, chat_id): httpx.post(f"{FAKE}/_tg/push", json={"data": data, "chat_id": chat_id})
    return F()


def esperar(cond, tempo=40):
    fim = time.time() + tempo
    while time.time() < fim:
        v = cond()
        if v:
            return v
        time.sleep(0.2)
    from app import db as _db
    ev = [dict(r) for r in _db.q("SELECT tipo, detalhe FROM eventos ORDER BY id DESC LIMIT 6")]
    raise AssertionError(f"tempo esgotado esperando a condição (últimos eventos: {ev})")
