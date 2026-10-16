"""Geração da reação em JSON. Provedores: ollama (padrão), gemini, anthropic."""
import json, os, re

import httpx

from . import config as C

CAMPOS = ["manchete_curta", "minha_reacao", "legenda_instagram", "fonte", "confianca"]
SCHEMA = {
    "type": "object",
    "properties": {
        "manchete_curta": {"type": "string"},
        "minha_reacao": {"type": "string"},
        "legenda_instagram": {"type": "string"},
        "fonte": {"type": "string"},
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


def montar_system(contexto: str) -> str:
    return f"{contexto.strip()}\n\n---\n{INSTRUCOES}"


def montar_user(n: dict, feedback: str | None = None) -> str:
    s = f"Notícia\nTítulo: {n['titulo']}\nFonte: {n['fonte']}\nLink: {n['url']}\n\nTexto:\n{n['texto']}"
    if feedback:
        s += f"\n\nA resposta anterior foi rejeitada: {feedback}. Corrija e responda de novo só com o JSON."
    return s


async def _chat(provider: str, model: str, system: str, user: str, temperature: float) -> str:
    async with httpx.AsyncClient(timeout=300) as c:
        if provider == "ollama":
            r = await c.post(f"{C.OLLAMA_URL}/api/chat", json={
                "model": model or C.OLLAMA_MODEL, "stream": False, "format": SCHEMA,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": temperature, "num_ctx": 8192}})
            r.raise_for_status()
            return r.json()["message"]["content"]
        if provider == "gemini":
            key = os.environ["GEMINI_API_KEY"]
            r = await c.post(f"{C.GEMINI_API_BASE}/models/{model}:generateContent",
                             headers={"x-goog-api-key": key},
                             json={"systemInstruction": {"parts": [{"text": system}]},
                                   "contents": [{"role": "user", "parts": [{"text": user}]}],
                                   "generationConfig": {"temperature": temperature,
                                                        "responseMimeType": "application/json"}})
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if provider == "anthropic":
            key = os.environ["ANTHROPIC_API_KEY"]
            r = await c.post(f"{C.ANTHROPIC_API_BASE}/messages",
                             headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                             json={"model": model, "max_tokens": 1500, "temperature": min(temperature, 1.0),
                                   "system": system, "messages": [{"role": "user", "content": user}]})
            r.raise_for_status()
            return r.json()["content"][0]["text"]
    raise ValueError(f"provedor desconhecido: {provider}")


def parse(raw: str) -> dict:
    raw = raw.strip()
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


async def reagir(perfil: dict, noticia: dict, temperature: float = 0.7, feedback: str | None = None) -> dict:
    """Uma tentativa. Levanta ValueError com a lista de problemas se a saída for inválida."""
    raw = await _chat(perfil["llm_provider"], perfil["llm_model"], montar_system(perfil["contexto_md"]),
                      montar_user(noticia, feedback), temperature)
    d = parse(raw)
    erros = validar(d)
    if erros:
        raise ValueError("; ".join(erros))
    return pos_processar(d)
