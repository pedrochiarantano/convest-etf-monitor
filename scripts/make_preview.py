"""Gera o PREVIEW.html: uma versão autocontida do dashboard, com uma amostra
dos dados embutida, que abre com DUPLO-CLIQUE (sem precisar de servidor).

Uso (na raiz do projeto):
    python scripts/make_preview.py

Ele lê docs/index.html + docs/data/*.json, injeta um "shim" que serve esses
dados sem rede (contornando a restrição de file:// do navegador) e grava
PREVIEW.html na raiz. Reflete sempre a versão atual do dashboard."""
import os, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IDX = os.path.join(ROOT, "docs", "index.html")
DATA = os.path.join(ROOT, "docs", "data")
OUT = os.path.join(ROOT, "PREVIEW.html")

SAMPLE = 200  # nº de ativos embutidos (mantém o arquivo leve)

def load(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return "{}"
    txt = open(p, encoding="utf-8").read().strip()
    return txt or "{}"

def sample_latest(js, n=SAMPLE):
    try:
        obj = json.loads(js)
    except Exception:
        return js
    if isinstance(obj, dict) and isinstance(obj.get("assets"), list) and len(obj["assets"]) > n:
        obj["assets"] = obj["assets"][:n]
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return js

def main():
    h = open(IDX, encoding="utf-8").read()
    L = sample_latest(load("latest.json"))
    H = load("holdings.json")
    S = load("sparklines.json")
    shim = (
        "<script>window.__L=%s;window.__H=%s;window.__S=%s;const _f=window.fetch;"
        "window.fetch=(u,o)=>{u=String(u);"
        "if(u.includes('latest.json'))return Promise.resolve({ok:true,json:()=>Promise.resolve(window.__L)});"
        "if(u.includes('holdings.json'))return Promise.resolve({ok:true,json:()=>Promise.resolve(window.__H)});"
        "if(u.includes('sparklines.json'))return Promise.resolve({ok:true,json:()=>Promise.resolve(window.__S)});"
        "return _f(u,o);};</script>"
    ) % (L, H, S)
    out = h.replace("</head>", shim + "\n</head>")
    open(OUT, "w", encoding="utf-8").write(out)
    print(f"PREVIEW.html gerado ({len(out)//1024} KB) em {OUT}")

if __name__ == "__main__":
    main()
