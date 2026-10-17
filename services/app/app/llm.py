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
def _alternar(msgs: list[dict]) -> list[dict]:
    """Junta turnos seguidos do mesmo papel e garante que começa por 'user' (exigência de Gemini e Anthropic)."""
    out: list[dict] = []
    for m in msgs:
        if out and out[-1]["role"] == m["role"]:
            out[-1] = {"role": m["role"], "content": out[-1]["content"] + "\n\n" + m["content"]}
        else:
            out.append(dict(m))
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


async def _chat(con: dict, system: str, user: str, temperature: float, schema: dict | None = None,
                historico: list[dict] | None = None) -> str:
    schema = schema or SCHEMA
    tipo, modelo, base, key = con["tipo"], con["modelo"], con["base_url"].rstrip("/"), con.get("api_key", "")
    if not modelo:
        raise LLMError("a conexão não tem modelo escolhido")
    turnos = _alternar([*(historico or []), {"role": "user", "content": user}])
    msgs = [{"role": "system", "content": system}, *turnos]
    async with httpx.AsyncClient(timeout=300) as c:
        try:
            if tipo == "openai":
                hdr = {"Authorization": f"Bearer {key}"} if key else {}
                corpo = {"model": modelo, "messages": msgs, "temperature": temperature, "stream": False}
                r = await c.post(f"{base}/chat/completions", headers=hdr, json={
                    **corpo, "response_format": {"type": "json_schema", "json_schema": {"name": "reacao", "schema": schema, "strict": True}}})
                if r.status_code == 400:  # servidor sem suporte a response_format: confia no prompt
                    r = await c.post(f"{base}/chat/completions", headers=hdr, json=corpo)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            if tipo == "ollama":
                r = await c.post(f"{base}/api/chat", json={
                    "model": modelo, "stream": False, "format": schema, "messages": msgs,
                    "options": {"temperature": temperature, "num_ctx": 8192}})
                r.raise_for_status()
                return r.json()["message"]["content"]
            if tipo == "gemini":
                r = await c.post(f"{C.GEMINI_API_BASE}/models/{modelo}:generateContent", headers={"x-goog-api-key": key}, json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user" if t["role"] == "user" else "model", "parts": [{"text": t["content"]}]} for t in turnos],
                    "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"}})
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            if tipo == "anthropic":
                r = await c.post(f"{C.ANTHROPIC_API_BASE}/messages", headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, json={
                    "model": modelo, "max_tokens": 3000, "temperature": min(temperature, 1.0), "system": system,
                    "messages": turnos})
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


SCHEMA_LEGENDA = {"type": "object", "properties": {"legenda_instagram": {"type": "string"}}, "required": ["legenda_instagram"]}


async def legenda_midia(con: dict, contexto: str, descricao: str, tipo: str, temperature: float = 0.8) -> str:
    """Legenda para uma foto/vídeo do próprio autor, a partir da frase de contexto que ele mandou."""
    system = (f"{contexto.strip()}\n\n---\nVocê escreve a legenda de Instagram de um(a) {tipo} do próprio autor, em primeira pessoa, "
              "no tom dele. Use só o que ele contou; não invente fatos. Máximo 600 caracteres, termine com 3 a 5 hashtags. "
              'Responda SOMENTE com JSON: {"legenda_instagram": "..."}')
    ultimo = ""
    for _ in range(3):
        user = f"O que ele contou sobre o {tipo}: {descricao}" + (f"\n\nA resposta anterior foi rejeitada: {ultimo}." if ultimo else "")
        try:
            d = parse(await _chat(con, system, user, temperature, SCHEMA_LEGENDA))
            leg = d.get("legenda_instagram")
            if isinstance(leg, str) and leg.strip() and len(leg) <= 2200:
                return leg.strip()
            ultimo = "legenda_instagram ausente, vazia ou longa demais"
        except ValueError as e:
            ultimo = str(e)
    raise ValueError(f"o modelo não entregou uma legenda válida ({ultimo})")


# ---------------- texto -> post, carrossel, hashtags ----------------
ESTRATEGIAS_AB = [
    "manchete em forma de pergunta; chamada para ação pedindo que comentem",
    "manchete com número ou lista curta; chamada para ação pedindo que salvem o post",
    "manchete provocativa e contraintuitiva; chamada para ação pedindo que compartilhem",
    "manchete com o benefício direto para o leitor; chamada para ação pedindo que sigam o perfil",
]
_STR = {"type": "string"}
_TAGS = {"type": "array", "items": _STR}
SCHEMA_POST = {"type": "object", "properties": {
    "manchete_curta": _STR, "texto_card": _STR, "legenda_instagram": _STR, "cta": _STR, "hashtags": _TAGS},
    "required": ["manchete_curta", "texto_card", "legenda_instagram", "cta", "hashtags"]}
SCHEMA_CARROSSEL = {"type": "object", "properties": {
    "slides": {"type": "array", "items": {"type": "object", "properties": {"titulo": _STR, "texto": _STR}, "required": ["titulo", "texto"]}},
    "legenda_instagram": _STR, "cta": _STR, "hashtags": _TAGS},
    "required": ["slides", "legenda_instagram", "cta", "hashtags"]}
SCHEMA_HASHTAGS = {"type": "object", "properties": {"hashtags": _TAGS}, "required": ["hashtags"]}

_REGRA_HASHTAGS = ("hashtags: 8 a 10, em português do Brasil, sem espaços e sem repetir: 3 de nicho (específicas, pouco disputadas), "
                   "3 de alcance médio e 2 a 4 amplas.")
INSTR_POST = f"""
Você escreve um post de Instagram (imagem com texto + legenda) a partir de uma ideia do autor, na voz dele (descrita acima).
Use SOMENTE o que a ideia traz e o que o perfil acima diz sobre o autor; não invente fatos, números ou histórias.
Responda SOMENTE com JSON:
- manchete_curta: até 10 palavras, vai em destaque no card.
- texto_card: 2 parágrafos curtos, primeira pessoa, até 450 caracteres no total.
- legenda_instagram: legenda completa SEM hashtags, até 1500 caracteres, terminando com a chamada para ação.
- cta: a chamada para ação usada no fim da legenda (uma frase).
- {_REGRA_HASHTAGS}
Português do Brasil.
""".strip()
INSTR_CARROSSEL = f"""
Você monta um carrossel de Instagram (vários slides de imagem com texto + legenda) a partir de uma ideia do autor, na voz dele (descrita acima).
Use SOMENTE o que a ideia traz e o que o perfil acima diz sobre o autor; não invente fatos, números ou histórias.
Responda SOMENTE com JSON:
- slides: lista com EXATAMENTE {{n}} slides. O 1º é a capa (titulo forte de até 10 palavras; texto = subtítulo curto de até 80 caracteres, pode ficar vazio).
  Do 2º ao penúltimo, cada slide desenvolve UMA ideia (titulo de até 8 palavras; texto de até 220 caracteres).
  O último fecha com a chamada para ação (titulo de até 8 palavras; texto de até 160 caracteres).
- legenda_instagram: legenda completa SEM hashtags, até 1200 caracteres, terminando com a chamada para ação.
- cta: a chamada para ação usada.
- {_REGRA_HASHTAGS}
Português do Brasil.
""".strip()


def normalizar_hashtags(tags) -> list[str]:
    out: list[str] = []
    for t in tags if isinstance(tags, list) else []:
        t = "#" + re.sub(r"[^\w]", "", str(t).replace("#", ""), flags=re.U)
        if len(t) > 1 and t.lower() not in [o.lower() for o in out]:
            out.append(t)
    return out[:10]


def montar_legenda(legenda: str, cta: str, tags: list[str]) -> str:
    leg = legenda.strip()
    if cta.strip() and cta.strip().lower()[:30] not in leg.lower():
        leg += "\n\n" + cta.strip()
    return leg + ("\n\n" + " ".join(tags) if tags else "")


def _estrategia(estrategia: str | None) -> str:
    return f"\n\nEstratégia desta versão: {estrategia}. Faça uma versão claramente diferente das outras versões da mesma ideia." if estrategia else ""


def _feedback(feedback: str | None) -> str:
    return f"\n\nA resposta anterior foi rejeitada: {feedback}. Corrija e responda de novo só com o JSON." if feedback else ""


async def post_de_texto(con: dict, contexto: str, ideia: str, temperature: float = 0.8, estrategia: str | None = None,
                        feedback: str | None = None) -> dict:
    """ValueError = saída inválida (vale tentar de novo); LLMError = conexão."""
    d = parse(await _chat(con, f"{contexto.strip()}\n\n---\n{INSTR_POST}", f"Ideia do autor:\n{ideia}{_estrategia(estrategia)}{_feedback(feedback)}",
                          temperature, SCHEMA_POST))
    for k in ("manchete_curta", "texto_card", "legenda_instagram", "cta"):
        if not isinstance(d.get(k), str) or not d[k].strip():
            raise ValueError(f"campo '{k}' ausente ou vazio")
    if len(d["manchete_curta"].split()) > 10:
        raise ValueError("manchete_curta com mais de 10 palavras")
    if len(d["texto_card"]) > 600:
        raise ValueError("texto_card com mais de 600 caracteres")
    tags = normalizar_hashtags(d.get("hashtags"))
    legenda = montar_legenda(d["legenda_instagram"], d["cta"], tags)
    if len(legenda) > 2200:
        raise ValueError("legenda com mais de 2200 caracteres")
    return {"manchete_curta": d["manchete_curta"].strip(), "texto_card": d["texto_card"].strip(), "cta": d["cta"].strip(),
            "hashtags": tags, "legenda": legenda}


async def carrossel_de_texto(con: dict, contexto: str, ideia: str, n_slides: int = 6, temperature: float = 0.8,
                             estrategia: str | None = None, feedback: str | None = None) -> dict:
    n = max(3, min(int(n_slides), 10))
    d = parse(await _chat(con, f"{contexto.strip()}\n\n---\n{INSTR_CARROSSEL.replace('{n}', str(n))}",
                          f"Ideia do autor:\n{ideia}{_estrategia(estrategia)}{_feedback(feedback)}", temperature, SCHEMA_CARROSSEL))
    slides = d.get("slides")
    if not isinstance(slides, list) or len(slides) != n:
        raise ValueError(f"o carrossel deve ter exatamente {n} slides")
    out = []
    for i, sl in enumerate(slides, 1):
        titulo, texto = str((sl or {}).get("titulo", "")).strip(), str((sl or {}).get("texto", "")).strip()
        if not titulo:
            raise ValueError(f"slide {i} sem titulo")
        if len(titulo.split()) > 12 or len(texto) > 320:
            raise ValueError(f"slide {i} longo demais (titulo até 10 palavras, texto até 220 caracteres)")
        out.append({"titulo": titulo, "texto": texto})
    for k in ("legenda_instagram", "cta"):
        if not isinstance(d.get(k), str) or not d[k].strip():
            raise ValueError(f"campo '{k}' ausente ou vazio")
    tags = normalizar_hashtags(d.get("hashtags"))
    legenda = montar_legenda(d["legenda_instagram"], d["cta"], tags)
    if len(legenda) > 2200:
        raise ValueError("legenda com mais de 2200 caracteres")
    return {"slides": out, "cta": d["cta"].strip(), "hashtags": tags, "legenda": legenda}


async def hashtags_para(con: dict, contexto: str, texto: str, temperature: float = 0.7) -> list[str]:
    system = (f"{contexto.strip()}\n\n---\nVocê sugere hashtags de Instagram para o texto do post abaixo, no nicho do autor. "
              f"Responda SOMENTE com JSON: {{\"hashtags\": [...]}}. {_REGRA_HASHTAGS}")
    ultimo = ""
    for _ in range(3):
        try:
            tags = normalizar_hashtags(parse(await _chat(con, system, f"Texto do post:\n{texto}{_feedback(ultimo)}", temperature, SCHEMA_HASHTAGS)).get("hashtags"))
            if len(tags) >= 3:
                return tags
            ultimo = "menos de 3 hashtags válidas"
        except ValueError as e:
            ultimo = str(e)
    raise ValueError(f"o modelo não entregou hashtags válidas ({ultimo})")


# ---------------- conversa de brainstorming (Telegram) ----------------
SCHEMA_AGENTE = {"type": "object", "properties": {
    "resposta": _STR, "acao": {"type": "string", "enum": ["conversar", "propor_perfil", "gerar", "definir_marca"]},
    "marca": {"type": "object", "properties": {"fundo": _STR, "texto": _STR, "acento": _STR, "fonte": _STR},
              "required": ["fundo", "texto", "acento", "fonte"]},
    "perfil_md": _STR, "palavras_chave": _STR, "horarios": _STR,
    "gerar": {"type": "object", "properties": {
        "formato": {"type": "string", "enum": ["feed", "story", "carrossel", "citacao", "meme"]}, "ideia": _STR,
        "n_slides": {"type": "integer"}, "variacoes": {"type": "integer"},
        "fundo": {"type": "string", "enum": ["nenhum", "banco"]}},
        "required": ["formato", "ideia", "n_slides", "variacoes", "fundo"]}},
    "required": ["resposta", "acao", "perfil_md", "palavras_chave", "horarios", "gerar", "marca"]}

INSTR_AGENTE = """
Você é o assistente de brainstorming e produção de conteúdo do Instagram do autor, conversando com ele pelo Telegram.
Seu trabalho tem duas partes: (1) montar e manter o perfil dele (quem é, tom, temas, mindset de postagem) e (2) fazer brainstorming de pautas e gerar os posts.

Como conversar:
- Português do Brasil, informal e direto, respostas curtas (até 600 caracteres), UMA pergunta por vez.
- Nunca invente fatos sobre o autor: use só o que ele disse aqui ou o que consta no perfil atual.
- Se o perfil atual está vazio ou curto, conduza uma entrevista antes de qualquer coisa: quem ele é e o que faz, para quem fala (público),
  tom de voz, temas que quer abordar e o que evita, no que acredita, objetivo com o Instagram, 3 a 5 textos reais dele (peça para colar),
  chamada para ação e hashtags que costuma usar, frequência e horários de postagem.
- Quando já houver informação suficiente (cerca de 5 respostas boas) ou quando ele pedir, use acao "propor_perfil": preencha perfil_md com o perfil
  COMPLETO em markdown, na estrutura "# Quem eu sou / # Temas que comento / # No que eu acredito / # O que eu critico / # Tom de voz /
  # Padrões que são meus / # Frases e jeitos que NUNCA uso / # Exemplos reais de textos meus / # Regras de saída", usando as palavras e os textos dele;
  palavras_chave com os temas separados por vírgula (usadas para filtrar notícias); horarios no formato HH:MM separados por vírgula, se ele disse (senão vazio).
  Em "resposta", resuma em poucas linhas e diga que ele confirma ou ajusta pelos botões. Ele NÃO salva nada sem confirmar.
- Para revisar um perfil existente, parta do perfil atual e proponha só o que mudou, mas devolva o perfil_md completo.
- Brainstorming: quando ele pedir ideias, proponha 3 a 5 ideias numeradas, cada uma com um ângulo em uma linha. Use os temas do perfil.
- Gerar: quando ele escolher uma ideia ou pedir um post, use acao "gerar" com gerar.ideia = a ideia completa e autossuficiente (inclua o ângulo escolhido e os pontos
  que ele deu), gerar.formato = feed, story ou carrossel (carrossel quando ele pedir carrossel/sequência/passo a passo; story quando pedir story),
  gerar.n_slides = 5 a 8 para carrossel (0 nos demais), gerar.variacoes = 1 a 3 (mais de 1 só quando ele pedir versões ou teste A/B).
  Em "resposta", diga em uma linha o que está gerando.
- Formatos extras de gerar.formato: "citacao" (card com uma frase forte; gerar.ideia = o tema ou a frase), e "meme" (foto do banco de imagens com texto
  em cima e embaixo; gerar.ideia = a situação engraçada). Para os dois, gerar.fundo = "banco" quando ele quiser uma foto de banco de imagens
  (sempre no meme; na citação só se ele pedir foto), senão "nenhum". Nos outros formatos, fundo = "nenhum".
- Marca visual: se ele falar de cores, fonte ou identidade visual, use acao "definir_marca" e preencha marca{fundo, texto, acento, fonte}: cores no formato
  #RRGGBB (deixe vazio o que ele não mudou) e fonte = sans (moderna), serif (clássica) ou mono (técnica). Em "resposta", confirme o que mudou.
  O logotipo ele envia como arquivo (não como foto comprimida) com a palavra "logo" na legenda.
- Em qualquer outra acao ("conversar"), deixe perfil_md, palavras_chave, horarios e marca vazios e gerar.ideia vazia.

Responda SOMENTE com JSON com os campos: resposta, acao, perfil_md, palavras_chave, horarios, marca{fundo, texto, acento, fonte}, gerar{formato, ideia, n_slides, variacoes, fundo}.
""".strip()


async def conversar(con: dict, perfil: dict, historico: list[dict], mensagem: str, temperature: float = 0.7) -> dict:
    """Um turno da conversa. Devolve o dict normalizado: resposta, acao, perfil_md, palavras_chave, horarios, gerar."""
    estado = (f"Perfil atual do autor (nome: {perfil.get('nome', '')}):\n"
              f"{(perfil.get('contexto_md') or '').strip() or '(vazio: ainda não foi montado)'}\n\n"
              f"Palavras-chave atuais: {perfil.get('palavras_chave') or '(nenhuma)'}\nHorários atuais: {perfil.get('horarios') or '(nenhum)'}")
    ultimo = ""
    for _ in range(3):
        try:
            raw = await _chat(con, f"{INSTR_AGENTE}\n\n=== ESTADO ===\n{estado}", mensagem + _feedback(ultimo), temperature,
                              SCHEMA_AGENTE, historico)
            d = parse(raw)
            if not isinstance(d.get("resposta"), str) or not d["resposta"].strip():
                raise ValueError("campo 'resposta' ausente ou vazio")
            acao = d.get("acao") if d.get("acao") in ("conversar", "propor_perfil", "gerar", "definir_marca") else "conversar"
            g = d.get("gerar") if isinstance(d.get("gerar"), dict) else {}
            fmt = g.get("formato") if g.get("formato") in ("feed", "story", "carrossel", "citacao", "meme") else "feed"
            mc = d.get("marca") if isinstance(d.get("marca"), dict) else {}
            ideia = str(g.get("ideia") or "").strip()
            perfil_md = str(d.get("perfil_md") or "").strip()
            if acao == "gerar" and len(ideia) < 8:
                raise ValueError("acao gerar sem gerar.ideia")
            if acao == "propor_perfil" and len(perfil_md) < 80:
                raise ValueError("acao propor_perfil sem perfil_md completo")
            return {"resposta": d["resposta"].strip(), "acao": acao, "perfil_md": perfil_md,
                    "palavras_chave": str(d.get("palavras_chave") or "").strip(), "horarios": str(d.get("horarios") or "").strip(),
                    "gerar": {"formato": fmt, "ideia": ideia, "n_slides": max(3, min(int(g.get("n_slides") or 6), 10)),
                              "variacoes": max(1, min(int(g.get("variacoes") or 1), len(ESTRATEGIAS_AB))),
                              "fundo": "banco" if g.get("fundo") == "banco" else "nenhum"},
                    "marca": {k: str(mc.get(k) or "").strip() for k in ("fundo", "texto", "acento", "fonte")}}
        except (ValueError, TypeError) as e:
            ultimo = str(e)
    raise ValueError(f"o modelo não respondeu no formato esperado ({ultimo})")


SCHEMA_TEXTO_STORY = {"type": "object", "properties": {"texto": _STR}, "required": ["texto"]}


async def texto_story(con: dict, contexto: str, pedido: str, temperature: float = 0.8) -> str:
    """Texto curto que aparece NA TELA do Story, no tom pedido pelo autor."""
    system = (f"{contexto.strip()}\n\n---\nVocê escreve o texto curto que aparece NA TELA de um Story de Instagram do próprio autor, "
              "em primeira pessoa e no tom dele, seguindo os pedidos de tom e assunto que ele fez. Máximo 100 caracteres, no máximo 2 frases curtas, "
              "sem hashtags, sem emoji, sem aspas. Use só o que ele contou; não invente fatos. "
              'Responda SOMENTE com JSON: {"texto": "..."}')
    ultimo = ""
    for _ in range(3):
        try:
            t = str(parse(await _chat(con, system, f"Pedido do autor: {pedido}{_feedback(ultimo)}", temperature, SCHEMA_TEXTO_STORY)).get("texto") or "").strip().strip('"')
            if 3 <= len(t) <= 140:
                return t
            ultimo = "texto vazio ou longo demais (máximo 100 caracteres)"
        except ValueError as e:
            ultimo = str(e)
    raise ValueError(f"o modelo não entregou um texto válido ({ultimo})")


SCHEMA_CITACAO = {"type": "object", "properties": {"frase": _STR, "autor": _STR, "legenda": _STR, "busca": _STR}, "required": ["frase", "autor", "legenda", "busca"]}
SCHEMA_MEME = {"type": "object", "properties": {"topo": _STR, "base": _STR, "legenda": _STR, "busca": _STR},
               "required": ["topo", "base", "legenda", "busca"]}


async def citacao_de_texto(con: dict, contexto: str, tema: str, temperature: float = 0.9) -> dict:
    """Frase curta e forte para um card de citação, na voz do autor (a menos que ele peça a frase de outra pessoa conhecida)."""
    system = (f"{contexto.strip()}\n\n---\nVocê cria um card de citação para o Instagram do autor. 'frase': uma frase forte, de até 160 caracteres, "
              "na voz dele, sem hashtags e sem aspas. Se o tema for uma frase de terceiros que ele colou, mantenha-a fiel e coloque o nome em 'autor'; "
              "senão 'autor' é o nome do próprio autor. Nunca invente citações de pessoas reais. 'legenda': 2 a 4 linhas comentando a frase, "
              "terminando com a chamada para ação dele, seguida de 5 a 8 hashtags. 'busca': 2 a 4 palavras EM INGLÊS para uma foto de fundo discreta "
              'no banco de imagens (paisagem, textura ou cena sem pessoas identificáveis). Responda SOMENTE com JSON: {"frase": "...", "autor": "...", "legenda": "...", "busca": "..."}')
    ultimo = ""
    for _ in range(3):
        try:
            d = parse(await _chat(con, system, f"Tema: {tema}{_feedback(ultimo)}", temperature, SCHEMA_CITACAO))
            frase, autor, leg = (str(d.get(k) or "").strip() for k in ("frase", "autor", "legenda"))
            if not (8 <= len(frase) <= 220):
                raise ValueError("frase vazia ou longa demais (máximo 160 caracteres)")
            if len(leg) < 10:
                raise ValueError("legenda ausente")
            return {"frase": frase.strip('"“”'), "autor": autor, "legenda": montar_legenda(leg, "", []), "busca": str(d.get("busca") or "").strip() or "calm landscape"}
        except ValueError as e:
            ultimo = str(e)
    raise ValueError(f"o modelo não entregou uma citação válida ({ultimo})")


async def meme_de_texto(con: dict, contexto: str, situacao: str, temperature: float = 0.9) -> dict:
    """Texto de cima e de baixo do meme, legenda e uma busca (em inglês) para achar a foto no banco de imagens."""
    system = (f"{contexto.strip()}\n\n---\nVocê cria um meme para o Instagram do autor. 'topo' e 'base': frases curtas (até 45 caracteres cada) "
              "que formam a piada (setup em cima, punchline embaixo); uma delas pode ficar vazia. 'busca': 2 a 4 palavras EM INGLÊS para achar a foto de fundo "
              "num banco de imagens (cena genérica e expressiva, sem celebridades). 'legenda': 1 a 3 linhas curtas com 5 a 8 hashtags. "
              'Responda SOMENTE com JSON: {"topo": "...", "base": "...", "legenda": "...", "busca": "..."}')
    ultimo = ""
    for _ in range(3):
        try:
            d = parse(await _chat(con, system, f"Situação: {situacao}{_feedback(ultimo)}", temperature, SCHEMA_MEME))
            topo, base, leg, busca = (str(d.get(k) or "").strip() for k in ("topo", "base", "legenda", "busca"))
            if not (topo or base) or max(len(topo), len(base)) > 70:
                raise ValueError("texto do meme vazio ou longo demais (máximo 45 caracteres por linha)")
            if len(leg) < 5:
                raise ValueError("legenda ausente")
            return {"topo": topo, "base": base, "legenda": montar_legenda(leg, "", []), "busca": busca or "funny reaction"}
        except ValueError as e:
            ultimo = str(e)
    raise ValueError(f"o modelo não entregou um meme válido ({ultimo})")


SCHEMA_ROTEIRO = {"type": "object", "properties": {"texto": _STR}, "required": ["texto"]}


async def roteiro_narracao(con: dict, contexto: str, pedido: str, temperature: float = 0.8) -> str:
    """Texto falado (voz em off) para um Story ou Reel curto, no tom do autor."""
    system = (f"{contexto.strip()}\n\n---\nVocê escreve o roteiro de narração (voz em off) de um Story/Reel curto do próprio autor, em primeira pessoa "
              "e no tom dele, seguindo o pedido. Entre 15 e 45 palavras, frases curtas e faladas, sem emoji, sem hashtags, sem aspas, sem indicações de cena. "
              "Use só o que ele contou; não invente fatos. "
              'Responda SOMENTE com JSON: {"texto": "..."}')
    ultimo = ""
    for _ in range(3):
        try:
            t = str(parse(await _chat(con, system, f"Pedido do autor: {pedido}{_feedback(ultimo)}", temperature, SCHEMA_ROTEIRO)).get("texto") or "").strip().strip('"')
            n = len(t.split())
            if 6 <= n <= 90:
                return t
            ultimo = "roteiro vazio ou fora do tamanho (15 a 45 palavras)"
        except ValueError as e:
            ultimo = str(e)
    raise ValueError(f"o modelo não entregou um roteiro válido ({ultimo})")


async def prompt_movimento(con: dict, pedido: str) -> str:
    """Prompt EM INGLÊS para o modelo de vídeo animar uma foto: só movimento sutil e realista, sem mudar quem aparece."""
    system = ("Você escreve prompts em inglês para um modelo de imagem-para-vídeo que anima UMA foto. Descreva só o movimento: câmera (push-in suave, pan lento, parallax) "
              "e movimentos naturais do que já está na foto (cabelo, tecido, luz, respiração). Não invente pessoas, objetos nem texto na cena; mantenha o rosto e a identidade. "
              "Até 60 palavras, uma frase só, vertical 9:16, estilo realista. Siga o pedido do autor sobre clima/tom. "
              'Responda SOMENTE com JSON: {"texto": "..."}')
    ultimo = ""
    for _ in range(3):
        try:
            t = str(parse(await _chat(con, system, f"Pedido do autor: {pedido}{_feedback(ultimo)}", 0.7, SCHEMA_ROTEIRO)).get("texto") or "").strip()
            if 5 <= len(t.split()) <= 90:
                return t
            ultimo = "prompt vazio ou fora do tamanho"
        except ValueError as e:
            ultimo = str(e)
    raise ValueError(f"o modelo não entregou um prompt válido ({ultimo})")
