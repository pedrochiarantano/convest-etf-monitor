"""Expande o universo mesclando o FinanceDatabase (JerBouma, licença MIT) com a
base JustETF já existente. Mantém os metadados ricos do JustETF (TER, patrimônio,
setor, região) onde existirem e ACRESCENTA os ETFs do FinanceDatabase que têm ISIN
e ainda não estão na base.

- Escopo: todos os ETFs do FinanceDatabase COM ISIN (globais), deduplicados por ISIN
  escolhendo a listagem mais líquida (Xetra/LSE/Euronext antes das regionais).
- Como o símbolo do FinanceDatabase já é o ticker do Yahoo, semeamos o symbol_map
  diretamente (status 'fdb'), dispensando a resolução por ISIN para os novos.
- TER e patrimônio não vêm do FinanceDatabase; ficam em branco e são preenchidos
  best-effort depois por enrich_metadata.py.

Rode em ambiente limpo (GitHub Actions) ou localmente:
    python scripts/build_universe.py
Para testar sem sobrescrever a base:  OUT_DIR=/tmp python scripts/build_universe.py
"""
import os, csv, io
import financedatabase as fd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
OUT_DIR = os.environ.get("OUT_DIR", DATA)
UNIVERSE = os.path.join(DATA, "universe.csv")
MAP = os.path.join(DATA, "symbol_map.csv")
UNIVERSE_OUT = os.path.join(OUT_DIR, "universe.csv")
MAP_OUT = os.path.join(OUT_DIR, "symbol_map.csv")

COLS = ["isin", "ticker", "name", "ac", "region", "sector", "ter", "size", "cur",
        "dist", "repl", "dom", "ytd", "y1", "y3", "vol", "div", "nh"]

# Preferência de bolsa para deduplicar por ISIN (europeias líquidas primeiro,
# depois EUA, por último as regionais alemãs e demais).
EXCH_PREF = {"GER": 0, "LSE": 1, "AMS": 2, "PAR": 3, "MIL": 4, "EBS": 5, "SWX": 5,
             "STO": 6, "VIE": 7, "MCE": 7, "BRU": 7, "LIS": 7,
             "PCX": 9, "NYQ": 9, "NMS": 9, "NGM": 9, "ASE": 10, "BATS": 10,
             "FRA": 12, "MUN": 13, "DUS": 13, "BER": 13, "HAM": 13, "STU": 13}
CUR_PREF = {"EUR": 0, "GBP": 1, "USD": 2, "CHF": 3}

DOM = {"IE": "Ireland", "LU": "Luxembourg", "DE": "Germany", "FR": "France",
       "NL": "Netherlands", "CH": "Switzerland", "GB": "United Kingdom",
       "US": "United States", "JE": "Jersey", "LI": "Liechtenstein",
       "CA": "Canada", "AT": "Austria", "SE": "Sweden", "IT": "Italy",
       "ES": "Spain", "FI": "Finland", "BE": "Belgium"}

def region_from_name(n):
    s = (n or "").lower()
    pairs = [("emerging", "Emerging Markets"), ("china", "China"), ("japan", "Japan"),
             ("united kingdom", "United Kingdom"), ("ftse 100", "United Kingdom"),
             ("s&p 500", "North America"), ("nasdaq", "North America"),
             ("u.s.", "North America"), ("usa", "North America"), (" us ", "North America"),
             ("eurozone", "Europe"), ("euro stoxx", "Europe"), ("emu", "Europe"),
             ("europe", "Europe"), ("all-world", "World / Global"),
             ("all world", "World / Global"), ("acwi", "World / Global"),
             ("msci world", "World / Global"), ("ftse all", "World / Global"),
             ("global", "World / Global"), ("world", "World / Global"),
             ("india", "India"), ("asia", "Asia"), ("latin", "Latin America")]
    for k, v in pairs:
        if k in s:
            return v
    return "Global / Outros"

def sector_from_name(n, category):
    s = (n or "").lower()
    pairs = [("semiconduct", "Semiconductors"), ("cyber", "Cybersecurity"),
             ("robotic", "Robotics & Automation"), ("artificial intelligence", "AI & Big Data"),
             (" ai ", "AI & Big Data"), ("big data", "AI & Big Data"),
             ("clean energy", "Clean Energy"), ("renewable", "Clean Energy"),
             ("water", "Water"), ("health", "Health Care"), ("biotech", "Health Care"),
             ("technology", "Technology"), ("financ", "Financials"), ("bank", "Financials"),
             ("energy", "Energy"), ("real estate", "Real Estate"), ("reit", "Real Estate"),
             ("gold", "Precious Metals"), ("silver", "Precious Metals"),
             ("consumer", "Consumer"), ("dividend", "Dividend"), ("small cap", "Small/Mid Cap"),
             ("mid cap", "Small/Mid Cap")]
    for k, v in pairs:
        if k in s:
            return v
    return category if category and str(category) != "nan" else "Broad Market"

def ac_from(name, cgroup):
    s = (name or "").lower()
    if any(k in s for k in ["bond", "treasury", "gilt", "govt", "aggregate", "fixed income"]):
        return "Bond"
    if any(k in s for k in ["gold", "silver", "commodit", "metal", "oil"]):
        return "Commodity"
    if "money market" in s or "t-bill" in s or "1-3 month" in s:
        return "Money Market"
    if "real estate" in s or "reit" in s:
        return "Real Estate"
    cg = str(cgroup or "")
    if cg == "Fixed Income":
        return "Bond"
    if cg == "Commodities":
        return "Commodity"
    if cg == "Real Estate":
        return "Real Estate"
    return "Equity"

def read_rows(path):
    if not os.path.exists(path):
        return []
    raw = open(path, "rb").read().decode("utf-8", "replace").replace("\x00", "")
    return list(csv.DictReader(io.StringIO(raw)))

def main():
    je = {r["isin"]: r for r in read_rows(UNIVERSE) if r.get("isin")}
    smap = {r["isin"]: r for r in read_rows(MAP) if r.get("isin")}
    print(f"JustETF: {len(je)} ISINs | symbol_map: {len(smap)} entradas")

    e = fd.ETFs().select()
    e = e[e["isin"].notna()]
    # Dedup por ISIN escolhendo a melhor listagem
    best = {}
    for sym, r in e.iterrows():
        isin = r["isin"]
        key = (EXCH_PREF.get(r.get("exchange"), 20),
               CUR_PREF.get(r.get("currency"), 4), len(str(sym)))
        if isin not in best or key < best[isin][0]:
            best[isin] = (key, str(sym), r)
    print(f"FinanceDatabase: {len(best)} ETFs únicos por ISIN")

    added = 0
    for isin, (_, sym, r) in best.items():
        if isin in je:
            continue  # JustETF já cobre (metadados ricos preservados)
        name = str(r.get("name") or "")
        je[isin] = {
            "isin": isin, "ticker": sym.split(".")[0], "name": name,
            "ac": ac_from(name, r.get("category_group")),
            "region": region_from_name(name),
            "sector": sector_from_name(name, r.get("category")),
            "ter": "", "size": "", "cur": str(r.get("currency") or ""),
            "dist": "", "repl": "", "dom": DOM.get(isin[:2], ""),
            "ytd": "", "y1": "", "y3": "", "vol": "", "div": "", "nh": "",
        }
        if isin not in smap or not smap[isin].get("yahoo_symbol"):
            smap[isin] = {"isin": isin, "ticker": sym.split(".")[0],
                          "yahoo_symbol": sym, "status": "fdb"}
        added += 1

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(UNIVERSE_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for row in je.values():
            w.writerow({k: row.get(k, "") for k in COLS})
    with open(MAP_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["isin", "ticker", "yahoo_symbol", "status"])
        w.writeheader()
        for row in smap.values():
            w.writerow({k: row.get(k, "") for k in ["isin", "ticker", "yahoo_symbol", "status"]})

    print(f"adicionados {added} novos ETFs | universo final: {len(je)} ISINs")
    print(f"escrito em: {UNIVERSE_OUT} e {MAP_OUT}")

if __name__ == "__main__":
    main()
