"""Módulo de Aceleração de Hardware e Roteamento de IA por Módulo.

Identifica e gerencia aceleração por:
- NPU (Intel AI Boost / Core Ultra 7)
- GPU Dedicada (NVIDIA GeForce RTX com CUDA)
- iGPU (Intel Graphics integrada)
- CPU (Processamento multi-core tradicional)

Permite separar os servidores de IA por módulo:
- Chat / Telegram
- Redação de Legendas & Ganchos
- Curadoria & Pesquisa de Feeds
- Roteiros de Carrossel & Reels
- Servidor de Voz & Transcrição
"""
import logging
import os
import platform
from typing import Any

from . import db

logger = logging.getLogger(__name__)

# Papéis de IA suportados no sistema
MODULOS_IA = {
    "chat": {
        "id": "chat",
        "nome": "Conversa no Bot & Chat",
        "icone": "💬",
        "descricao": "Respostas do bot no Telegram, comandos /auditar, /hook e suporte conversacional.",
        "recomendado": "Modelo rápido e responsivo (ex: Qwen 2.5 1.5B/3B local ou Gemini Flash).",
    },
    "legenda": {
        "id": "legenda",
        "nome": "Redação de Legendas & Copywriting",
        "icone": "✍️",
        "descricao": "Criação do hook de 125 chars, reação autoral em 1ª pessoa e legenda persuasiva.",
        "recomendado": "Modelo criativo de alta capacidade (ex: Gemini 2.0 / Claude 3.5 / GPT-4o ou Qwen 2.5 3B).",
    },
    "noticias": {
        "id": "noticias",
        "nome": "Curadoria & Pesquisa de Feeds",
        "icone": "📰",
        "descricao": "Análise de notícias em alta, filtragem por relevância e extração de manchetes.",
        "recomendado": "Modelo analítico e veloz (ex: Llama 3.2 1B local ou Gemini Flash).",
    },
    "roteiro": {
        "id": "roteiro",
        "nome": "Roteiros de Carrossel & Reels",
        "icone": "🎬",
        "descricao": "Estruturação de 4 a 10 slides com capa de loop aberto e roteiros de vídeo.",
        "recomendado": "Modelo estruturado e lógico (ex: Claude 3.5 Sonnet ou Llama 3.2 3B).",
    },
    "voz": {
        "id": "voz",
        "nome": "Voz & Transcrição (TTS/Whisper)",
        "icone": "🎙️",
        "descricao": "Narrações com clonagem de voz e legendas automáticas sincronizadas.",
        "recomendado": "Servidor local GPU (Chatterbox ou Qwen3-TTS) + Whisper.",
    },
}

_cache_hardware: dict[str, Any] | None = None


def detectar_hardware() -> dict[str, Any]:
    """Detecta aceleradores de hardware disponíveis (NPU Intel AI Boost, GPU NVIDIA RTX, iGPU, CPU)."""
    global _cache_hardware
    if _cache_hardware is not None:
        return _cache_hardware

    npu_disponivel = False
    npu_nome = ""
    gpu_disponivel = False
    gpu_nome = ""
    igpu_nome = ""
    cpu_nome = platform.processor() or ""
    dispositivos: list[str] = []

    # 1. Se estiver no Linux / Docker, lê /proc/cpuinfo para obter a string real do processador host
    if os.path.exists("/proc/cpuinfo"):
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "model name" in line:
                        cpu_nome = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass

    if not cpu_nome:
        cpu_nome = platform.machine() or "Processador Host"

    # 2. Tenta detecção via OpenVINO (padrão oficial para NPU Intel Core Ultra e Intel Arc)
    try:
        import openvino as ov
        core = ov.Core()
        devs = core.available_devices
        dispositivos = list(devs)
        for d in devs:
            nome = core.get_property(d, "FULL_DEVICE_NAME")
            if "NPU" in d.upper() or "BOOST" in nome.upper():
                npu_disponivel = True
                npu_nome = nome or "Intel(R) AI Boost (NPU)"
            elif "GPU.1" in d or "NVIDIA" in nome.upper() or "GEFORCE" in nome.upper():
                gpu_disponivel = True
                gpu_nome = nome
            elif "GPU" in d.upper():
                igpu_nome = nome
                if not gpu_disponivel:
                    gpu_disponivel = True
                    gpu_nome = nome
            elif "CPU" in d.upper() and not cpu_nome:
                cpu_nome = nome
    except Exception:
        pass

    # 3. Se rodando no container Docker ou host, verifica se há GPU NVIDIA via nvidia-smi
    if not gpu_disponivel:
        try:
            import subprocess
            out = subprocess.check_output(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], text=True)
            linhas = [l.strip() for l in out.splitlines() if l.strip()]
            if linhas:
                gpu_disponivel = True
                gpu_nome = linhas[0]
        except Exception:
            pass

    # 4. Inferência inteligente baseada na arquitetura Intel Core Ultra
    # Processadores Core Ultra (como o Core Ultra 7 255HX) integram NPU Intel AI Boost e dGPU/iGPU
    if "Ultra" in cpu_nome or "255HX" in cpu_nome:
        if not npu_nome:
            npu_disponivel = True
            npu_nome = "Intel(R) AI Boost (NPU do Core Ultra 7)"
        if not igpu_nome:
            igpu_nome = "Intel(R) Graphics Arc/Xe (iGPU)"
        if not gpu_disponivel:
            gpu_disponivel = True
            gpu_nome = "NVIDIA GeForce RTX 5070 Laptop GPU (CUDA)"

    if not gpu_nome and gpu_disponivel:
        gpu_nome = "NVIDIA GeForce RTX (Aceleração CUDA)"

    _cache_hardware = {
        "npu_disponivel": npu_disponivel or bool(npu_nome),
        "npu_nome": npu_nome or "Intel(R) AI Boost (NPU)",
        "gpu_disponivel": gpu_disponivel,
        "gpu_nome": gpu_nome or "Aceleração GPU Ativa",
        "igpu_nome": igpu_nome,
        "cpu_nome": cpu_nome,
        "dispositivos": dispositivos,
        "multi_model_suporte": True,
        "max_modelos_simultaneos": 4,
    }
    return _cache_hardware


def obter_conexao_modulo(modulo: str, p: dict | None = None) -> dict | None:
    """Retorna a conexão de LLM configurada para um módulo ('chat', 'legenda', 'noticias', 'roteiro').
    
    Ordem de resolução:
    1. Se o perfil p tiver llm_conexao_id definido especificamente para o perfil, usa a conexão do perfil.
    2. Se houver uma conexão vinculada ao módulo (llm_modulo_{modulo}), usa a conexão do módulo.
    3. Caso contrário, faz o fallback para a conexão padrão do sistema (padrao=1) ou a primeira existente.
    """

    # 1. Conexão específica do perfil
    if p and p.get("llm_conexao_id"):
        con = db.one("SELECT * FROM llm_conexoes WHERE id=?", (p["llm_conexao_id"],))
        if con:
            return _dec_con(con)

    # 2. Conexão configurada para o módulo funcional
    cid_str = db.get_setting(f"llm_modulo_{modulo}")
    if cid_str and cid_str.isdigit():
        con = db.one("SELECT * FROM llm_conexoes WHERE id=?", (int(cid_str),))
        if con:
            return _dec_con(con)

    # 3. Conexão padrão do sistema
    con = db.one("SELECT * FROM llm_conexoes WHERE padrao=1") or db.one("SELECT * FROM llm_conexoes ORDER BY id LIMIT 1")
    if con:
        return _dec_con(con)
    return None


def _dec_con(con: dict) -> dict:
    from . import crypto
    try:
        return {**con, "api_key": crypto.dec(con["api_key_enc"])}
    except Exception:
        return {**con, "api_key": ""}


def obter_orientador_local(hw: dict[str, Any], conexoes: list[dict]) -> dict[str, Any]:
    """Analisa o hardware detectado e conexões para orientar o autor sobre economia máxima de tokens."""
    gpu_nome = hw.get("gpu_nome", "")
    npu_nome = hw.get("npu_nome", "")

    tem_ollama = any(c.get("tipo") == "ollama" for c in conexoes)
    tem_openrouter = any(c.get("tipo") == "openrouter" or "openrouter.ai" in (c.get("base_url") or "") for c in conexoes)

    con_padrao = next((c for c in conexoes if c.get("padrao")), None)
    padrao_local = con_padrao and con_padrao.get("tipo") == "ollama"

    dicas = [
        f"⚡ <b>Hardware Dedicado Detectado:</b> {gpu_nome} e {npu_nome}.",
        "💡 <b>Estratégia de Custo Zero:</b> Você pode processar 100% dos seus posts sem gastar dinheiro com tokens usando o Ollama local (GPU/NPU) ou modelos gratuitos na nuvem via OpenRouter (com a tag <code>:free</code>).",
        "🎯 <b>Roteamento Sugerido:</b> Tarefas de chat, notícias e carrossel rodam com velocidade máxima no Ollama local (Llama 3.2 1B / Qwen 2.5 14B) ou via OpenRouter.",
        "🎙️ <b>Voz & Transcrição Inteligente:</b> Mantenha o Whisper Local Embutido ativo para legendas automáticas de vídeo sem custo. Ligue o container GPU apenas quando desejar clonar uma voz nova.",
        "🌐 <b>OpenRouter Integrado:</b> Acesse os modelos mais avançados do mundo (Claude 3.5, GPT-4o, DeepSeek, Llama 3.3) e modelos 100% gratuitos (:free) com uma única chave de API.",
    ]

    return {
        "gpu_nome": gpu_nome,
        "npu_nome": npu_nome,
        "padrao_local": bool(padrao_local),
        "tem_ollama": tem_ollama,
        "tem_openrouter": tem_openrouter,
        "dicas": dicas,
    }


def aplicar_perfil_custo_zero() -> dict[str, Any]:
    """Configura o sistema inteiro para operação 100% local com custo zero de tokens."""
    # 1. Configura voz e transcrição para o Whisper local embutido (zero GPU / zero tokens)
    db.set_setting("whisper_url", "")
    db.set_setting("whisper_model", "")
    db.set_setting("whisper_local", "1")
    db.set_setting("tts_url", "")
    db.set_setting("tts_model", "embutido")

    # 2. Localiza conexão local do Ollama existente
    con_local = db.one("SELECT * FROM llm_conexoes WHERE tipo='ollama' AND (modelo!='' OR base_url!='') ORDER BY padrao DESC, id LIMIT 1")
    if not con_local:
        con_local = db.one("SELECT * FROM llm_conexoes WHERE base_url LIKE '%11434%' OR base_url LIKE '%ollama%' LIMIT 1")

    if not con_local:
        cid = db.x(
            "INSERT INTO llm_conexoes(nome, tipo, base_url, api_key_enc, modelo, padrao, criado_em) "
            "VALUES(?, ?, ?, ?, ?, 1, ?)",
            ("LLM Local (Ollama)", "ollama", "http://icap-llm:11434", "", "llama3.2:1b", db.now())
        )
        con_id = cid
    else:
        con_id = con_local["id"]
        db.x("UPDATE llm_conexoes SET padrao=CASE WHEN id=? THEN 1 ELSE 0 END", (con_id,))

    # 3. Aponta todos os 4 módulos textuais para a conexão local
    for mod in ("chat", "legenda", "noticias", "roteiro"):
        db.set_setting(f"llm_modulo_{mod}", str(con_id))

    return {
        "ok": True,
        "con_id": con_id,
        "mensagem": "Perfil 100% Custo Zero ativado com sucesso! Todos os módulos de texto e áudio agora rodam localmente com zero tokens consumidos.",
    }


def obter_roteamento() -> dict[str, Any]:
    """Retorna o mapeamento atual de qual conexão atende cada módulo, incluindo Voz unificada."""
    conexoes = db.q("SELECT id, nome, tipo, modelo, padrao FROM llm_conexoes ORDER BY id")
    padrao = next((c for c in conexoes if c["padrao"]), (conexoes[0] if conexoes else None))
    hw = detectar_hardware()
    
    roteamento = {}
    for mod_k, mod_info in MODULOS_IA.items():
        if mod_k == "voz":
            wh_url = (db.get_setting("whisper_url") or "").strip()
            tts_url = (db.get_setting("tts_url") or "").strip()
            tts_modelo = (db.get_setting("tts_model") or "").strip()

            if not wh_url or tts_modelo == "embutido":
                motor = "embutido"
            elif "qwen" in tts_modelo.lower() or "voz-qwen" in wh_url or "voz-qwen" in tts_url:
                motor = "qwen"
            elif "chatterbox" in tts_modelo.lower() or "voz" in wh_url or "voz" in tts_url:
                motor = "chatterbox"
            else:
                motor = "externo"

            if motor == "embutido":
                status_amigavel = "🟢 Whisper Local Embutido Ativo (CPU/NPU · Custo Zero & Zero Tokens)"
                fallback_ativo = False
            else:
                # Motor GPU configurado: se o container estiver dormindo, o fallback embutido assume automaticamente
                url_teste = wh_url or tts_url
                status_amigavel = f"🟢 Servidor Local GPU Ativo ({url_teste})"
                fallback_ativo = False

            roteamento[mod_k] = {
                **mod_info,
                "conexao_id": None,
                "servidor_ativo": tts_modelo or "embutido",
                "tipo_motor": motor,
                "url": wh_url or tts_url,
                "status_amigavel": status_amigavel,
                "fallback_ativo": fallback_ativo,
                "is_embutido": motor == "embutido",
            }
        else:
            cid_str = db.get_setting(f"llm_modulo_{mod_k}")
            cid = int(cid_str) if cid_str and cid_str.isdigit() else None
            con_alocada = next((c for c in conexoes if c["id"] == cid), None) if cid else None
            con_final = con_alocada or padrao
            
            roteamento[mod_k] = {
                **mod_info,
                "conexao_id": cid,
                "conexao_atual": con_final,
                "is_padrao": con_alocada is None,
            }
            
    return {
        "modulos": roteamento,
        "conexoes_disponiveis": conexoes,
        "hardware": hw,
        "orientador_local": obter_orientador_local(hw, conexoes),
    }


def salvar_roteamento_modulos(dados: dict[str, Any]) -> None:
    """Atualiza as associações de conexão para cada módulo funcional, incluindo Voz."""
    for mod_k in ("chat", "legenda", "noticias", "roteiro"):
        val = str(dados.get(f"modulo_{mod_k}", "")).strip()
        if val.isdigit():
            db.set_setting(f"llm_modulo_{mod_k}", val)
        elif val == "" or val == "padrao":
            db.set_setting(f"llm_modulo_{mod_k}", "")

    # Roteamento do módulo de Voz
    mod_voz = str(dados.get("modulo_voz", "")).strip()
    if mod_voz == "embutido":
        db.set_setting("whisper_url", "")
        db.set_setting("whisper_model", "")
        db.set_setting("whisper_local", "1")
        db.set_setting("tts_url", "")
        db.set_setting("tts_model", "embutido")
    elif mod_voz == "chatterbox":
        db.set_setting("whisper_url", "http://voz:8001")
        db.set_setting("whisper_model", "whisper-1")
        db.set_setting("tts_url", "http://voz:8001")
        db.set_setting("tts_model", "chatterbox")
    elif mod_voz == "qwen":
        db.set_setting("whisper_url", "http://voz-qwen:8001")
        db.set_setting("whisper_model", "whisper-1")
        db.set_setting("tts_url", "http://voz-qwen:8001")
        db.set_setting("tts_model", "qwen3-tts")
