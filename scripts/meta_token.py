#!/usr/bin/env python3
"""Ajuda com o token do Instagram (fluxo Facebook Login). Só biblioteca padrão.

  python scripts/meta_token.py exchange   # token curto -> token longo de usuário (~60 dias)
  python scripts/meta_token.py pages      # lista Páginas, tokens de Página e o IG_USER_ID ligado
  python scripts/meta_token.py check      # confere o token e o limite de publicação

Variáveis lidas do ambiente: META_APP_ID, META_APP_SECRET, SHORT_TOKEN (exchange),
USER_TOKEN (pages), IG_ACCESS_TOKEN e IG_USER_ID (check).
A saída contém segredos: rode só na sua máquina e cole no .env, nunca em chat ou commit.
"""
import json, os, sys, urllib.parse, urllib.request, urllib.error

BASE = f"https://graph.facebook.com/{os.getenv('IG_GRAPH_VERSION', 'v23.0')}"


def get(path, **params):
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Erro da Meta: {json.load(e).get('error', {}).get('message')}")


def need(*names):
    miss = [n for n in names if not os.getenv(n)]
    if miss:
        sys.exit("Faltam variáveis: " + ", ".join(miss))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "exchange":
        need("META_APP_ID", "META_APP_SECRET", "SHORT_TOKEN")
        d = get("oauth/access_token", grant_type="fb_exchange_token", client_id=os.environ["META_APP_ID"],
                client_secret=os.environ["META_APP_SECRET"], fb_exchange_token=os.environ["SHORT_TOKEN"])
        print("USER_TOKEN (longo, ~60 dias):", d["access_token"])
    elif cmd == "pages":
        need("USER_TOKEN")
        d = get("me/accounts", fields="name,id,access_token,instagram_business_account", access_token=os.environ["USER_TOKEN"])
        for p in d.get("data", []):
            ig = (p.get("instagram_business_account") or {}).get("id", "(sem Instagram ligado)")
            print(f"Página: {p['name']} ({p['id']})\n  IG_USER_ID: {ig}\n  IG_ACCESS_TOKEN (Página): {p['access_token']}\n")
    elif cmd == "check":
        need("IG_ACCESS_TOKEN", "IG_USER_ID")
        t, ig = os.environ["IG_ACCESS_TOKEN"], os.environ["IG_USER_ID"]
        print("Conta:", get(ig, fields="username,followers_count", access_token=t))
        print("Limite de publicação:", get(f"{ig}/content_publishing_limit", fields="quota_usage,config", access_token=t))
    else:
        print(__doc__)


main()
