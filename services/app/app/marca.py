"""Kit de marca por perfil: cores, fonte e logotipo aplicados em todos os cards."""
import base64, json, re

from . import config as C, db

PADRAO = {"fundo": "#0e1116", "texto": "#f3f1ea", "acento": "#ff7a1a", "fonte": "sans"}
FONTES = {"sans": '"Inter","Segoe UI","Helvetica Neue",Arial,sans-serif',
          "serif": 'Georgia,"Times New Roman","DejaVu Serif",serif',
          "mono": 'ui-monospace,"SFMono-Regular",Consolas,"DejaVu Sans Mono",monospace'}
NOMES_FONTE = {"sans": "moderna (sem serifa)", "serif": "clássica (serifada)", "mono": "técnica (monoespaçada)"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_LOGO = 2 * 1024 * 1024


def _lum(h: str) -> float:
    def canal(i):
        v = int(h[i:i + 2], 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * canal(1) + 0.7152 * canal(3) + 0.0722 * canal(5)


def contraste(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def carregar(p: dict | None) -> dict:
    """Marca do perfil com os padrões onde nada foi definido."""
    try:
        d = json.loads((p or {}).get("marca") or "{}")
    except ValueError:
        d = {}
    m = dict(PADRAO)
    for k in ("fundo", "texto", "acento"):
        if isinstance(d.get(k), str) and HEX.match(d[k]):
            m[k] = d[k].lower()
    if d.get("fonte") in FONTES:
        m["fonte"] = d["fonte"]
    return m


def definir(perfil_id: int, **campos) -> tuple[dict, list[str]]:
    """Aplica as mudanças válidas e devolve (marca_nova, avisos). Texto e fundo precisam de contraste legível."""
    p = db.one("SELECT * FROM perfis WHERE id=?", (perfil_id,))
    atual = carregar(p)
    novo, avisos = dict(atual), []
    for k in ("fundo", "texto", "acento"):
        v = str(campos.get(k) or "").strip()
        if not v:
            continue
        if not v.startswith("#") and re.fullmatch(r"[0-9a-fA-F]{6}", v):
            v = "#" + v
        if HEX.match(v):
            novo[k] = v.lower()
        else:
            avisos.append(f"cor {k} inválida ({v}); use o formato #RRGGBB")
    f = str(campos.get("fonte") or "").strip().lower()
    if f:
        if f in FONTES:
            novo["fonte"] = f
        else:
            avisos.append(f"fonte {f} inválida (use: {', '.join(FONTES)})")
    if contraste(novo["fundo"], novo["texto"]) < 3.0:
        avisos.append("fundo e texto ficariam parecidos demais para ler: mantive as cores anteriores")
        novo["fundo"], novo["texto"] = atual["fundo"], atual["texto"]
    db.x("UPDATE perfis SET marca=? WHERE id=?", (json.dumps(novo), perfil_id))
    return novo, avisos


def _logo_path(perfil_id: int):
    for ext in ("png", "jpg", "webp"):
        f = C.MARCA / f"{perfil_id}.{ext}"
        if f.exists():
            return f
    return None


def salvar_logo(perfil_id: int, dados: bytes) -> str:
    if len(dados) > MAX_LOGO:
        raise ValueError("o logotipo passa de 2 MB")
    if dados[:8] == b"\x89PNG\r\n\x1a\n":
        ext = "png"
    elif dados[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    elif dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        ext = "webp"
    else:
        raise ValueError("formato de logotipo não aceito (use PNG, JPG ou WEBP)")
    remover_logo(perfil_id)
    C.MARCA.mkdir(parents=True, exist_ok=True)
    (C.MARCA / f"{perfil_id}.{ext}").write_bytes(dados)
    return ext


def remover_logo(perfil_id: int) -> None:
    for ext in ("png", "jpg", "webp"):
        (C.MARCA / f"{perfil_id}.{ext}").unlink(missing_ok=True)


def logo_uri(perfil_id: int) -> str | None:
    f = _logo_path(perfil_id)
    if not f:
        return None
    mime = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}[f.suffix[1:]]
    return f"data:{mime};base64," + base64.b64encode(f.read_bytes()).decode()


def contexto(p: dict | None, estilo: str | None = None) -> dict:
    """Variáveis para os templates: CSS da marca e logo. estilo 'claro' inverte fundo/texto; 'acento' usa a cor de destaque como fundo."""
    m = carregar(p)
    fundo, texto, acento = m["fundo"], m["texto"], m["acento"]
    if estilo == "claro":
        fundo, texto = texto, fundo
    elif estilo == "acento":
        fundo = acento
        texto = "#0b0d10" if contraste(acento, "#0b0d10") >= contraste(acento, "#ffffff") else "#ffffff"
        acento = texto
    css = (f":root{{--bg:{fundo};--fg:{texto};--acc:{acento};--mut:color-mix(in srgb,{texto} 58%,{fundo});"
           f"--line:color-mix(in srgb,{texto} 14%,{fundo});--body:color-mix(in srgb,{texto} 92%,{fundo})}}"
           f"html,body{{font-family:{FONTES[m['fonte']]}}}")
    return {"marca_css": css, "logo": logo_uri(p["id"]) if p else None}
