import pytest
from app import db, hardware, llm
from unittest.mock import patch
import httpx


def setup_function():
    db.init()
    db.x("DELETE FROM llm_conexoes WHERE nome LIKE 'TesteOpenRouter%' OR tipo='openrouter'")


@pytest.mark.anyio
async def test_listar_modelos_openrouter():
    # Sem chave: deve lançar erro
    with pytest.raises(llm.LLMError, match="informe a chave de API da OpenRouter"):
        await llm.listar_modelos("openrouter", "", "")

    # Com chave mockada: deve priorizar modelos gratuitos (:free)
    mock_resp = {
        "data": [
            {"id": "openai/gpt-4o"},
            {"id": "meta-llama/llama-3.3-70b-instruct:free"},
            {"id": "anthropic/claude-3.5-sonnet"},
            {"id": "deepseek/deepseek-r1:free"},
        ]
    }
    
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = httpx.Response(200, json=mock_resp, request=httpx.Request("GET", "https://openrouter.ai/api/v1/models"))
        mock_get.return_value = mock_response
        
        modelos, base = await llm.listar_modelos("openrouter", "", "sk-or-test-key")
        assert base == "https://openrouter.ai/api/v1"
        assert len(modelos) == 4
        # Modelos :free devem vir primeiro
        assert modelos[0] == "deepseek/deepseek-r1:free"
        assert modelos[1] == "meta-llama/llama-3.3-70b-instruct:free"
        assert ":free" not in modelos[2]
        assert ":free" not in modelos[3]


def test_hardware_orientador_openrouter():
    hw = hardware.detectar_hardware()
    conexoes = [
        {"id": 1, "nome": "OpenRouter", "tipo": "openrouter", "base_url": "https://openrouter.ai/api/v1", "padrao": 1}
    ]
    orientador = hardware.obter_orientador_local(hw, conexoes)
    assert orientador["tem_openrouter"] is True
    assert "tem_omniroute" not in orientador
    assert "tem_freellmapi" not in orientador


def test_db_migracao_remove_omniroute_freellmapi():
    # Cria registros antigos
    db.x("INSERT INTO llm_conexoes(nome, tipo, base_url, api_key_enc, modelo, padrao, criado_em) VALUES('Antigo Omni', 'omniroute', 'http://host.docker.internal:3000/v1', '', 'default', 0, ?)", (db.now(),))
    db.x("INSERT INTO llm_conexoes(nome, tipo, base_url, api_key_enc, modelo, padrao, criado_em) VALUES('Antigo FreeLLM', 'freellmapi', 'http://host.docker.internal:3001/v1', '', 'default', 0, ?)", (db.now(),))
    
    assert db.one("SELECT COUNT(*) n FROM llm_conexoes WHERE tipo IN ('omniroute', 'freellmapi')")["n"] == 2
    
    # Executa migração
    db._migrar()
    
    # Devem ter sido limpos
    assert db.one("SELECT COUNT(*) n FROM llm_conexoes WHERE tipo IN ('omniroute', 'freellmapi')")["n"] == 0
