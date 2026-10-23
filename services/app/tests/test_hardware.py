import pytest
from app import db, hardware, pipeline

pytestmark = pytest.mark.usefixtures("estado_isolado")


def setup_function():
    db.init()
    db.x("DELETE FROM llm_conexoes WHERE nome LIKE 'TesteHardware%'")
    db.x("DELETE FROM settings WHERE k LIKE 'llm_modulo_%'")
    # Garante que as conexões de teste controlam o padrão
    db.x("UPDATE llm_conexoes SET padrao=0")


def test_detectar_hardware():
    hw = hardware.detectar_hardware()
    assert isinstance(hw, dict)
    assert "npu_disponivel" in hw
    assert "gpu_disponivel" in hw
    assert "cpu_nome" in hw
    assert hw["multi_model_suporte"] is True
    assert hw["max_modelos_simultaneos"] == 4


def test_obter_roteamento_estrutura():
    rot = hardware.obter_roteamento()
    assert "modulos" in rot
    assert "conexoes_disponiveis" in rot
    assert "hardware" in rot
    
    modulos = rot["modulos"]
    for mod in ("chat", "legenda", "noticias", "roteiro", "voz"):
        assert mod in modulos
        assert "nome" in modulos[mod]
        assert "icone" in modulos[mod]
        assert "descricao" in modulos[mod]


def test_roteamento_e_resolucao_conexoes_modulares():
    # 1. Cria 2 conexões distintas
    cid_chat = db.x(
        "INSERT INTO llm_conexoes(nome, tipo, base_url, api_key_enc, modelo, padrao, criado_em) "
        "VALUES('TesteHardware Chat', 'ollama', 'http://llm:11434', '', 'qwen2.5:1.5b', 0, ?)",
        (db.now(),)
    )
    cid_legenda = db.x(
        "INSERT INTO llm_conexoes(nome, tipo, base_url, api_key_enc, modelo, padrao, criado_em) "
        "VALUES('TesteHardware Legenda', 'openai', 'https://api.openai.com/v1', '', 'gpt-4o', 1, ?)",
        (db.now(),)
    )
    
    # 2. Inicialmente sem roteamento específico: todos usam o padrão (gpt-4o)
    con_chat_init = hardware.obter_conexao_modulo("chat")
    assert con_chat_init is not None
    assert con_chat_init["modelo"] == "gpt-4o"
    
    # 3. Salva roteamento: chat -> qwen2.5:1.5b, legenda -> gpt-4o
    hardware.salvar_roteamento_modulos({
        "modulo_chat": str(cid_chat),
        "modulo_legenda": str(cid_legenda),
        "modulo_noticias": "",  # vazio = usa padrão
    })
    
    # 4. Verifica resolução modular
    con_chat = hardware.obter_conexao_modulo("chat")
    con_legenda = hardware.obter_conexao_modulo("legenda")
    con_noticias = hardware.obter_conexao_modulo("noticias")
    
    assert con_chat["id"] == cid_chat
    assert con_chat["modelo"] == "qwen2.5:1.5b"
    
    assert con_legenda["id"] == cid_legenda
    assert con_legenda["modelo"] == "gpt-4o"
    
    # Notícias estava vazio, deve fazer fallback para o padrão (cid_legenda)
    assert con_noticias["id"] == cid_legenda
    
    # 5. Verifica via pipeline.conexao_do_modulo
    p_chat = pipeline.conexao_do_modulo("chat")
    assert p_chat["id"] == cid_chat
    
    # 6. Perfil com conexão própria tem precedência sobre o módulo
    perfil_fake = {"id": 1, "llm_conexao_id": cid_chat}
    p_leg_override = pipeline.conexao_do_modulo("legenda", perfil_fake)
    assert p_leg_override["id"] == cid_chat


def test_orientador_local_e_custo_zero():
    # 1. Cria conexão Ollama local
    cid_local = db.x(
        "INSERT INTO llm_conexoes(nome, tipo, base_url, api_key_enc, modelo, padrao, criado_em) "
        "VALUES('TesteHardware Ollama Local', 'ollama', 'http://icap-llm:11434', '', 'llama3.2:1b', 0, ?)",
        (db.now(),)
    )

    # 2. Testa orientador
    hw = hardware.detectar_hardware()
    conexoes = db.q("SELECT * FROM llm_conexoes")
    orientador = hardware.obter_orientador_local(hw, conexoes)
    assert orientador["tem_ollama"] is True
    assert len(orientador["dicas"]) >= 4

    # 3. Aplica perfil de custo zero
    res = hardware.aplicar_perfil_custo_zero()
    assert res["ok"] is True
    assert db.get_setting("tts_model") == "embutido"
    assert db.get_setting("whisper_local") == "1"
    assert db.get_setting("whisper_url") == ""
    assert db.get_setting("llm_modulo_chat") == str(cid_local)
    assert db.get_setting("llm_modulo_roteiro") == str(cid_local)


def test_modulo_voz_roteamento():
    # 1. Configura para Chatterbox
    hardware.salvar_roteamento_modulos({"modulo_voz": "chatterbox"})
    assert db.get_setting("tts_model") == "chatterbox"
    assert "voz" in db.get_setting("whisper_url")
    
    rot1 = hardware.obter_roteamento()
    assert rot1["modulos"]["voz"]["tipo_motor"] == "chatterbox"

    # 2. Configura para Whisper Embutido (zero GPU / zero tokens)
    hardware.salvar_roteamento_modulos({"modulo_voz": "embutido"})
    assert db.get_setting("tts_model") == "embutido"
    assert db.get_setting("whisper_local") == "1"
    
    rot2 = hardware.obter_roteamento()
    assert rot2["modulos"]["voz"]["tipo_motor"] == "embutido"
    assert "Custo Zero" in rot2["modulos"]["voz"]["status_amigavel"]

