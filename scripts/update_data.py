"""Pipeline diário: baixa dados EOD do Yahoo Finance (grátis, delay >=1 dia),
mantém histórico em data/prices.parquet, calcula indicadores de preço/volume/
momentum e grava docs/data/latest.json (consumido pelo dashboard).
Também gera agregados por setor, região e classe de ativo (rotação)."""
import csv, os, sys, json, time, datetime as dt
import numpy as np
import pandas as pd
import yfinance as yf
import indicators as ind

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UNIVERSE = os.path.join(ROOT, "data", "universe.csv")
MAP = os.path.join(ROOT, "data", "symbol_map.csv")
PRICES = os.path.join(ROOT, "data", "prices.csv.gz")
OUT = os.path.join(ROOT, "docs", "data", "latest.json")

PERIOD = os.environ.get("HISTORY_PERIOD", "2y")  # janela baixada a cada rodada
CHUNK = 100

def clean(v):
    if v is None:
        return None
    if isinstance(v, str):
        return v.split("<")[0].strip()
    return v

def load_rows():
    uni = {r["isin"]: r for r in csv.DictReader(open(UNIVERSE, encoding="utf-8"))}
    smap = {}
    if os.path.exists(MAP):
        smap = {r["isin"]: r["yahoo_symbol"] for r in csv.DictReader(open(MAP, encoding="utf-8"))
                if r.get("yahoo_symbol")}
    rows = []
    for isin, sym in smap.items():
        if isin in uni:
            r = dict(uni[isin]); r["symbol"] = sym; rows.append(r)
    return rows

def mark_recheck(isins):
    """Zera o símbolo Yahoo dos ISINs com série defasada e marca status='recheck',
    para que resolve_symbols tente encontrar uma bolsa com dado real na próxima rodada."""
    if not isins or not os.path.exists(MAP):
        return
    cols = ["isin", "ticker", "yahoo_symbol", "status"]
    rows = list(csv.DictReader(open(MAP, encoding="utf-8")))
    target = set(isins)
    for r in rows:
        if r["isin"] in target:
            r["yahoo_symbol"] = ""
            r["status"] = "recheck"
    with open(MAP, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})
    print(f"  {len(isins)} símbolos marcados para re-resolução (recheck)")

def download(symbols):
    frames_c, frames_v = [], []
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        for attempt in range(2):
            try:
                df = yf.download(chunk, period=PERIOD, progress=False,
                                 auto_adjust=True, threads=True)
                break
            except Exception as e:
                print("  retry", str(e)[:60]); time.sleep(2)
        else:
            continue
        if df is None or df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            c = df["Close"].copy(); v = df["Volume"].copy()
        else:  # um único símbolo
            c = df[["Close"]].copy(); c.columns = chunk
            v = df[["Volume"]].copy(); v.columns = chunk
        frames_c.append(c); frames_v.append(v)
        print(f"  baixados {i+len(chunk)}/{len(symbols)}")
        time.sleep(0.5)
    close = pd.concat(frames_c, axis=1) if frames_c else pd.DataFrame()
    vol = pd.concat(frames_v, axis=1) if frames_v else pd.DataFrame()
    return close, vol

def merge_history(close):
    """Anexa novos preços ao histórico persistido (parquet, formato longo)."""
    long = close.reset_index().melt(id_vars=close.index.name or "Date",
                                    var_name="symbol", value_name="close")
    long.columns = ["date", "symbol", "close"]
    long = long.dropna(subset=["close"])
    long["date"] = pd.to_datetime(long["date"]).dt.strftime("%Y-%m-%d")
    if os.path.exists(PRICES):
        old = pd.read_csv(PRICES)
        long = pd.concat([old, long], ignore_index=True)
    long = long.drop_duplicates(subset=["symbol", "date"], keep="last")
    long = long.sort_values(["symbol", "date"])
    long["close"] = long["close"].round(4)
    long.to_csv(PRICES, index=False, compression="gzip")
    return len(long)

def pct_rank(values):
    s = pd.Series(values, dtype="float64")
    return (s.rank(pct=True) * 100).round(0)

def aggregate(assets, key):
    groups = {}
    for a in assets:
        k = a.get(key) or "—"
        groups.setdefault(k, []).append(a)
    out = []
    for k, items in groups.items():
        def avg(f):
            xs = [i[f] for i in items if i.get(f) is not None]
            return round(float(np.mean(xs)), 2) if xs else None
        up = sum(1 for i in items if (i.get("trend") or "").startswith("Alta"))
        out.append({
            "name": k, "count": len(items),
            "ret_1w": avg("ret_1w"), "ret_1m": avg("ret_1m"),
            "ret_3m": avg("ret_3m"), "ret_6m": avg("ret_6m"),
            "ret_ytd": avg("ret_ytd"), "ret_1y": avg("ret_1y"),
            "rsi": avg("rsi"), "mom": avg("mom_raw"),
            "pct_uptrend": round(100 * up / len(items), 0),
        })
    out.sort(key=lambda x: (x["ret_3m"] is None, -(x["ret_3m"] or -1e9)))
    return out

def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    rows = load_rows()
    if limit:
        rows = rows[:limit]
    if not rows:
        print("Nenhum símbolo resolvido. Rode resolve_symbols.py antes."); sys.exit(1)
    symbols = [r["symbol"] for r in rows]
    print(f"baixando {len(symbols)} símbolos (período={PERIOD})...")
    close, vol = download(symbols)
    if close.empty:
        print("Sem dados retornados."); sys.exit(1)
    close.index = pd.to_datetime(close.index)
    total = merge_history(close)
    print(f"histórico: {total} linhas em prices.csv.gz")

    assets = []
    stale_isins = []
    for r in rows:
        s = r["symbol"]
        if s not in close.columns:
            continue
        c = close[s]; v = vol[s] if s in vol.columns else pd.Series(dtype=float)
        # Série "morta"/defasada: exclui e marca para re-resolver em outra bolsa
        if ind.degenerate(c):
            stale_isins.append(r["isin"])
            continue
        met = ind.compute(c, v)
        if met["close"] is None:
            continue
        assets.append({
            "isin": r["isin"], "ticker": r["ticker"], "symbol": s,
            "name": clean(r["name"]), "ac": clean(r["ac"]),
            "region": clean(r["region"]), "sector": clean(r["sector"]),
            "ter": float(r["ter"]) if r.get("ter") else None,
            "size": float(r["size"]) if r.get("size") else None,
            "cur": clean(r.get("cur")), **met,
        })

    # Percentil de momentum (força relativa) dentro de cada classe de ativo
    by_ac = {}
    for i, a in enumerate(assets):
        by_ac.setdefault(a["ac"], []).append(i)
    for ac, idxs in by_ac.items():
        ranks = pct_rank([assets[i]["mom_raw"] for i in idxs])
        for j, i in enumerate(idxs):
            rv = ranks.iloc[j]
            assets[i]["mom_pct"] = None if pd.isna(rv) else int(rv)

    # Marca as séries degeneradas para re-resolução (outra bolsa) na próxima rodada
    mark_recheck(stale_isins)

    data_date = max((a["last_date"] for a in assets), default=None)
    payload = {
        "generated_at": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "data_date": data_date,
        "universe_total": len(rows),
        "assets_with_data": len(assets),
        "excluded_stale": len(stale_isins),
        "assets": assets,
        "sectors": aggregate(assets, "sector"),
        "regions": aggregate(assets, "region"),
        "asset_classes": aggregate(assets, "ac"),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"latest.json: {len(assets)} ativos válidos, {len(stale_isins)} excluídos "
          f"(série defasada → re-resolver), data={data_date}, "
          f"{os.path.getsize(OUT)//1024} KB")

if __name__ == "__main__":
    main()
