"""Módulo Meta AI: Executa pesquisa no Instagram e a técnica Blow Up via navegador (Playwright).

Acessa o https://www.meta.ai com a sessão autenticada do usuário (cookies/perfil persistente),
pesquisa tendências, perfis e links do Instagram e aplica a técnica Blow Up para criar
conteúdo viral tangível (manchete, card visual e legenda de alta retenção).
"""
import asyncio
import json
import logging
import re
from typing import Any

from . import config as C, llm

logger = logging.getLogger(__name__)

_META_AI_LOCK = asyncio.Lock()

PROMPT_BLOW_UP = """
Analise este link ou tema do Instagram utilizando a técnica Blow Up:
{instagram_url}

Contexto e Tom de Voz do meu perfil:
{contexto_autor}

Por favor, execute o método Blow Up completo:
1. RAIO-X DO GANCHO (HOOK): Qual técnica psicológica e visual foi usada nos primeiros 3 segundos para reter o público?
2. ANÁLISE DE VIRALIZAÇÃO: Por que esse conteúdo explodiu? (Padrões de retenção, quebra de expectativa, gatilhos de salvamento e compartilhamento).
3. ESTRUTURA CENA A CENA: Desconstrução do ritmo, cortes e elementos visuais/auditivos.
4. VERSÃO BLOW UP ADAPTADA PARA MIM:
   - Novo Hook irresistível (máximo 125 caracteres, pronto para o Instagram)
   - Roteiro / Carrossel completo com o mesmo formato vencedor, aplicado ao meu nicho e tom de voz
   - Legenda de alta conversão com 1 CTA claro e 3 a 5 hashtags estratégicas
""".strip()

PROMPT_GERAR_POST_BLOW_UP = """
Pesquise no Instagram e nas tendências atuais para o perfil @{handle} ({nome}).
Contexto do perfil: {contexto_autor}

Pedido enviado no Telegram: "{pedido}"
Formato desejado: {formato}

Aplique a TÉCNICA BLOW UP: pegue uma situação real, tendência quente do Instagram, notícia ou erro concreto ligado ao pedido, dê um zoom (blow up) no detalhe invisível que gera uma consequência gigante e vire para a solução/autoridade do perfil @{handle}.

Responda em português do Brasil preenchendo EXATAMENTE os blocos abaixo (sem omitir nenhum):
[MANCHETE]: (título curto, forte e explosivo de até 9 palavras em português para a capa do card)
[SUBTITULO]: (2 a 3 frases diretas em português revelando o Blow Up e a virada de autoridade para o card)
[DESTAQUES]: (2 ou 3 palavras exatas da manchete separadas por vírgula para destacar em neon)
[DADO]: (um número, valor, multa, artigo de lei ou métrica de impacto curto, ex: R$ 50 MIL ou 100% OFFLINE)
[ITENS]: (3 pontos curtos e práticos separados por | mostrando o passo a passo ou raio-X)
[LAYOUT]: (escolha 1: impacto_foto, editorial, alerta, dado ou lista)
[IMAGEM_INGLES]: (4 a 6 palavras em inglês descrevendo uma fotografia cinematográfica para o fundo deste tema, ex: cybersecurity server room dark neon)
[CTA]: (chamada para ação curta e magnética, ex: Comente PRIVADA ou Responda no Direct)
[LEGENDA]:
(escreva aqui a legenda completa em português pronta para postar no Instagram no estilo Blow Up, com gancho forte na 1ª linha, desenvolvimento direto, CTA e 4 hashtags estratégicas no final)
""".strip()


def extrair_link_instagram(texto: str) -> str | None:
    """Detecta URL de post, reel ou story do Instagram no texto."""
    padrao = r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels|tv|stories)/[A-Za-z0-9_-]+/?(?:\?[^\s]*)?"
    match = re.search(padrao, texto)
    return match.group(0) if match else None


def normalizar_cookies(cookies_raw: str) -> list[dict[str, Any]]:
    """Converte cookies em formato JSON ou string de cabeçalho 'k=v; k2=v2' para a lista do Playwright."""
    txt = (cookies_raw or "").strip()
    if not txt:
        return []

    # 1. Tenta formato JSON (ex.: exportado de Cookie-Editor ou EditThisCookie)
    if txt.startswith("[") and txt.endswith("]"):
        try:
            arr = json.loads(txt)
            normalizados = []
            for c in arr:
                if isinstance(c, dict) and "name" in c and "value" in c:
                    normalizados.append({
                        "name": str(c["name"]),
                        "value": str(c["value"]),
                        "domain": str(c.get("domain") or ".meta.ai"),
                        "path": str(c.get("path") or "/"),
                        "secure": bool(c.get("secure", True)),
                        "sameSite": "Lax",
                    })
            return normalizados
        except Exception:
            pass

    # 2. Formato chave=valor; chave2=valor2
    resultado = []
    partes = txt.split(";")
    for p in partes:
        if "=" in p:
            k, v = p.strip().split("=", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                resultado.append({
                    "name": k,
                    "value": v,
                    "domain": ".meta.ai",
                    "path": "/",
                    "secure": True,
                    "sameSite": "Lax",
                })
    return resultado


def _limpar_locks_orfaos(perfil_dir) -> None:
    """Remove locks órfãos do Chromium caso uma execução anterior tenha sido interrompida."""
    for nome_lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (perfil_dir / nome_lock).unlink(missing_ok=True)
        except Exception:
            pass


async def _consultar_meta_ai_navegador(prompt_completo: str, timeout_segundos: int = 90) -> str:
    """Envia um prompt diretamente para o https://www.meta.ai autenticado com os cookies do usuário."""
    from . import settings
    cookies_salvos = settings.segredo("meta_ai_cookies")
    cookies_lista = normalizar_cookies(cookies_salvos)
    if not cookies_lista:
        raise RuntimeError("Nenhum cookie do Meta AI configurado.")

    perfil_dir = C.DATA / "meta_ai_profile"
    perfil_dir.mkdir(parents=True, exist_ok=True)

    async with _META_AI_LOCK:
        _limpar_locks_orfaos(perfil_dir)
        pw = None
        browser_context = None
        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            browser_context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(perfil_dir),
                executable_path=C.CHROMIUM,
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"],
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            await browser_context.add_cookies(cookies_lista)
            page = await browser_context.new_page()
            await page.goto("https://www.meta.ai", wait_until="domcontentloaded", timeout=25000)

            # No meta.ai existe um <textarea> oculto antes do <div role="textbox" contenteditable="true">.
            # Por isso usamos get_by_role("textbox").first que mira diretamente no editor Lexical visível.
            composer = page.get_by_role("textbox").first
            try:
                await composer.wait_for(state="visible", timeout=15000)
            except Exception:
                html_preview = await page.content()
                if "log in" in html_preview.lower() or "entrar" in html_preview.lower():
                    raise RuntimeError("Sessão do Meta AI não está logada. Atualize os cookies em Conexões.")
                raise RuntimeError("Caixa de entrada visível do Meta AI não encontrada.")

            await composer.click()
            body_antes = await page.inner_text("body")
            linhas_sidebar_antigas = {ln.strip() for ln in body_antes.splitlines() if len(ln.strip()) > 15}
            # Substitui quebras de linha por espaço/ponto para o editor Lexical não enviar antes da hora
            prompt_linear = re.sub(r"\s*\n+\s*", " | ", prompt_completo.strip())
            ancora_prompt = prompt_linear[-65:].strip()
            await page.keyboard.insert_text(prompt_linear)
            await page.wait_for_timeout(350)
            await page.keyboard.press("Enter")
            logger.info("Prompt enviado ao Meta AI no navegador. Aguardando resposta...")

            await page.wait_for_timeout(3500)
            iteracoes = max(12, int(timeout_segundos / 2))
            ultimo_candidato = ""
            estavel_cont = 0

            for _ in range(iteracoes):
                await page.wait_for_timeout(2000)
                # Se houver bloco de código recolhido ("lines hidden"), expande
                try:
                    btn_hidden = page.get_by_text(re.compile(r"\d+\s+lines?\s+hidden", re.I)).first
                    if await btn_hidden.count() > 0:
                        await btn_hidden.click(timeout=1000)
                except Exception:
                    pass

                body = await page.inner_text("body")
                # Corta estritamente APÓS o balão do nosso prompt enviado (nunca usa 'Today' da sidebar!)
                candidato = ""
                if "Show thinking" in body:
                    candidato = body.split("Show thinking")[-1].strip()
                elif ancora_prompt and ancora_prompt in body:
                    pos_ancora = body.rfind(ancora_prompt)
                    candidato = body[pos_ancora + len(ancora_prompt):].strip()
                elif "[MANCHETE]" in body:
                    pos_m = body.rfind("[MANCHETE]")
                    if pos_m > body.find(prompt_linear[:35]):
                        candidato = body[pos_m:].strip()

                # Remove rodapé da interface do Meta AI e linhas que já existiam na sidebar antes do envio
                for marcador_fim in ("\nAsk Meta AI...", "\nThinking", "\nSources\n"):
                    if marcador_fim in candidato:
                        candidato = candidato.split(marcador_fim)[0].strip()

                if candidato:
                    linhas_limpas = [
                        ln for ln in candidato.splitlines()
                        if ln.strip() not in linhas_sidebar_antigas
                        and not ln.strip().startswith(("TLDR —", "Account and posts from"))
                    ]
                    candidato = "\n".join(linhas_limpas).strip()

                # Ignora estados transitórios de raciocínio do Meta AI
                primeira_linha = (candidato.split("\n")[0] if candidato else "").strip()
                em_raciocinio = (
                    "Show thinking" not in body and (
                        len(candidato) < 140 or
                        any(primeira_linha.startswith(p) for p in (
                            "Researching", "Drafting", "Thinking", "Searching", "Analyzing",
                            "Looking up", "Checking", "Pulling", "Creating", "Generating"
                        ))
                    )
                )
                if em_raciocinio:
                    continue

                if len(candidato) >= 120:
                    if candidato == ultimo_candidato:
                        estavel_cont += 1
                        if estavel_cont >= 1:
                            return candidato
                    else:
                        ultimo_candidato = candidato
                        estavel_cont = 0

            if ultimo_candidato:
                return ultimo_candidato
            raise RuntimeError("Tempo limite excedido aguardando a resposta completa do Meta AI.")
        finally:
            if browser_context:
                try:
                    await browser_context.close()
                except Exception:
                    pass
            if pw:
                try:
                    await pw.stop()
                except Exception:
                    pass


def _limpar_tags_e_markdown(s: str) -> str:
    """Remove qualquer tag residual [MANCHETE], [LAYOUT], [CTA], [LEGENDA] e asteriscos de markdown."""
    if not s:
        return ""
    s = re.sub(r"(?im)^\s*\*{0,2}\[[A-Z_]+\]\*{0,2}\s*:?.*$", "", s)
    s = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", s)
    s = re.sub(r"^Code\s*\n", "", s, flags=re.I)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def _parsear_blocos_blow_up(texto_bruto: str, pedido: str, formato: str) -> dict[str, Any]:
    """Extrai campos estruturados da resposta do Meta AI e garante que o texto da legenda esteja representado no card."""
    txt = (texto_bruto or "").strip()

    def _extrair_tag(nome_tag: str, ate_fim: bool = False) -> str:
        if ate_fim:
            padrao = rf"\*{{0,2}}\[{nome_tag}\]\*{{0,2}}\s*:?\s*(.+)$"
            m = re.search(padrao, txt, flags=re.I | re.S)
        else:
            padrao = rf"\*{{0,2}}\[{nome_tag}\]\*{{0,2}}\s*:?\s*(.+?)(?=\n\s*\*{{0,2}}\[[A-Z_]+\]|\Z)"
            m = re.search(padrao, txt, flags=re.I | re.S)
        return m.group(1).strip() if m else ""

    manchete = _limpar_tags_e_markdown(_extrair_tag("MANCHETE")).strip('"\'* ')
    teve_tag_manchete = bool(manchete)
    subtitulo = _limpar_tags_e_markdown(_extrair_tag("SUBTITULO"))
    destaques_raw = _extrair_tag("DESTAQUES")
    dado = _limpar_tags_e_markdown(_extrair_tag("DADO"))
    itens_raw = _extrair_tag("ITENS")
    imagem_ingles = _limpar_tags_e_markdown(_extrair_tag("IMAGEM_INGLES")).strip('"\'* ')
    cta = _limpar_tags_e_markdown(_extrair_tag("CTA"))
    legenda_bruta = _extrair_tag("LEGENDA", ate_fim=True)
    legenda = _limpar_tags_e_markdown(legenda_bruta)

    linhas = [
        _limpar_tags_e_markdown(ln).strip()
        for ln in txt.splitlines()
        if _limpar_tags_e_markdown(ln).strip()
        and not ln.strip().startswith(("Ask Meta AI", "TLDR —", "Account and posts"))
    ]

    if not manchete:
        for ln in linhas:
            if any(k in ln.upper() for k in ("HOOK", "MANCHETE", "TÍTULO", "TITULO")) and ":" in ln:
                manchete = ln.split(":", 1)[1].strip('"\'* ')
                break
        if not manchete and linhas:
            manchete = re.sub(r"^[#*0-9.\-\s]+", "", linhas[0]).strip('"\'* ')[:90]

    if not legenda:
        if "Legenda" in txt or "legenda" in txt:
            partes_leg = re.split(r"Legenda[^:\n]*:\s*", txt, maxsplit=1, flags=re.I)
            if len(partes_leg) > 1:
                legenda = _limpar_tags_e_markdown(partes_leg[1])
        if not legenda:
            corpo_livre = "\n\n".join(ln for ln in linhas[1:] if len(ln) > 25)
            legenda = f"{manchete}\n\n{corpo_livre[:900]}\n\n#privateai #ia #seguranca #tecnologia".strip()

    # Garante que o texto do card (subtitulo/corpo) represente diretamente o conteúdo real da legenda!
    linhas_legenda_sem_hash = [
        ln.strip() for ln in legenda.splitlines()
        if ln.strip() and not ln.strip().startswith("#") and ln.strip().upper() != manchete.upper()
    ]
    resumo_da_legenda = "\n\n".join(linhas_legenda_sem_hash[:2])[:340]
    if not subtitulo or len(subtitulo) < 45 or subtitulo.upper() == manchete.upper():
        subtitulo = resumo_da_legenda or f"Análise prática: {pedido[:140]}"

    itens = [
        _limpar_tags_e_markdown(it).strip(" -•*")
        for it in re.split(r"\||\n", itens_raw)
        if _limpar_tags_e_markdown(it).strip(" -•*")
    ] if itens_raw else []

    palavras_destaque = [p.strip('"\'* ') for p in destaques_raw.split(",") if p.strip('"\'* ')]
    if not palavras_destaque and manchete:
        palavras_m = [w for w in manchete.split() if len(w) > 3]
        palavras_destaque = [" ".join(palavras_m[:2])] if palavras_m else []

    # Sempre usa o novo template fotográfico contextual com a legenda sobreposta
    layout = "impacto_foto"

    if not cta:
        cta = "Responda no Direct" if formato == "story" else "Comente aqui embaixo"
    if formato == "story" and "legenda" in cta.lower():
        cta = "Responda no Direct"

    busca_contextual = imagem_ingles or f"{manchete} {subtitulo[:80]} {pedido[:60]}"

    return {
        "manchete": manchete[:110],
        "corpo": subtitulo[:340],
        "palavras_destaque": palavras_destaque[:3],
        "dado_destaque": dado[:30],
        "itens_card": itens[:3],
        "layout": layout,
        "imagem_ingles": busca_contextual,
        "cta": cta[:50],
        "legenda": legenda[:2100],
        "teve_tag_manchete": teve_tag_manchete,
        "texto_bruto_meta_ai": txt,
    }


async def gerar_post_blow_up(
    pedido: str,
    perfil: dict[str, Any],
    formato: str = "feed",
) -> dict[str, Any]:
    """Usa o Meta AI autenticado (com cookie do usuário) para pesquisar no Instagram e gerar um post Blow Up completo."""
    handle = (perfil.get("handle") or "emery.carvalho").lstrip("@")
    nome = perfil.get("nome") or "Emerson Carvalho"
    contexto_autor = (perfil.get("contexto_md") or "").strip() or (
        "Especialista em Segurança Eletrônica, Network Servers, Storage Centers e Private AI. "
        "Padrão visual escuro com verde neon #00FF88 / ciano e técnica Blow Up."
    )
    prompt = PROMPT_GERAR_POST_BLOW_UP.format(
        handle=handle,
        nome=nome,
        contexto_autor=contexto_autor[:600],
        pedido=pedido,
        formato=formato.upper(),
    )

    try:
        resposta_meta = await _consultar_meta_ai_navegador(prompt, timeout_segundos=90)
        dados = _parsear_blocos_blow_up(resposta_meta, pedido=pedido, formato=formato)
        # Se a resposta veio sem a tag [MANCHETE] ou com texto curto/inválido, estrutura via LLM usando a pesquisa do Meta AI
        if not dados.get("teve_tag_manchete") or len(dados.get("manchete", "")) < 8:
            fb = await _fallback_blow_up_llm(
                pedido,
                perfil,
                f"{prompt}\n\nPESQUISA CAPTURADA NO META AI:\n{resposta_meta[:1800]}",
                "formatacao_blocos",
            )
            if fb.get("ok"):
                dados_fb = _parsear_blocos_blow_up(fb.get("analise_blow_up", ""), pedido=pedido, formato=formato)
                if dados_fb.get("manchete"):
                    dados = dados_fb
        return {
            "ok": True,
            "origem": "meta.ai_navegador",
            **dados,
        }
    except Exception as e:
        logger.warning(f"Meta AI navegador indisponível ({e}); acionando fallback de geração Blow Up...")
        fb = await _fallback_blow_up_llm(pedido, perfil, prompt, str(e))
        if fb.get("ok"):
            dados = _parsear_blocos_blow_up(fb.get("analise_blow_up", ""), pedido=pedido, formato=formato)
            return {
                "ok": True,
                "origem": "fallback_llm",
                "aviso": fb.get("aviso"),
                **dados,
            }
        return {"ok": False, "erro": fb.get("erro", str(e))}


async def executar_blow_up(instagram_url: str, perfil: dict[str, Any]) -> dict[str, Any]:
    """Executa a técnica Blow Up acessando o meta.ai no navegador Playwright."""
    contexto_autor = (perfil.get("contexto_md") or "").strip() or f"Nome: {perfil.get('nome', 'Autor')}"
    prompt_completo = PROMPT_BLOW_UP.format(
        instagram_url=instagram_url,
        contexto_autor=contexto_autor[:600],
    )
    try:
        resposta_texto = await _consultar_meta_ai_navegador(prompt_completo, timeout_segundos=55)
        return {
            "ok": True,
            "origem": "meta.ai_navegador",
            "url_analisada": instagram_url,
            "analise_blow_up": resposta_texto.strip(),
        }
    except Exception as e:
        logger.error(f"Erro na execução via navegador meta.ai: {e}")
        return await _fallback_blow_up_llm(instagram_url, perfil, prompt_completo, str(e))


async def _fallback_blow_up_llm(instagram_url: str, perfil: dict[str, Any], prompt: str, motivo_erro: str) -> dict[str, Any]:
    """Fallback executado pelo LLM do perfil caso o navegador/cookies do meta.ai falhem."""
    con = None
    try:
        from . import pipeline
        con = pipeline.conexao_do_perfil(perfil)
    except Exception:
        con = None

    if not con or not con.get("modelo"):
        return {
            "ok": False,
            "origem": "erro",
            "erro": f"Meta AI no navegador falhou ({motivo_erro[:150]}) e não há modelo LLM configurado como fallback.",
        }

    system = (
        "Você é um especialista em engenharia reversa de conteúdo viral no Instagram e na técnica Blow Up.\n"
        "Responda em texto estruturado com os blocos [MANCHETE], [SUBTITULO], [DESTAQUES], [DADO], [ITENS], [LAYOUT], [CTA] e [LEGENDA]."
    )
    try:
        raw = await llm._chat(con, system, prompt, temperature=0.7)
        # Se o modelo retornou JSON do schema padrão, converte para blocos legíveis
        texto_saida = raw.strip()
        if texto_saida.startswith("{"):
            try:
                j = json.loads(texto_saida)
                manchete_j = j.get("manchete_curta") or j.get("manchete") or ""
                reacao_j = j.get("minha_reacao") or j.get("corpo") or ""
                legenda_j = j.get("legenda_instagram") or j.get("legenda") or ""
                if manchete_j or legenda_j:
                    texto_saida = (
                        f"[MANCHETE]: {manchete_j}\n"
                        f"[SUBTITULO]: {reacao_j}\n"
                        f"[LAYOUT]: impacto_foto\n"
                        f"[CTA]: Comente aqui\n"
                        f"[LEGENDA]:\n{legenda_j}"
                    )
            except Exception:
                pass
        return {
            "ok": True,
            "origem": "fallback_llm",
            "url_analisada": instagram_url,
            "analise_blow_up": texto_saida,
            "aviso": f"⚠️ Executado via LLM reserva ({con['modelo']}).",
        }
    except Exception as e:
        return {
            "ok": False,
            "origem": "erro",
            "erro": f"Meta AI no navegador falhou ({motivo_erro[:100]}) e o fallback de LLM também falhou: {e}",
        }


async def testar_sessao() -> dict[str, Any]:
    """Testa se os cookies do meta.ai estão salvos e se a sessão responde no navegador."""
    from . import settings
    cookies_salvos = settings.segredo("meta_ai_cookies")
    cookies_lista = normalizar_cookies(cookies_salvos)
    if not cookies_lista:
        return {"ok": False, "erro": "Nenhum cookie salvo. Exporte os cookies do meta.ai e cole no formulário acima."}

    pw = None
    browser_context = None
    perfil_dir = C.DATA / "meta_ai_profile"
    perfil_dir.mkdir(parents=True, exist_ok=True)
    async with _META_AI_LOCK:
        _limpar_locks_orfaos(perfil_dir)
        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            browser_context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(perfil_dir),
                executable_path=C.CHROMIUM,
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"],
                viewport={"width": 1280, "height": 800},
            )
            await browser_context.add_cookies(cookies_lista)
            page = await browser_context.new_page()
            await page.goto("https://www.meta.ai", wait_until="domcontentloaded", timeout=20000)
            composer = page.get_by_role("textbox").first
            await composer.wait_for(state="visible", timeout=12000)
            return {"ok": True, "detalhe": "Sessão do Meta AI autenticada e caixa de pesquisa ativa com sucesso!"}
        except Exception as e:
            return {"ok": False, "erro": f"Falha ao validar sessão do Meta AI: {str(e)[:200]}"}
        finally:
            if browser_context:
                try:
                    await browser_context.close()
                except Exception:
                    pass
            if pw:
                try:
                    await pw.stop()
                except Exception:
                    pass


PROMPT_ANALISE_PERFIL = """
Faça uma análise profunda e estratégica do perfil do Instagram: {identificador}

Por favor, elabore um raio-X completo deste criador/marca com base nas regras do Instagram (2026):
1. NICHO & POSICIONAMENTO: Qual é a especialidade central, autoridade e proposta de valor?
2. TOM DE VOZ & ESTILO: Como a pessoa se comunica? (Ritmo, formalidade, energia, gatilhos).
3. PILARES DE CONTEÚDO & TEMAS: Quais são os 3 a 5 grandes temas que mais geram retenção?
4. DORES & DESEJOS DO PÚBLICO: O que a audiência busca e o que mais gera salvamentos e compartilhamentos?
5. PALAVRAS-CHAVE ESTRATÉGICAS: Liste de 8 a 12 termos essenciais para monitorar tendências quentes do nicho.
6. IDEIAS BLOW UP RECOMENDADAS: Que tipo de conteúdo e ganchos esse perfil deve postar para viralizar?
""".strip()


async def analisar_perfil_remoto(identificador: str, perfil: dict[str, Any]) -> dict[str, Any]:
    """Extrai análise de perfil diretamente do meta.ai no navegador ou via LLM de fallback."""
    prompt_completo = PROMPT_ANALISE_PERFIL.format(identificador=identificador)
    try:
        resposta_texto = await _consultar_meta_ai_navegador(prompt_completo, timeout_segundos=55)
        return {
            "ok": True,
            "origem": "meta.ai_navegador",
            "relatorio": resposta_texto.strip(),
        }
    except Exception as e:
        logger.warning(f"Meta AI no navegador falhou ao analisar perfil ({e}). Executando fallback via LLM...")
        return await _fallback_analise_perfil_llm(identificador, perfil, prompt_completo, str(e))


async def _fallback_analise_perfil_llm(
    identificador: str,
    perfil: dict[str, Any],
    prompt: str,
    motivo_erro: str,
) -> dict[str, Any]:
    """Fallback via LLM do perfil caso o navegador/cookies do Meta AI não estejam ativos."""
    con = None
    try:
        from . import pipeline
        con = pipeline.conexao_do_perfil(perfil)
    except Exception:
        con = None

    if not con or not con.get("modelo"):
        return {
            "ok": False,
            "origem": "erro",
            "erro": f"Meta AI no navegador indisponível ({motivo_erro[:120]}) e nenhum modelo LLM configurado.",
        }

    system = (
        "Você é um estrategista sênior de Instagram e especialista em análise de posicionamento e autoridade.\n"
        "Com base no identificador/perfil informado e contexto disponível, construa um raio-X completo com:\n"
        "1. Nicho & Posicionamento\n"
        "2. Tom de Voz & Estilo (2026)\n"
        "3. Pilares de Conteúdo\n"
        "4. Palavras-Chave Estratégicas\n"
        "5. Ideias Blow Up Recomendadas."
    )
    try:
        raw = await llm._chat(con, system, prompt, temperature=0.7)
        return {
            "ok": True,
            "origem": "fallback_llm",
            "relatorio": raw.strip(),
            "aviso": f"Análise gerada via LLM ({con['modelo']}). Para usar o Meta AI oficial direto do navegador, configure os cookies em Conexões.",
        }
    except Exception as e:
        return {
            "ok": False,
            "origem": "erro",
            "erro": f"Falha na extração remota do Meta AI ({motivo_erro[:100]}) e no fallback de LLM: {e}",
        }
