from unittest.mock import AsyncMock, patch

with patch('app.render.start', new_callable=AsyncMock), patch('app.render.stop', new_callable=AsyncMock):
    from fastapi.testclient import TestClient
    from app.main import app
    from app import db, crypto

    db.init()
    db.set_setting('admin_hash', crypto.hash_password('senha12345'))
    client = TestClient(app)
    client.post('/login', data={'senha': 'senha12345'}, follow_redirects=True)

    r_esc = client.get('/escritorio')
    assert r_esc.status_code == 200, f"Expected 200, got {r_esc.status_code}"
    assert '<div id="root"></div>' in r_esc.text
    assert 'index-DHTmCcY1.js' in r_esc.text
    assert 'index-thwPU4C_.css' in r_esc.text
    assert 'window.__ICAP_DATA__' in r_esc.text

    r_tileset = client.get('/assets/tilesets/FloorAndGround.png')
    assert r_tileset.status_code == 200, f"Tileset returned {r_tileset.status_code}"

    r_char = client.get('/assets/characters/char_0.png')
    assert r_char.status_code == 200, f"Char returned {r_char.status_code}"

    r_font = client.get('/assets/FSPixelSansUnicode-Regular-D9-dh-Uo.ttf')
    assert r_font.status_code == 200, f"Font returned {r_font.status_code}"

    print("ALL VERIFICATIONS PASSED 100%!")
