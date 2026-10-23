import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from app import db, llm_local


def test_catalogo_modelos_leves():
    cat = llm_local.MODELOS_CATALOGO
    assert "qwen2.5:1.5b" in cat
    assert "llama3.2:1b" in cat
    assert cat["qwen2.5:1.5b"]["recomendado"] is True
    assert "986 MB" in cat["qwen2.5:1.5b"]["tamanho"]


def test_detectar_base_url_fallback():
    async def _test():
        with patch("httpx.AsyncClient.get", side_effect=Exception("offline")):
            url = await llm_local.detectar_base_url()
            assert url == "http://llm:11434"
    asyncio.run(_test())


def test_apontar_como_padrao_insere_e_atualiza():
    db.init()
    # Limpar conexoes de teste
    db.x("DELETE FROM llm_conexoes WHERE nome LIKE 'LLM Local%'")
    
    # 1. Apontar qwen2.5:1.5b
    cid = llm_local.apontar_como_padrao("qwen2.5:1.5b", "http://llm:11434")
    assert cid > 0
    con = db.one("SELECT * FROM llm_conexoes WHERE id=?", (cid,))
    assert con is not None
    assert con["tipo"] == "ollama"
    assert con["modelo"] == "qwen2.5:1.5b"
    assert con["padrao"] == 1
    
    # 2. Apontar outro modelo e verificar se o anterior deixa de ser padrão
    cid2 = llm_local.apontar_como_padrao("llama3.2:1b", "http://llm:11434")
    assert cid2 > 0
    con_antigo = db.one("SELECT padrao FROM llm_conexoes WHERE id=?", (cid,))
    con_novo = db.one("SELECT padrao FROM llm_conexoes WHERE id=?", (cid2,))
    assert con_antigo["padrao"] == 0
    assert con_novo["padrao"] == 1


def test_status_servidor_online_mock():
    async def _test():
        db.init()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "qwen2.5:1.5b"}]}
        
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            status = await llm_local.status_servidor()
            assert status["online"] is True
            assert "qwen2.5:1.5b" in status["modelos_instalados"]
            assert "catalogo" in status
    asyncio.run(_test())
