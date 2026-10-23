"""Gerenciador de LLMs Locais Ultraleves (Ollama em 1 Clique).

Permite baixar e rodar modelos locais otimizados para CPU e GPU modesta:
- Qwen 2.5 1.5B (986 MB): Melhor custo-benefício em PT-BR e estruturação JSON
- Llama 3.2 1B (1.3 GB): Ultrarrápido, excelente para ganchos e headlines
- Qwen 2.5 3B (1.9 GB): Raciocínio profundo e redação refinada
- Llama 3.2 3B (2.0 GB): Forte em carrosséis e narrativas

O gerenciador detecta o servidor Ollama no Docker (http://llm:11434) ou na máquina host
(http://host.docker.internal:11434), baixa o modelo com acompanhamento de progresso,
e ao concluir, aponta e configura automaticamente a conexão como padrão no banco de dados.
"""
import asyncio
import json
import logging
from typing import Any

import httpx

from . import db

logger = logging.getLogger(__name__)

# Modelos recomendados: ultraleves, eficientes e rápidos em CPU/GPU
MODELOS_CATALOGO = {
    "qwen2.5:1.5b": {
        "tag": "qwen2.5:1.5b",
        "nome": "Qwen 2.5 1.5B",
        "tamanho": "986 MB",
        "ram": "2 GB",
        "recomendado": True,
        "descricao": "Ultra leve e veloz. Excelente compreensão de português e saídas JSON estruturadas sem alucinações.",
    },
    "llama3.2:1b": {
        "tag": "llama3.2:1b",
        "nome": "Llama 3.2 1B",
        "tamanho": "1.3 GB",
        "ram": "2 GB",
        "recomendado": False,
        "descricao": "Modelo mais rápido da Meta. Ótimo para geração de ideias, ganchos e micro-posts.",
    },
    "qwen2.5:3b": {
        "tag": "qwen2.5:3b",
        "nome": "Qwen 2.5 3B",
        "tamanho": "1.9 GB",
        "ram": "4 GB",
        "recomendado": False,
        "descricao": "Equilíbrio ideal entre velocidade e raciocínio profundo. Segue instruções complexas com precisão.",
    },
    "llama3.2:3b": {
        "tag": "llama3.2:3b",
        "nome": "Llama 3.2 3B",
        "tamanho": "2.0 GB",
        "ram": "4 GB",
        "recomendado": False,
        "descricao": "Raciocínio avançado da Meta para posts longos, carrosséis detalhados e narrativas.",
    },
}

# Estado volátil em memória para progresso de downloads ativos
_estado_download: dict[str, Any] = {
    "ativo": False,
    "modelo": "",
    "status": "ocioso",
    "percentual": 0,
    "concluido_bytes": 0,
    "total_bytes": 0,
    "erro": "",
}
_download_task: asyncio.Task | None = None


async def detectar_base_url() -> str:
    """Tenta detectar o endereço do Ollama no Docker ou no Host."""
    candidatos = [
        "http://llm:11434",
        "http://host.docker.internal:11434",
        "http://127.0.0.1:11434",
        "http://localhost:11434",
    ]
    async with httpx.AsyncClient(timeout=2.0) as client:
        for url in candidatos:
            try:
                r = await client.get(f"{url}/api/tags")
                if r.status_code == 200:
                    return url
            except Exception:
                continue
    return "http://llm:11434"


async def status_servidor() -> dict[str, Any]:
    """Retorna o status atual do servidor Ollama e os modelos instalados."""
    base_url = await detectar_base_url()
    online = False
    modelos_instalados: list[str] = []
    
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base_url}/api/tags")
            if r.status_code == 200:
                online = True
                dados = r.json()
                modelos_instalados = [m.get("name", "") for m in dados.get("models", [])]
    except Exception as e:
        logger.debug(f"Ollama offline em {base_url}: {e}")

    # Verificar se algum modelo do catálogo está ativo como conexão padrão
    con_padrao = db.one("SELECT * FROM llm_conexoes WHERE padrao=1")
    modelo_padrao_atual = con_padrao["modelo"] if con_padrao else ""

    return {
        "online": online,
        "base_url": base_url,
        "modelos_instalados": modelos_instalados,
        "modelo_padrao": modelo_padrao_atual,
        "download": dict(_estado_download),
        "catalogo": MODELOS_CATALOGO,
    }


def apontar_como_padrao(modelo_tag: str, base_url: str = "http://llm:11434") -> int:
    """Configura o modelo Ollama local como conexão padrão do sistema."""
    nome = f"LLM Local ({MODELOS_CATALOGO.get(modelo_tag, {}).get('nome', modelo_tag)})"
    
    # Desmarcar padrões atuais
    db.x("UPDATE llm_conexoes SET padrao=0")
    
    # Verificar se já existe conexão do tipo ollama com este modelo e base_url
    existente = db.one("SELECT id FROM llm_conexoes WHERE tipo='ollama' AND modelo=?", (modelo_tag,))
    if existente:
        cid = existente["id"]
        db.x("UPDATE llm_conexoes SET padrao=1, base_url=?, nome=? WHERE id=?", (base_url, nome, cid))
    else:
        cid = db.x(
            "INSERT INTO llm_conexoes(nome, tipo, base_url, api_key_enc, modelo, padrao, criado_em)"
            " VALUES(?, 'ollama', ?, '', ?, 1, ?)",
            (nome, base_url, modelo_tag, db.now()),
        )
    
    # Se houver perfil cadastrado, garantir que aponta para essa conexão
    perfis = db.q("SELECT id, llm_conexao_id FROM perfis")
    for p in perfis:
        if not p.get("llm_conexao_id"):
            db.x("UPDATE perfis SET llm_conexao_id=? WHERE id=?", (cid, p["id"]))

    db.log(None, None, "llm_local", f"Modelo {modelo_tag} configurado como padrão (conexão #{cid})")
    return cid


async def _executar_download(modelo_tag: str) -> None:
    """Executa o pull do modelo via API do Ollama e atualiza o estado."""
    global _estado_download
    base_url = await detectar_base_url()
    
    _estado_download = {
        "ativo": True,
        "modelo": modelo_tag,
        "status": "iniciando",
        "percentual": 0,
        "concluido_bytes": 0,
        "total_bytes": 0,
        "erro": "",
    }
    
    try:
        async with httpx.AsyncClient(timeout=1800.0) as client:
            async with client.stream("POST", f"{base_url}/api/pull", json={"name": modelo_tag, "stream": True}) as response:
                if response.status_code != 200:
                    corpo = await response.aread()
                    raise RuntimeError(f"Ollama retornou HTTP {response.status_code}: {corpo.decode('utf-8', errors='ignore')}")

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    
                    status = data.get("status", "")
                    total = data.get("total", 0)
                    completed = data.get("completed", 0)
                    
                    pct = int((completed / total * 100)) if total > 0 else 0
                    _estado_download["status"] = status
                    _estado_download["percentual"] = pct
                    _estado_download["concluido_bytes"] = completed
                    _estado_download["total_bytes"] = total
                    
                    if status == "success":
                        break

        # Ao concluir com sucesso, apontar automaticamente como padrão!
        apontar_como_padrao(modelo_tag, base_url)
        _estado_download["status"] = "concluido"
        _estado_download["percentual"] = 100
        _estado_download["ativo"] = False
        logger.info(f"Modelo {modelo_tag} baixado e configurado como padrão com sucesso.")
    except Exception as e:
        logger.error(f"Erro ao baixar modelo {modelo_tag}: {e}")
        _estado_download["status"] = "erro"
        _estado_download["erro"] = str(e)
        _estado_download["ativo"] = False


def iniciar_download(modelo_tag: str) -> bool:
    """Inicia o download do modelo em background se nenhum outro estiver ativo."""
    global _download_task
    if _estado_download.get("ativo"):
        return False
    
    _download_task = asyncio.create_task(_executar_download(modelo_tag))
    return True
