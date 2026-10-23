import httpx
from app import db, hardware

db.init()
# Configure an admin password for testing session
with httpx.Client(base_url="http://127.0.0.1:8000", follow_redirects=True) as client:
    # 1. Setup password
    r1 = client.get("/")
    print("Initial url:", r1.url)
    
    if "/setup" in str(r1.url):
        r_post = client.post("/setup", data={"senha": "admin123456senha", "senha2": "admin123456senha"})
        print("Setup post status:", r_post.status_code, "url:", r_post.url)
    elif "/login" in str(r1.url):
        r_post = client.post("/login", data={"senha": "admin123456senha"})
        print("Login post status:", r_post.status_code, "url:", r_post.url)

    # 2. Access /llm
    r_llm = client.get("/llm")
    print("/llm status:", r_llm.status_code)
    assert r_llm.status_code == 200
    html = r_llm.text
    assert "Aceleradores de Hardware Ativos" in html
    assert "Roteamento Inteligente de IA por Módulo" in html
    assert "Servidor de Voz" in html
    assert "Ollama" in html
    print("SUCCESS: /llm rendered with all hardware, voice and modular routing cards!")

    import re
    m = re.search(r'name="csrf"\s+value="([^"]+)"', html)
    csrf_token = m.group(1) if m else ""
    print("Extracted CSRF:", csrf_token)

    # 3. Test saving routing via POST /llm/roteamento
    r_rot = client.post("/llm/roteamento", data={
        "csrf": csrf_token,
        "modulo_chat": "",
        "modulo_legenda": "",
        "modulo_noticias": "",
        "modulo_roteiro": "",
    })
    print("POST /llm/roteamento status:", r_rot.status_code, "url:", r_rot.url)
    assert r_rot.status_code == 200
    print("SUCCESS: POST /llm/roteamento tested live with CSRF!")
