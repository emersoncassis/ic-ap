"""Instagram Graph API (fluxo Facebook Login): publicar imagem e conferir a conta."""
import asyncio

import httpx

from . import config as C


class MetaError(Exception):
    pass


async def _graph(c: httpx.AsyncClient, method: str, path: str, token: str, **params):
    params["access_token"] = token
    r = await c.request(method, f"{C.IG_BASE}/{path}", params=params)
    try:
        data = r.json()
    except ValueError:
        raise MetaError(f"resposta inválida da Meta (HTTP {r.status_code})")
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", {})
        raise MetaError(f"{err.get('message', 'erro desconhecido')} (code {err.get('code')})")  # sem o token
    return data


def _params_midia(url: str, legenda: str, formato: str) -> dict:
    """feed: foto; story: imagem ou vídeo (sem legenda); reel: vídeo."""
    video = url.lower().endswith(".mp4")
    if formato == "story":
        return {"media_type": "STORIES", ("video_url" if video else "image_url"): url}
    if formato == "reel" or video:
        return {"media_type": "REELS", "video_url": url, "caption": legenda, "share_to_feed": "true"}
    return {"image_url": url, "caption": legenda}


async def publicar(ig_user_id: str, token: str, media_url: str, legenda: str, formato: str = "feed") -> str:
    async with httpx.AsyncClient(timeout=60) as c:
        cont = await _graph(c, "POST", f"{ig_user_id}/media", token, **_params_midia(media_url, legenda, formato))
        cid = cont["id"]
        for _ in range(C.IG_POLL_TRIES):
            st = (await _graph(c, "GET", cid, token, fields="status_code")).get("status_code")
            if st == "FINISHED":
                break
            if st in ("ERROR", "EXPIRED"):
                raise MetaError(f"container em {st}")
            await asyncio.sleep(C.IG_POLL_SECONDS)
        else:
            raise MetaError("container não ficou pronto a tempo")
        pub = await _graph(c, "POST", f"{ig_user_id}/media_publish", token, creation_id=cid)
    return pub["id"]


async def conferir(ig_user_id: str, token: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        conta = await _graph(c, "GET", ig_user_id, token, fields="username")
        lim = await _graph(c, "GET", f"{ig_user_id}/content_publishing_limit", token, fields="quota_usage,config")
    return {"username": conta.get("username"), "limite": lim.get("data", lim)}


async def token_longo(app_id: str, app_secret: str, token_curto: str) -> str:
    """Troca o token de usuário (curto) por um longo (~60 dias). O App Secret é usado só nesta chamada."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{C.IG_BASE}/oauth/access_token", params={
            "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": app_secret,
            "fb_exchange_token": token_curto})
    try:
        data = r.json()
    except ValueError:
        raise MetaError(f"resposta inválida da Meta (HTTP {r.status_code})")
    if r.status_code >= 400 or "access_token" not in data:
        raise MetaError(f"{data.get('error', {}).get('message', 'não foi possível trocar o token')}")
    return data["access_token"]


async def paginas(token_usuario: str) -> list[dict]:
    """Páginas do usuário que têm Instagram profissional ligado, com o token de cada Página."""
    async with httpx.AsyncClient(timeout=30) as c:
        d = await _graph(c, "GET", "me/accounts", token_usuario, limit=100,
                         fields="name,id,access_token,instagram_business_account{id,username}")
    res = []
    for p in d.get("data", []):
        igb = p.get("instagram_business_account")
        if igb:
            res.append({"id": p["id"], "nome": p["name"], "token": p["access_token"],
                        "ig_id": igb["id"], "ig_user": igb.get("username", "")})
    return res
