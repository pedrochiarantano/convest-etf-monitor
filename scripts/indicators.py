"""Cálculo de indicadores de preço, volume e momentum.
Recebe séries de preço (fechamento ajustado) e volume e devolve um dict de métricas.
Todas as métricas são calculadas de forma defensiva (retornam None quando não há
histórico suficiente) para nunca quebrar o pipeline diário."""
import numpy as np
import pandas as pd

TRADING_DAYS = {"1w": 5, "1m": 21, "3m": 63, "6m": 126, "1y": 252}

def _ret(close: pd.Series, n: int):
    c = close.dropna()
    if len(c) <= n:
        return None
    a, b = c.iloc[-1], c.iloc[-1 - n]
    if b == 0 or pd.isna(a) or pd.isna(b):
        return None
    return round((a / b - 1) * 100, 2)

def _ytd(close: pd.Series):
    c = close.dropna()
    if c.empty:
        return None
    yr = c.index[-1].year
    ytd = c[c.index.year == yr]
    if len(ytd) < 2:
        return None
    base = ytd.iloc[0]
    if base == 0:
        return None
    return round((c.iloc[-1] / base - 1) * 100, 2)

def _rsi(close: pd.Series, period: int = 14):
    c = close.dropna()
    if len(c) < period + 1:
        return None
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    v = rsi.iloc[-1]
    return None if pd.isna(v) else round(float(v), 1)

def _vol_annualized(close: pd.Series, n: int):
    c = close.dropna()
    if len(c) < n + 1:
        return None
    rets = c.pct_change().dropna().iloc[-n:]
    if len(rets) < 2:
        return None
    return round(float(rets.std() * np.sqrt(252) * 100), 1)

def _ma(close: pd.Series, n: int):
    c = close.dropna()
    if len(c) < n:
        return None
    return round(float(c.iloc[-n:].mean()), 4)

def _cross(close: pd.Series, look: int = 15):
    """Retorna 'golden'/'death' se o cruzamento MAIS RECENTE de MM50 x MM200
    ocorreu nos últimos `look` pregões. O rótulo reflete o sentido desse
    cruzamento e, portanto, o regime atual (golden = MM50 hoje acima de MM200).
    Antes o código retornava o PRIMEIRO cruzamento da janela, o que classificava
    errado fundos que cruzaram duas vezes no período."""
    c = close.dropna()
    if len(c) < 205:
        return ""
    ma50 = c.rolling(50).mean()
    ma200 = c.rolling(200).mean()
    diff = (ma50 - ma200).dropna()
    if len(diff) < 2:
        return ""
    signs = np.sign(diff.values)
    last_change = None
    for i in range(len(signs) - 1, 0, -1):
        if signs[i] != 0 and signs[i - 1] != 0 and signs[i] != signs[i - 1]:
            last_change = i
            break
    if last_change is None:
        return ""
    if (len(signs) - 1 - last_change) > look:  # cruzamento fora da janela recente
        return ""
    return "golden" if signs[last_change] > 0 else "death"

# Limites de sanidade por janela (%). Acima disso, o retorno é quase certamente
# fruto de tick defeituoso da fonte gratuita — melhor marcar como indisponível.
RET_BOUNDS = {"ret_1w": 150, "ret_1m": 300, "ret_3m": 500,
              "ret_6m": 800, "ret_ytd": 1000, "ret_1y": 1000}

def _clean(close: pd.Series) -> pd.Series:
    """Remove preços não positivos e ticks aberrantes (movimento diário > +200%
    ou < -67%), que em ETF/ETP são quase sempre erro de dado da fonte."""
    c = close.dropna()
    c = c[c > 0]
    if len(c) < 3:
        return c
    ratio = c / c.shift(1)
    bad = (ratio > 3) | (ratio < (1 / 3))
    bad.iloc[0] = False
    return c[~bad]

def degenerate(close: pd.Series) -> bool:
    """Detecta série 'morta'/defasada: preço repetido na maioria dos pregões
    (típico de listagem sem histórico real na fonte gratuita — ex.: um ticker
    da Xetra travado em um valor e com um único print recente). Nesses casos os
    retornos saem idênticos em todas as janelas e não têm significado, então o
    ativo deve ser excluído e re-resolvido em outra bolsa.

    Critério (validado em dados reais): fração de dias com variação exatamente
    zero > 50%, ou menos de 10 preços distintos na janela recente. Fundos legítimos
    de baixa volatilidade (money market, T-bill) passam com folga."""
    c = _clean(close)          # remove spikes transitórios antes de avaliar
    c = c.dropna()
    c = c[c > 0]
    if len(c) < 10:
        return True
    w = c.iloc[-120:] if len(c) >= 120 else c
    chg = w.pct_change().dropna()
    if len(chg) < 5:
        return True
    zero_frac = float((chg.abs() < 1e-6).mean())
    distinct = int(w.round(4).nunique())
    if zero_frac > 0.5 or distinct < 10:
        return True
    # Descontinuidade de nível (split não ajustado, ticker trocado ou dado
    # corrompido na fonte): a razão maior/menor preço do último ano fica absurda.
    # Fundos legítimos, mesmo alavancados/voláteis, ficam abaixo de ~3×; dado
    # corrompido chega a dezenas ou centenas de vezes.
    win = c.iloc[-252:] if len(c) >= 252 else c
    lo = float(win.min())
    if lo > 0 and float(win.max()) / lo > 12:
        return True
    return False

def compute(close: pd.Series, volume: pd.Series) -> dict:
    close = _clean(close)
    out = {k: None for k in (
        "close last_date ret_1w ret_1m ret_3m ret_6m ret_ytd ret_1y chg_1d "
        "ma50 ma200 px_vs_ma50 px_vs_ma200 trend cross rsi vol30 vol90 "
        "volume vol_avg20 vol_ratio hi52 lo52 dist_hi mom_raw"
    ).split()}
    if close.empty:
        return out

    last = float(close.iloc[-1])
    out["close"] = round(last, 4)
    out["last_date"] = close.index[-1].strftime("%Y-%m-%d")
    if len(close) >= 2 and close.iloc[-2]:
        out["chg_1d"] = round((last / float(close.iloc[-2]) - 1) * 100, 2)

    out["ret_1w"] = _ret(close, TRADING_DAYS["1w"])
    out["ret_1m"] = _ret(close, TRADING_DAYS["1m"])
    out["ret_3m"] = _ret(close, TRADING_DAYS["3m"])
    out["ret_6m"] = _ret(close, TRADING_DAYS["6m"])
    out["ret_1y"] = _ret(close, TRADING_DAYS["1y"])
    out["ret_ytd"] = _ytd(close)

    # Rede de segurança: descarta retornos implausíveis (resíduo de dado ruim)
    for _k, _b in RET_BOUNDS.items():
        if out[_k] is not None and abs(out[_k]) > _b:
            out[_k] = None
    if out["chg_1d"] is not None and abs(out["chg_1d"]) > 60:
        out["chg_1d"] = None

    ma50, ma200 = _ma(close, 50), _ma(close, 200)
    out["ma50"], out["ma200"] = ma50, ma200
    if ma50:
        out["px_vs_ma50"] = round((last / ma50 - 1) * 100, 2)
    if ma200:
        out["px_vs_ma200"] = round((last / ma200 - 1) * 100, 2)

    # Classificação de tendência
    if ma50 and ma200:
        if last > ma50 > ma200:
            out["trend"] = "Alta Forte"
        elif last > ma200:
            out["trend"] = "Alta"
        elif last < ma50 < ma200:
            out["trend"] = "Baixa Forte"
        elif last < ma200:
            out["trend"] = "Baixa"
        else:
            out["trend"] = "Lateral"
    elif ma50:
        out["trend"] = "Alta" if last > ma50 else "Baixa"
    out["cross"] = _cross(close)

    out["rsi"] = _rsi(close)
    out["vol30"] = _vol_annualized(close, 30)
    out["vol90"] = _vol_annualized(close, 90)

    vol = volume.dropna()
    if not vol.empty:
        out["volume"] = int(vol.iloc[-1])
        if len(vol) >= 20:
            avg = float(vol.iloc[-20:].mean())
            out["vol_avg20"] = int(avg)
            # Piso de liquidez + histórico mínimo: evita que recém-listados
            # ilíquidos gerem "picos" de volume artificiais (média minúscula).
            if avg >= 1000 and len(close) >= 40:
                out["vol_ratio"] = round(float(vol.iloc[-1]) / avg, 2)

    win = close.iloc[-252:] if len(close) >= 252 else close
    hi, lo = float(win.max()), float(win.min())
    out["hi52"], out["lo52"] = round(hi, 4), round(lo, 4)
    if hi > 0:
        out["dist_hi"] = round((last / hi - 1) * 100, 2)

    # Momentum bruto (combinação de janelas) — percentil calculado depois entre pares
    comps = [out["ret_1m"], out["ret_3m"], out["ret_6m"]]
    ws = [0.3, 0.4, 0.3]
    vals = [(w, c) for w, c in zip(ws, comps) if c is not None]
    if vals:
        tw = sum(w for w, _ in vals)
        out["mom_raw"] = round(sum(w * c for w, c in vals) / tw, 3)
    return out
