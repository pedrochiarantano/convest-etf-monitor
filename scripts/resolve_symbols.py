"""Resolve cada ISIN/ticker do universo para um símbolo válido do Yahoo Finance.
Estratégia (barata e resiliente):
  1. Testa candidatos por sufixo de bolsa em lote (.DE Xetra é o padrão do JustETF),
     ACEITANDO apenas séries com dado real (rejeita séries "mortas"/defasadas).
  2. Para os que sobrarem (ou marcados 'recheck' por terem série defasada), usa a
     busca por ISIN do Yahoo e valida o candidato antes de aceitar.
Mantém cache incremental em data/symbol_map.csv. Entradas sem dado real utilizável
ficam com status 'no_data' e não são re-tentadas indefinidamente."""
import csv, os, sys, time
import yfinance as yf
import requests
import indicators as ind

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UNIVERSE = os.path.join(ROOT, "data", "universe.csv")
MAP = os.path.join(ROOT, "data", "symbol_map.csv")

# Ordem de tentativa de bolsas (sufixo Yahoo). Xetra primeiro.
SUFFIXES = [".DE", ".L", ".AS", ".MI", ".SW", ".PA"]
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

def is_pending(m, isin):
    """Pendente = ainda sem símbolo e não marcado como 'sem dado' (evita loop)."""
    e = m.get(isin)
    if not e:
        return True
    if e.get("yahoo_symbol"):
        return False
    return e.get("status") != "no_data"

def _series(df, sym):
    try:
        close = df["Close"]
    except Exception:
        return None
    cols = close.columns if hasattr(close, "columns") else [sym]
    if sym not in cols:
        return None
    s = close[sym].dropna()
    return s if len(s) else None

def batch_validate(symbols):
    """Devolve os símbolos com série REAL (com dado e não degenerada)."""
    good = set()
    for i in range(0, len(symbols), BATCH):
        chunk = symbols[i:i + BATCH]
        try:
            df = yf.download(chunk, period="6mo", progress=False,
                             auto_adjust=True, threads=True)
        except Exception as e:
            print("  download erro:", str(e)[:80]); continue
        if df is None or df.empty:
            continue
        for s in chunk:
            ser = _series(df, s)
            if ser is not None and not ind.degenerate(ser):
                good.add(s)
        time.sleep(0.5)
    return good

def validate_symbol(sym):
    """Valida um símbolo individual (usado na busca por ISIN)."""
    try:
        df = yf.download(sym, period="6mo", progress=False,
                         auto_adjust=True, threads=False)
        ser = _series(df, sym)
        return ser is not None and not ind.degenerate(ser)
    except Exception:
        return False

def yahoo_search_isin(isin):
    """Devolve lista ordenada de símbolos candidatos para o ISIN (bolsas líquidas primeiro)."""
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    try:
        r = requests.get(url, params={"q": isin, "quotesCount": 10, "newsCount": 0},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        quotes = r.json().get("quotes", [])
    except Exception:
        return []
    etfs = [q for q in quotes if q.get("quoteType") == "ETF" and q.get("symbol")]
    pool = etfs or [q for q in quotes if q.get("symbol")]
    # Stuttgart (STU/.SG) costuma ser defasada — despriorizada
    pref = {"GER": 0, "LSE": 1, "AMS": 2, "PAR": 3, "MIL": 4, "EBS": 5, "STU": 8}
    pool.sort(key=lambda q: pref.get(q.get("exchange", ""), 6))
    return [q["symbol"] for q in pool]

def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    uni = load_universe()
    if limit:
        uni = uni[:limit]
    m = load_map()

    pending = [r for r in uni if is_pending(m, r["isin"])]
    print(f"universo={len(uni)}  resolvidos={len(uni)-len(pending)}  pendentes/recheck={len(pending)}")

    # Passo 1: tentativa por sufixo, em lote (só aceita série real)
    for suf in SUFFIXES:
        still = [r for r in pending if is_pending(m, r["isin"])]
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

    # Passo 2: busca por ISIN (com validação) para o que restou
    still = [r for r in pending if is_pending(m, r["isin"])]
    print(f"busca por ISIN para {len(still)} restantes")
    for i, r in enumerate(still):
        chosen = ""
        for sym in yahoo_search_isin(r["isin"]):
            if validate_symbol(sym):
                chosen = sym; break
            time.sleep(0.1)
        status = "isin_search" if chosen else "no_data"
        m[r["isin"]] = {"isin": r["isin"], "ticker": r["ticker"],
                        "yahoo_symbol": chosen, "status": status}
        if i % 25 == 0:
            save_map(m); print(f"  ...{i}/{len(still)}")
        time.sleep(0.2)
    save_map(m)

    resolved = sum(1 for r in uni if m.get(r["isin"], {}).get("yahoo_symbol"))
    print(f"TOTAL resolvido: {resolved}/{len(uni)} ({100*resolved/len(uni):.1f}%)")

if __name__ == "__main__":
    main()
