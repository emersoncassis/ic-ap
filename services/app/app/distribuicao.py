"""Distribuição Multiplataforma Local (Motor Próprio do ic-ap).

Substitui ferramentas de terceiros (como Upload-Post) por conectores diretos,
soberanos e sem custo adicional de intermediários para:
1. Threads (Meta Threads API oficial: texto, imagem, vídeo e carrossel)
2. YouTube Shorts (Google YouTube Data API v3: upload direto de MP4 com tag #Shorts)
3. LinkedIn (LinkedIn Community Management / Posts API: texto, imagem e vídeo)
4. TikTok (TikTok Content Posting API v2: publicação direta de vídeos)
"""
import asyncio
import json
import logging
from typing import Any

import httpx

from . import config as C, db

logger = logging.getLogger(__name__)

CANAIS_SUPORTADOS = {
    "threads": {
        "nome": "Threads",
        "formatos": ["feed", "reel", "carrossel"],
        "descricao": "Meta Threads API oficial (texto, fotos e vídeos curtos)",
        "docs": "https://developers.facebook.com/docs/threads",
    },
    "youtube": {
        "nome": "YouTube Shorts",
        "formatos": ["reel", "feed"],
        "descricao": "YouTube Data API v3 (vídeos verticais 9:16 com #Shorts)",
        "docs": "https://developers.google.com/youtube/v3",
    },
    "linkedin": {
        "nome": "LinkedIn",
        "formatos": ["feed", "reel", "carrossel"],
        "descricao": "LinkedIn Posts API v2 (texto, imagens e vídeos profissionais)",
        "docs": "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api",
    },
    "tiktok": {
        "nome": "TikTok",
        "formatos": ["reel"],
        "descricao": "TikTok Content Posting API v2 (vídeos e reels verticais)",
        "docs": "https://developers.tiktok.com/doc/content-posting-api-get-started",
    },
}


def _crypto_dec(val: str) -> str:
    """Decodifica chave criptografada de forma resiliente."""
    if not val:
        return ""
    try:
        from . import crypto
        return crypto.dec(val)
    except Exception:
        return val


def _crypto_enc(val: str) -> str:
    """Codifica chave com Fernet se disponível."""
    if not val:
        return ""
    try:
        from . import crypto
        return crypto.enc(val)
    except Exception:
        return val


# ---------------- Gestão de Canais no Banco ----------------


def listar_canais(perfil_id: int) -> list[dict[str, Any]]:
    """Lista todos os canais configurados para o perfil com status mascarado."""
    linhas = db.q("SELECT * FROM canais_distribuicao WHERE perfil_id=? ORDER BY canal", (perfil_id,))
    out = []
    for r in linhas:
        c = dict(r)
        tok = _crypto_dec(c.get("token_enc") or "")
        c["tem_token"] = bool(tok)
        c["token_mascarado"] = ("••••••••" + tok[-4:]) if len(tok) > 6 else ("••••" if tok else "")
        try:
            c["extra"] = json.loads(c.get("extra_json") or "{}")
        except Exception:
            c["extra"] = {}
        out.append(c)
    return out


def obter_canal(perfil_id: int, canal: str) -> dict[str, Any] | None:
    """Recupera as credenciais descriptografadas do canal."""
    r = db.one("SELECT * FROM canais_distribuicao WHERE perfil_id=? AND canal=?", (perfil_id, canal))
    if not r:
        return None
    d = dict(r)
    d["token"] = _crypto_dec(d.get("token_enc") or "")
    try:
        d["extra"] = json.loads(d.get("extra_json") or "{}")
    except Exception:
        d["extra"] = {}
    return d


def salvar_canal(
    perfil_id: int,
    canal: str,
    identificador: str,
    token: str,
    ativo: bool = True,
    extra: dict | None = None,
) -> None:
    """Salva ou atualiza as configurações do canal para o perfil."""
    canal = canal.lower().strip()
    if canal not in CANAIS_SUPORTADOS:
        raise ValueError(f"Canal '{canal}' não é suportado.")

    token_enc = _crypto_enc(token.strip()) if token.strip() else ""
    extra_json = json.dumps(extra or {})

    existente = db.one("SELECT id, token_enc FROM canais_distribuicao WHERE perfil_id=? AND canal=?", (perfil_id, canal))
    agora = db.now()
    if existente:
        tok_final = token_enc if token.strip() else existente["token_enc"]
        db.x(
            "UPDATE canais_distribuicao SET ativo=?, identificador=?, token_enc=?, extra_json=?, atualizado_em=? WHERE id=?",
            (1 if ativo else 0, identificador.strip(), tok_final, extra_json, agora, existente["id"]),
        )
    else:
        db.x(
            "INSERT INTO canais_distribuicao(perfil_id, canal, ativo, identificador, token_enc, extra_json, criado_em, atualizado_em)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (perfil_id, canal, 1 if ativo else 0, identificador.strip(), token_enc, extra_json, agora, agora),
        )


def remover_canal(perfil_id: int, canal: str) -> bool:
    """Remove a integração do canal com o perfil."""
    return db.x("DELETE FROM canais_distribuicao WHERE perfil_id=? AND canal=?", (perfil_id, canal)) > 0


def alternar_canal(perfil_id: int, canal: str) -> bool:
    """Ativa ou desativa o canal."""
    return db.x("UPDATE canais_distribuicao SET ativo=1-ativo, atualizado_em=? WHERE perfil_id=? AND canal=?", (db.now(), perfil_id, canal)) > 0


def canais_ativos(perfil_id: int) -> list[dict[str, Any]]:
    """Devolve apenas os canais ativos com tokens configurados."""
    todos = db.q("SELECT * FROM canais_distribuicao WHERE perfil_id=? AND ativo=1", (perfil_id,))
    ativos = []
    for r in todos:
        d = dict(r)
        tok = _crypto_dec(d.get("token_enc") or "")
        if tok:
            d["token"] = tok
            try:
                d["extra"] = json.loads(d.get("extra_json") or "{}")
            except Exception:
                d["extra"] = {}
            ativos.append(d)
    return ativos


def historico_publicacoes(post_id: int) -> list[dict[str, Any]]:
    """Retorna o histórico de publicações por canal para um post."""
    return db.q("SELECT * FROM publicacoes_canais WHERE post_id=? ORDER BY id DESC", (post_id,))


# ---------------- Testes de Conexão dos Canais ----------------


async def testar_canal(perfil_id: int, canal: str) -> dict[str, Any]:
    """Valida as credenciais configuradas diretamente na API de cada plataforma."""
    cfg = obter_canal(perfil_id, canal)
    if not cfg or not cfg.get("token"):
        return {"ok": False, "erro": f"Canal {canal} não configurado ou sem token."}

    token = cfg["token"]
    identificador = cfg.get("identificador") or ""

    async with httpx.AsyncClient(timeout=20) as c:
        try:
            if canal == "threads":
                user_id = identificador or "me"
                r = await c.get(f"https://graph.threads.net/v1.0/{user_id}", params={"access_token": token, "fields": "id,username,threads_profile_picture_url"})
                data = r.json()
                if r.status_code == 200 and "username" in data:
                    return {"ok": True, "detalhe": f"Conta @{data['username']} autenticada com sucesso no Threads."}
                return {"ok": False, "erro": data.get("error", {}).get("message", r.text[:150])}

            elif canal == "youtube":
                # Testa buscando o canal autenticado
                headers = {"Authorization": f"Bearer {token}"}
                r = await c.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"}, headers=headers)
                data = r.json()
                if r.status_code == 200 and data.get("items"):
                    tit = data["items"][0]["snippet"]["title"]
                    return {"ok": True, "detalhe": f"Canal '{tit}' autenticado no YouTube."}
                return {"ok": False, "erro": data.get("error", {}).get("message", r.text[:150])}

            elif canal == "linkedin":
                headers = {"Authorization": f"Bearer {token}", "X-Restli-Protocol-Version": "2.0.0"}
                r = await c.get("https://api.linkedin.com/v2/userinfo", headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    nome = data.get("name") or data.get("sub", "Usuário")
                    return {"ok": True, "detalhe": f"Perfil '{nome}' autenticado no LinkedIn."}
                return {"ok": False, "erro": f"LinkedIn HTTP {r.status_code}: {r.text[:150]}"}

            elif canal == "tiktok":
                headers = {"Authorization": f"Bearer {token}"}
                r = await c.get("https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name", headers=headers)
                data = r.json()
                if r.status_code == 200 and data.get("data", {}).get("user"):
                    u = data["data"]["user"].get("display_name", "Criador")
                    return {"ok": True, "detalhe": f"Perfil '{u}' autenticado no TikTok."}
                return {"ok": False, "erro": data.get("error", {}).get("message", r.text[:150])}

            return {"ok": False, "erro": f"Canal {canal} sem rotina de teste implementada."}

        except Exception as e:
            return {"ok": False, "erro": f"Falha na conexão com {canal}: {str(e)[:150]}"}


# ---------------- Conectores Nativos de Publicação ----------------


async def _publicar_threads(
    c: httpx.AsyncClient,
    identificador: str,
    token: str,
    post: dict,
    arqs: list[str],
    base_url: str,
) -> str:
    """Publica no Threads via Meta Graph API oficial (texto, imagem, vídeo ou carrossel)."""
    user_id = identificador or "me"
    legenda = post.get("legenda") or post.get("texto") or ""
    formato = post.get("formato") or "feed"
    primeiro_arq = arqs[0] if arqs else ""
    eh_video = primeiro_arq.lower().endswith(".mp4")

    # 1. Carrossel no Threads (2 a 10 imagens)
    if formato == "carrossel" and len(arqs) >= 2:
        filhos = []
        for a in arqs[:10]:
            u_img = f"{base_url}/{a}"
            rc = await c.post(
                f"https://graph.threads.net/v1.0/{user_id}/threads",
                params={"access_token": token, "media_type": "IMAGE", "image_url": u_img, "is_carousel_item": "true"},
            )
            data_c = rc.json()
            if rc.status_code >= 400 or "id" not in data_c:
                raise RuntimeError(f"Erro item carrossel Threads: {data_c}")
            filhos.append(data_c["id"])

        # Container carrossel pai
        r_pai = await c.post(
            f"https://graph.threads.net/v1.0/{user_id}/threads",
            params={"access_token": token, "media_type": "CAROUSEL", "children": ",".join(filhos), "text": legenda},
        )
        data_pai = r_pai.json()
        if r_pai.status_code >= 400 or "id" not in data_pai:
            raise RuntimeError(f"Erro container carrossel Threads: {data_pai}")
        container_id = data_pai["id"]

    # 2. Imagem ou Vídeo único
    elif arqs:
        media_url = f"{base_url}/{primeiro_arq}"
        params = {"access_token": token, "text": legenda}
        if eh_video:
            params["media_type"] = "VIDEO"
            params["video_url"] = media_url
        else:
            params["media_type"] = "IMAGE"
            params["image_url"] = media_url

        r = await c.post(f"https://graph.threads.net/v1.0/{user_id}/threads", params=params)
        data = r.json()
        if r.status_code >= 400 or "id" not in data:
            raise RuntimeError(f"Erro container Threads: {data}")
        container_id = data["id"]

    # 3. Apenas Texto
    else:
        r = await c.post(
            f"https://graph.threads.net/v1.0/{user_id}/threads",
            params={"access_token": token, "media_type": "TEXT", "text": legenda},
        )
        data = r.json()
        if r.status_code >= 400 or "id" not in data:
            raise RuntimeError(f"Erro texto Threads: {data}")
        container_id = data["id"]

    # Espera se for vídeo
    if eh_video:
        for _ in range(30):
            await asyncio.sleep(2)
            chk = await c.get(f"https://graph.threads.net/v1.0/{container_id}", params={"access_token": token, "fields": "status"})
            if chk.json().get("status") == "FINISHED":
                break

    # Publicação final do container
    r_pub = await c.post(
        f"https://graph.threads.net/v1.0/{user_id}/threads_publish",
        params={"access_token": token, "creation_id": container_id},
    )
    pub_data = r_pub.json()
    if r_pub.status_code >= 400 or "id" not in pub_data:
        raise RuntimeError(f"Erro ao publicar Threads: {pub_data}")

    return pub_data["id"]


async def _publicar_youtube(
    c: httpx.AsyncClient,
    identificador: str,
    token: str,
    post: dict,
    arqs: list[str],
    base_url: str,
    extra: dict,
) -> str:
    """Publica no YouTube Shorts (vídeo vertical MP4)."""
    primeiro_arq = arqs[0] if arqs else ""
    if not primeiro_arq.lower().endswith(".mp4"):
        raise ValueError("YouTube Shorts aceita apenas vídeos MP4.")

    caminho_local = C.CARDS / primeiro_arq
    if not caminho_local.exists():
        raise FileNotFoundError(f"Arquivo local não encontrado: {caminho_local}")

    legenda = post.get("legenda") or post.get("texto") or ""
    primeira_linha = legenda.split("\n")[0][:80].strip() or "Novo Conteúdo"
    if "#Shorts" not in primeira_linha:
        titulo = f"{primeira_linha} #Shorts"[:100]
    else:
        titulo = primeira_linha[:100]

    privacidade = extra.get("privacy_status", "public")

    snippet = {
        "title": titulo,
        "description": f"{legenda}\n\n#Shorts #video",
        "tags": ["Shorts", "Reels", "Brasil"],
        "categoryId": "28",  # Ciência e Tecnologia
    }
    status = {"privacyStatus": privacidade, "selfDeclaredMadeForKids": False}

    metadata = json.dumps({"snippet": snippet, "status": status})

    # Inicia Resumable Upload
    init_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(caminho_local.stat().st_size),
    }

    r_init = await c.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers=init_headers,
        content=metadata,
    )
    if r_init.status_code not in (200, 201):
        raise RuntimeError(f"Erro ao iniciar upload no YouTube: {r_init.text[:200]}")

    upload_url = r_init.headers.get("Location")
    if not upload_url:
        raise RuntimeError("YouTube não retornou Location para upload do vídeo.")

    # Envia os bytes do arquivo de vídeo local
    with open(caminho_local, "rb") as f_video:
        r_upload = await c.put(
            upload_url,
            headers={"Content-Type": "video/mp4"},
            content=f_video.read(),
        )

    data = r_upload.json()
    if r_upload.status_code not in (200, 201) or "id" not in data:
        raise RuntimeError(f"Erro ao enviar vídeo para o YouTube: {data}")

    return data["id"]


async def _publicar_linkedin(
    c: httpx.AsyncClient,
    identificador: str,
    token: str,
    post: dict,
    arqs: list[str],
    base_url: str,
) -> str:
    """Publica no LinkedIn via Posts API v2 (texto, imagem única ou vídeo)."""
    author = identificador.strip()
    if not author.startswith("urn:li:"):
        # Se veio apenas o número ou ID, assume pessoa física
        author = f"urn:li:person:{author}"

    legenda = post.get("legenda") or post.get("texto") or ""
    primeiro_arq = arqs[0] if arqs else ""
    caminho_local = (C.CARDS / primeiro_arq) if primeiro_arq else None

    headers = {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": "202401",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }

    content_payload = None

    # 1. Upload de Imagem no LinkedIn
    if caminho_local and caminho_local.exists() and primeiro_arq.lower().endswith((".jpg", ".jpeg", ".png")):
        init_body = {"initializeUploadRequest": {"owner": author}}
        r_init = await c.post("https://api.linkedin.com/rest/images?action=initializeUpload", headers=headers, json=init_body)
        init_data = r_init.json()
        if r_init.status_code not in (200, 201) or "value" not in init_data:
            raise RuntimeError(f"Falha ao registrar imagem no LinkedIn: {init_data}")

        upload_url = init_data["value"]["uploadUrl"]
        image_urn = init_data["value"]["image"]

        with open(caminho_local, "rb") as f_img:
            r_up = await c.put(upload_url, headers={"Authorization": f"Bearer {token}"}, content=f_img.read())
            if r_up.status_code not in (200, 201):
                raise RuntimeError(f"Falha no upload binário de imagem para LinkedIn: HTTP {r_up.status_code}")

        content_payload = {"media": {"id": image_urn}}

    # 2. Upload de Vídeo no LinkedIn
    elif caminho_local and caminho_local.exists() and primeiro_arq.lower().endswith(".mp4"):
        init_body = {"initializeUploadRequest": {"owner": author, "fileSizeBytes": caminho_local.stat().st_size}}
        r_init = await c.post("https://api.linkedin.com/rest/videos?action=initializeUpload", headers=headers, json=init_body)
        init_data = r_init.json()
        if r_init.status_code not in (200, 201) or "value" not in init_data:
            raise RuntimeError(f"Falha ao registrar vídeo no LinkedIn: {init_data}")

        upload_url = init_data["value"]["uploadInstructions"][0]["uploadUrl"]
        video_urn = init_data["value"]["video"]

        with open(caminho_local, "rb") as f_vid:
            r_up = await c.put(upload_url, headers={"Authorization": f"Bearer {token}"}, content=f_vid.read())
            if r_up.status_code not in (200, 201):
                raise RuntimeError(f"Falha no upload binário de vídeo para LinkedIn: HTTP {r_up.status_code}")

        content_payload = {"media": {"id": video_urn}}

    # Criação do Post
    post_payload = {
        "author": author,
        "commentary": legenda,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
    }
    if content_payload:
        post_payload["content"] = content_payload

    r_post = await c.post("https://api.linkedin.com/rest/posts", headers=headers, json=post_payload)
    if r_post.status_code not in (200, 201):
        raise RuntimeError(f"Erro ao criar post no LinkedIn: {r_post.text[:200]}")

    post_urn = r_post.headers.get("x-restli-id") or r_post.text[:100]
    return post_urn


async def _publicar_tiktok(
    c: httpx.AsyncClient,
    identificador: str,
    token: str,
    post: dict,
    arqs: list[str],
    base_url: str,
    extra: dict,
) -> str:
    """Publica no TikTok via Content Posting API v2."""
    primeiro_arq = arqs[0] if arqs else ""
    if not primeiro_arq.lower().endswith(".mp4"):
        raise ValueError("TikTok aceita apenas publicação de vídeos em formato MP4.")

    video_url = f"{base_url}/{primeiro_arq}"
    legenda = post.get("legenda") or post.get("texto") or ""
    privacy = extra.get("privacy_level", "PUBLIC_TO_EVERYONE")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    body = {
        "post_info": {
            "title": legenda[:150],
            "privacy_level": privacy,
            "disable_duet": False,
            "disable_stitch": False,
            "disable_comment": False,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "video_url": video_url,
        },
    }

    r = await c.post("https://open.tiktokapis.com/v2/post/publish/video/init/", headers=headers, json=body)
    data = r.json()
    if r.status_code != 200 or data.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"Erro ao publicar no TikTok: {data}")

    return data["data"]["publish_id"]


# ---------------- Orquestrador de Publicação Multiplataforma ----------------


async def publicar_multiplataforma(post_id: int, perfil_id: int, base_url: str) -> dict[str, Any]:
    """Dispara a publicação para todos os canais adicionais configurados e ativos no perfil."""
    canais = canais_ativos(perfil_id)
    if not canais:
        return {"sucessos": [], "falhas": [], "pulados": []}

    po = db.one("SELECT * FROM posts WHERE id=?", (post_id,))
    if not po:
        return {"sucessos": [], "falhas": [], "pulados": []}

    # Coleta arquivos do post
    arqs = [po["arquivo"]] if po.get("arquivo") else []
    if po.get("arquivos"):
        arqs = [a.strip() for a in po["arquivos"].split(",") if a.strip()]

    sucessos = []
    falhas = []
    pulados = []

    async with httpx.AsyncClient(timeout=90) as c:
        for canal_info in canais:
            canal = canal_info["canal"]
            token = canal_info["token"]
            identificador = canal_info.get("identificador") or ""
            extra = canal_info.get("extra") or {}

            # Verifica compatibilidade de formato
            espec = CANAIS_SUPORTADOS.get(canal, {})
            primeiro_arq = arqs[0] if arqs else ""
            eh_video = primeiro_arq.lower().endswith(".mp4")

            # TikTok e YouTube Shorts exigem vídeo
            if canal in ("tiktok", "youtube") and not eh_video:
                pulados.append(f"{espec.get('nome', canal)} (requer vídeo)")
                continue

            try:
                external_id = ""
                if canal == "threads":
                    external_id = await _publicar_threads(c, identificador, token, po, arqs, base_url)
                elif canal == "youtube":
                    external_id = await _publicar_youtube(c, identificador, token, po, arqs, base_url, extra)
                elif canal == "linkedin":
                    external_id = await _publicar_linkedin(c, identificador, token, po, arqs, base_url)
                elif canal == "tiktok":
                    external_id = await _publicar_tiktok(c, identificador, token, po, arqs, base_url, extra)

                # Salva registro com sucesso
                db.x(
                    "INSERT INTO publicacoes_canais(post_id, canal, status, external_id, detalhe, criado_em)"
                    " VALUES(?,?,?,?,?,?)",
                    (post_id, canal, "sucesso", str(external_id), "Publicado com sucesso via conector local", db.now()),
                )
                db.log(perfil_id, post_id, f"publicado_{canal}", f"id={external_id}")
                sucessos.append(espec.get("nome", canal))
                logger.info(f"Post #{post_id} publicado com sucesso em {canal} (id={external_id})")

            except Exception as e:
                msg_erro = str(e)[:250]
                db.x(
                    "INSERT INTO publicacoes_canais(post_id, canal, status, external_id, detalhe, criado_em)"
                    " VALUES(?,?,?,?,?,?)",
                    (post_id, canal, "falhou", "", msg_erro, db.now()),
                )
                db.log(perfil_id, post_id, f"falhou_{canal}", msg_erro)
                falhas.append(f"{espec.get('nome', canal)}: {msg_erro}")
                logger.error(f"Erro ao publicar post #{post_id} em {canal}: {e}")

    return {
        "sucessos": sucessos,
        "falhas": falhas,
        "pulados": pulados,
    }
