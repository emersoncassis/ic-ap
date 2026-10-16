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


async def publicar(ig_user_id: str, token: str, image_url: str, legenda: str) -> str:
    async with httpx.AsyncClient(timeout=60) as c:
        cont = await _graph(c, "POST", f"{ig_user_id}/media", token, image_url=image_url, caption=legenda)
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
