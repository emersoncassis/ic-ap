"""Conexões de LLM e geração da reação em JSON.

Tipos: openai (qualquer app/servidor compatível: LM Studio, Jan, llama.cpp, vLLM, Ollama /v1, OpenRouter…),
ollama (API nativa), gemini, anthropic. A conexão guarda URL, chave e o modelo escolhido.
"""
import json, re, time

import httpx

from . import config as C

TIPOS = {
    "openai": "Compatível com OpenAI (LM Studio, Jan, llama.cpp, vLLM…)",
    "ollama": "Ollama",
    "gemini": "Google Gemini (API)",
    "anthropic": "Anthropic Claude (API)",
}
DICAS_URL = {"openai": "http://host.docker.internal:1234/v1", "ollama": "http://host.docker.internal:11434", "gemini": "", "anthropic": ""}
CAMPOS = ["manchete_curta", "minha_reacao", "legenda_instagram", "fonte", "confianca"]
SCHEMA = {
    "type": "object",
    "properties": {
        "manchete_curta": {"type": "string"}, "minha_reacao": {"type": "string"},
        "legenda_instagram": {"type": "string"}, "fonte": {"type": "string"},
        "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
    },
    "required": CAMPOS,
}
INSTRUCOES = """
Você escreve posts de Instagram reagindo a uma notícia, na voz da pessoa descrita acima.
Responda SOMENTE com um JSON com os campos:
- manchete_curta: resumo da notícia em até 10 palavras.
- minha_reacao: 2 parágrafos curtos, primeira pessoa, no tom descrito, até 450 caracteres no total. Opinião marcada como opinião.
- legenda_instagram: legenda completa com a fonte citada e 3 a 5 hashtags, até 2000 caracteres.
- fonte: nome do veículo.
- confianca: "alta" se a notícia é clara e você entendeu bem, "media" ou "baixa" se faltou informação.
Regras: não invente fatos que não estejam no texto da notícia. Não reproduza trechos longos da matéria. Português do Brasil.
""".strip()

DICA_DOCKER = " Se o programa roda no seu PC e este app roda no Docker, use host.docker.internal no lugar de localhost."


class LLMError(Exception):
    pass


def _erro_http(e: Exception, url: str) -> LLMError:
    if isinstance(e, httpx.HTTPStatusError):
        corpo = e.response.text[:200].replace("\n", " ")
        return LLMError(f"HTTP {e.response.status_code} em {url}: {corpo}")
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
        return LLMError(f"não consegui conectar em {url}.{DICA_DOCKER}")
    return LLMError(f"{type(e).__name__} em {url}: {e}")


# ---------- detecção de modelos ----------
async def listar_modelos(tipo: str, base_url: str, key: str) -> tuple[list[str], str]:
    """Devolve (modelos, base_url_resolvida)."""
    base = (base_url or "").strip().rstrip("/")
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            if tipo == "openai":
                tentativas = [base] + ([base + "/v1"] if not base.endswith("/v1") else [])
                ultimo: Exception | None = None
                for b in tentativas:
                    try:
                        r = await c.get(f"{b}/models", headers={"Authorization": f"Bearer {key}"} if key else {})
                        r.raise_for_status()
                        return sorted(m["id"] for m in r.json().get("data", [])), b
                    except Exception as e:  # tenta a próxima base (/v1)
                        ultimo = _erro_http(e, f"{b}/models")
                raise ultimo or LLMError("sem resposta")
            if tipo == "ollama":
                b = base.removesuffix("/v1")
                r = await c.get(f"{b}/api/tags")
                r.raise_for_status()
                return sorted(m["name"] for m in r.json().get("models", [])), b
            if tipo == "gemini":
                if not key:
                    raise LLMError("informe a chave de API do Gemini")
                r = await c.get(f"{C.GEMINI_API_BASE}/models", params={"pageSize": 200}, headers={"x-goog-api-key": key})
                r.raise_for_status()
                return sorted(m["name"].removeprefix("models/") for m in r.json().get("models", [])
                              if "generateContent" in m.get("supportedGenerationMethods", [])), ""
            if tipo == "anthropic":
                if not key:
                    raise LLMError("informe a chave de API da Anthropic")
                r = await c.get(f"{C.ANTHROPIC_API_BASE}/models", params={"limit": 100},
                                headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
                r.raise_for_status()
                return [m["id"] for m in r.json().get("data", [])], ""
        except LLMError:
            raise
        except Exception as e:
            raise _erro_http(e, base or tipo)
    raise LLMError(f"tipo desconhecido: {tipo}")


# ---------- chamada ao modelo ----------
async def _chat(con: dict, system: str, user: str, temperature: float) -> str:
    tipo, modelo, base, key = con["tipo"], con["modelo"], con["base_url"].rstrip("/"), con.get("api_key", "")
    if not modelo:
        raise LLMError("a conexão não tem modelo escolhido")
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    async with httpx.AsyncClient(timeout=300) as c:
        try:
            if tipo == "openai":
                hdr = {"Authorization": f"Bearer {key}"} if key else {}
                corpo = {"model": modelo, "messages": msgs, "temperature": temperature, "stream": False}
                r = await c.post(f"{base}/chat/completions", headers=hdr, json={
                    **corpo, "response_format": {"type": "json_schema", "json_schema": {"name": "reacao", "schema": SCHEMA, "strict": True}}})
                if r.status_code == 400:  # servidor sem suporte a response_format: confia no prompt
                    r = await c.post(f"{base}/chat/completions", headers=hdr, json=corpo)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            if tipo == "ollama":
                r = await c.post(f"{base}/api/chat", json={
                    "model": modelo, "stream": False, "format": SCHEMA, "messages": msgs,
                    "options": {"temperature": temperature, "num_ctx": 8192}})
                r.raise_for_status()
                return r.json()["message"]["content"]
            if tipo == "gemini":
                r = await c.post(f"{C.GEMINI_API_BASE}/models/{modelo}:generateContent", headers={"x-goog-api-key": key}, json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"}})
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            if tipo == "anthropic":
                r = await c.post(f"{C.ANTHROPIC_API_BASE}/messages", headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, json={
                    "model": modelo, "max_tokens": 1500, "temperature": min(temperature, 1.0), "system": system,
                    "messages": [{"role": "user", "content": user}]})
                r.raise_for_status()
                return r.json()["content"][0]["text"]
        except LLMError:
            raise
        except Exception as e:
            raise _erro_http(e, base or tipo)
    raise LLMError(f"tipo desconhecido: {tipo}")


def montar_system(contexto: str) -> str:
    return f"{contexto.strip()}\n\n---\n{INSTRUCOES}"


def montar_user(n: dict, feedback: str | None = None, angulo: str | None = None) -> str:
    s = f"Notícia\nTítulo: {n['titulo']}\nFonte: {n['fonte']}\nLink: {n['url']}\n\nTexto:\n{n['texto']}"
    if angulo:
        s += f"\n\nÂngulo desta versão: {angulo}. Faça uma versão claramente diferente das outras versões da mesma notícia."
    if feedback:
        s += f"\n\nA resposta anterior foi rejeitada: {feedback}. Corrija e responda de novo só com o JSON."
    return s


def parse(raw: str) -> dict:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()  # modelos que "pensam em voz alta"
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("resposta sem JSON")
    return json.loads(m.group(0))


def validar(d: dict) -> list[str]:
    erros = []
    for k in CAMPOS:
        if not isinstance(d.get(k), str) or not d[k].strip():
            erros.append(f"campo '{k}' ausente ou vazio")
    if erros:
        return erros
    if len(d["manchete_curta"].split()) > 10:
        erros.append("manchete_curta com mais de 10 palavras")
    if len(d["minha_reacao"]) > 600:
        erros.append("minha_reacao com mais de 600 caracteres")
    if len(d["legenda_instagram"]) > 2200:
        erros.append("legenda_instagram com mais de 2200 caracteres")
    if d["confianca"] not in ("alta", "media", "baixa"):
        erros.append("confianca deve ser alta, media ou baixa")
    return erros


def pos_processar(d: dict) -> dict:
    """Garante o crédito da fonte na legenda."""
    if d["fonte"].lower() not in d["legenda_instagram"].lower():
        d["legenda_instagram"] = d["legenda_instagram"].rstrip() + f"\n\nFonte: {d['fonte']}"
    return d


async def reagir(con: dict, contexto: str, noticia: dict, temperature: float = 0.7, feedback: str | None = None,
                 angulo: str | None = None) -> dict:
    """Uma tentativa. ValueError = saída inválida (vale tentar de novo); LLMError = conexão/servidor."""
    raw = await _chat(con, montar_system(contexto), montar_user(noticia, feedback, angulo), temperature)
    d = parse(raw)
    erros = validar(d)
    if erros:
        raise ValueError("; ".join(erros))
    return pos_processar(d)


async def testar(con: dict) -> dict:
    """Pede uma reação a uma notícia de exemplo e confere se volta o JSON esperado."""
    noticia = {"titulo": "Empresa adota IA no atendimento", "fonte": "Exemplo News", "url": "https://exemplo.com/n",
               "texto": "Uma empresa brasileira passou a usar inteligência artificial no atendimento ao cliente e relatou "
                        "redução no tempo de resposta, mantendo os dados em servidores próprios."}
    t0 = time.time()
    ultimo = ""
    for _ in range(2):
        try:
            d = await reagir(con, "Você é um comentarista direto e objetivo.", noticia, 0.5, ultimo or None)
            return {"ok": True, "segundos": round(time.time() - t0, 1), "manchete": d["manchete_curta"]}
        except ValueError as e:
            ultimo = str(e)
    return {"ok": False, "segundos": round(time.time() - t0, 1), "erro": f"o modelo respondeu, mas fora do formato: {ultimo}"}
