"""Preenche best-effort o TER (taxa) e o patrimônio (AUM) dos ETFs que não têm
esses dados (tipicamente os importados do FinanceDatabase), buscando no Yahoo
Finance (Ticker.info). Cobertura é parcial — o Yahoo nem sempre expõe os dois.

Só toca em linhas com TER e/ou patrimônio em branco (nunca sobrescreve o que veio
do JustETF). É incremental: registra o que já tentou em data/enrich_done.csv e só
re-tenta após REFRESH_DAYS. Rode no workflow do universo (mensal) ou localmente:
    python scripts/enrich_metadata.py         # ou: python scripts/enrich_metadata.py 300
"""
import os, csv, io, sys, time, datetime as dt
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
UNIVERSE = os.path.join(DATA, "universe.csv")
MAP = os.path.join(DATA, "symbol_map.csv")
CACHE = os.path.join(DATA, "enrich_done.csv")
REFRESH_DAYS = 90

COLS = ["isin", "ticker", "name", "ac", "region", "sector", "ter", "size", "cur",
        "dist", "repl", "dom", "ytd", "y1", "y3", "vol", "div", "nh"]

def read_rows(path):
    if not os.path.exists(path):
        return []
    raw = open(path, "rb").read().decode("utf-8", "replace").replace("\x00", "")
    return list(csv.DictReader(io.StringIO(raw)))

def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    rows = read_rows(UNIVERSE)
    sym_by_isin = {r["isin"]: r["yahoo_symbol"] for r in read_rows(MAP)
                   if r.get("yahoo_symbol")}
    cache = {r["isin"]: r.get("fetched", "") for r in read_rows(CACHE)}
    today = dt.date.today().isoformat()
    cutoff = (dt.date.today() - dt.timedelta(days=REFRESH_DAYS)).isoformat()

    targets = [r for r in rows
               if (not r.get("ter") or not r.get("size"))
               and r["isin"] in sym_by_isin
               and cache.get(r["isin"], "") < cutoff]
    if limit:
        targets = targets[:limit]
    print(f"universo: {len(rows)} | a enriquecer: {len(targets)}")

    filled_ter = filled_size = 0
    for i, r in enumerate(targets):
        sym = sym_by_isin[r["isin"]]
        info = {}
        try:
            info = yf.Ticker(sym).info or {}
        except Exception:
            pass
        ter = info.get("annualReportExpenseRatio") or info.get("netExpenseRatio")
        aum = info.get("totalAssets")
        if ter is not None and not r.get("ter"):
            r["ter"] = round(float(ter), 3); filled_ter += 1
        if aum and not r.get("size"):
            r["size"] = int(round(float(aum) / 1e6))  # em milhões, como o JustETF
            filled_size += 1
        cache[r["isin"]] = today
        if i % 50 == 0:
            _save(rows, cache); print(f"  ...{i}/{len(targets)}")
        time.sleep(0.15)

    _save(rows, cache)
    print(f"TER preenchidos: {filled_ter} | patrimônio preenchidos: {filled_size}")

def _save(rows, cache):
    with open(UNIVERSE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLS})
    with open(CACHE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["isin", "fetched"])
        w.writeheader()
        for isin, d in cache.items():
            w.writerow({"isin": isin, "fetched": d})

if __name__ == "__main__":
    main()
