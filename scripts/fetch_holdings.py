"""Coleta a composição (top-10 posições) e a alocação setorial de cada ETF via
Yahoo Finance (yfinance.funds_data) e grava docs/data/holdings.json, consumido
pelo modal de detalhes do dashboard.

Roda SEMANALMENTE (composição muda devagar) e é incremental/retomável: só
re-busca fundos cujo dado tem mais de REFRESH_DAYS. Muitos ETFs de renda fixa
não expõem holdings no Yahoo — nesses casos o registro fica vazio (o modal
mostra 'composição indisponível')."""
import csv, os, sys, json, time, datetime as dt
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UNIVERSE = os.path.join(ROOT, "data", "universe.csv")
MAP = os.path.join(ROOT, "data", "symbol_map.csv")
OUT = os.path.join(ROOT, "docs", "data", "holdings.json")
REFRESH_DAYS = 7

def load_resolved():
    uni = {r["isin"] for r in csv.DictReader(open(UNIVERSE, encoding="utf-8"))}
    out = []
    if os.path.exists(MAP):
        for r in csv.DictReader(open(MAP, encoding="utf-8")):
            if r.get("yahoo_symbol") and r["isin"] in uni:
                out.append((r["isin"], r["yahoo_symbol"]))
    return out

def fetch_one(sym):
    rec = {"symbol": sym, "holdings": [], "sectors": {}}
    fd = yf.Ticker(sym).funds_data
    try:
        th = fd.top_holdings
        if th is not None and len(th):
            for symh, row in th.iterrows():
                rec["holdings"].append({
                    "symbol": str(symh),
                    "name": str(row.get("Name", "") or ""),
                    "pct": round(float(row.get("Holding Percent", 0) or 0), 5),
                })
    except Exception:
        pass
    try:
        sw = fd.sector_weightings
        if sw:
            rec["sectors"] = {k: round(float(v), 4) for k, v in sw.items()}
    except Exception:
        pass
    return rec

def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    resolved = load_resolved()
    if limit:
        resolved = resolved[:limit]
    data = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    today = dt.date.today().isoformat()
    cutoff = (dt.date.today() - dt.timedelta(days=REFRESH_DAYS)).isoformat()

    n = 0
    for isin, sym in resolved:
        e = data.get(isin)
        if e and e.get("fetched", "") >= cutoff:
            continue  # ainda fresco
        try:
            rec = fetch_one(sym)
        except Exception:
            rec = {"symbol": sym, "holdings": [], "sectors": {}}
        rec["fetched"] = today
        data[isin] = rec
        n += 1
        if n % 50 == 0:
            json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
            print(f"  {n} fundos atualizados...")
        time.sleep(0.2)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    withh = sum(1 for v in data.values() if v.get("holdings"))
    print(f"holdings.json: {len(data)} fundos ({withh} com composição), {n} atualizados nesta rodada, "
          f"{os.path.getsize(OUT)//1024} KB")

if __name__ == "__main__":
    main()
