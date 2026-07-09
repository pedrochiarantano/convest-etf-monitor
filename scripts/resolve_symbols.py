"""Resolve cada ISIN/ticker do universo para um símbolo válido do Yahoo Finance.
Estratégia (barata e resiliente):
  1. Testa candidatos por sufixo de bolsa em lote (.DE Xetra é o padrão do JustETF).
  2. Para os que sobrarem, usa a busca por ISIN da API do Yahoo.
Mantém cache incremental em data/symbol_map.csv — só resolve o que ainda falta,
então rodar de novo é rápido e retomável."""
import csv, os, sys, time, json
import yfinance as yf
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UNIVERSE = os.path.join(ROOT, "data", "universe.csv")
MAP = os.path.join(ROOT, "data", "symbol_map.csv")

# Ordem de tentativa de bolsas (sufixo Yahoo). Xetra primeiro.
SUFFIXES = [".DE", ".L", ".AS", ".MI", ".SW", ".PA", ".DE"]
BATCH = 120

def load_universe():
    with open(UNIVERSE, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def load_map():
    if not os.path.exists(MAP):
        return {}
    with open(MAP, encoding="utf-8") as f:
        return {r["isin"]: r for r in csv.DictReader(f)}

def save_map(m):
    cols = ["isin", "ticker", "yahoo_symbol", "status"]
    with open(MAP, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in m.values():
            w.writerow({k: r.get(k, "") for k in cols})

def batch_validate(symbols):
    """Devolve o conjunto de símbolos que retornaram preço no último mês."""
    good = set()
    for i in range(0, len(symbols), BATCH):
        chunk = symbols[i:i + BATCH]
        try:
            df = yf.download(chunk, period="1mo", progress=False,
                             auto_adjust=True, threads=True)
        except Exception as e:
            print("  download erro:", str(e)[:80]); continue
        if df is None or df.empty:
            continue
        try:
            close = df["Close"]
        except Exception:
            continue
        cols = close.columns if hasattr(close, "columns") else [chunk[0]]
        for s in chunk:
            try:
                if s in cols and close[s].dropna().shape[0] > 0:
                    good.add(s)
            except Exception:
                pass
        time.sleep(0.5)
    return good

def yahoo_search_isin(isin):
    """Fallback: busca o símbolo primário pela API de busca do Yahoo."""
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    try:
        r = requests.get(url, params={"q": isin, "quotesCount": 6, "newsCount": 0},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        quotes = r.json().get("quotes", [])
        etfs = [q for q in quotes if q.get("quoteType") == "ETF" and q.get("symbol")]
        pool = etfs or [q for q in quotes if q.get("symbol")]
        # prioriza bolsas europeias líquidas
        pref = {"GER": 0, "LSE": 1, "AMS": 2, "MIL": 3, "EBS": 4, "PAR": 5}
        pool.sort(key=lambda q: pref.get(q.get("exchange", ""), 9))
        return pool[0]["symbol"] if pool else ""
    except Exception:
        return ""

def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    uni = load_universe()
    if limit:
        uni = uni[:limit]
    m = load_map()

    pending = [r for r in uni if r["isin"] not in m or not m[r["isin"]].get("yahoo_symbol")]
    print(f"universo={len(uni)}  já resolvidos={len(uni)-len(pending)}  pendentes={len(pending)}")

    # Passo 1: tentativa por sufixo, em lote
    for suf in dict.fromkeys(SUFFIXES):
        still = [r for r in pending if r["isin"] not in m or not m[r["isin"]].get("yahoo_symbol")]
        if not still:
            break
        cand = {r["ticker"] + suf: r for r in still if r["ticker"]}
        print(f"testando sufixo {suf}: {len(cand)} candidatos")
        good = batch_validate(list(cand.keys()))
        for sym in good:
            r = cand[sym]
            m[r["isin"]] = {"isin": r["isin"], "ticker": r["ticker"],
                            "yahoo_symbol": sym, "status": "suffix"}
        save_map(m)
        print(f"  resolvidos neste passo: {len(good)}")

    # Passo 2: busca por ISIN para o que restou
    still = [r for r in pending if r["isin"] not in m or not m[r["isin"]].get("yahoo_symbol")]
    print(f"busca por ISIN para {len(still)} restantes")
    for i, r in enumerate(still):
        sym = yahoo_search_isin(r["isin"])
        status = "isin_search" if sym else "unresolved"
        m[r["isin"]] = {"isin": r["isin"], "ticker": r["ticker"],
                        "yahoo_symbol": sym, "status": status}
        if i % 50 == 0:
            save_map(m); print(f"  ...{i}/{len(still)}")
        time.sleep(0.25)
    save_map(m)

    resolved = sum(1 for r in uni if m.get(r["isin"], {}).get("yahoo_symbol"))
    print(f"TOTAL resolvido: {resolved}/{len(uni)} ({100*resolved/len(uni):.1f}%)")

if __name__ == "__main__":
    main()
