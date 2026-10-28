"""Ranking dei temi come i basket di Ratatouille (Ronin746/ratatouille-public, Screener/) [RONIN 16/10].

1. Per ogni titolo i 7 fattori di `indicators.py` (ultimi 3 mesi = 63 sedute):
   prezzo (rendimento 3M e 1M, R² e pendenza della regressione), candele (quota verdi, giorni > +1%),
   medie (10>20>50 e pendenze positive), trend (HH/HL su 9 blocchi da 5 sedute, drawdown massimo),
   volatilità (stabilità dell'ATR), volume (volume su/giù 20 sedute, volume di ieri / media 20), forza relativa (linea
   titolo/SPY a 3 mesi).
2. `scorer.py`: ogni misura diventa un percentile 0-100 su tutto l'universo, poi media pesata (25/15/15/15/10/10/10)
   = Final_Score.
3. `sector_baskets.py` (analyze_baskets): punteggio del basket = media del Final_Score dei suoi titoli, classifica
   decrescente, top pick. Si usa solo la classifica long, anche per i filtri degli short [RONIN 16/10].
I temi restano quelli della mappa ETF attuale; cambia solo come vengono messi in classifica.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from . import config as C

LOOKBACK_DAYS = 63          # cfg.lookback_months (3) * 21
HHHL_DAYS, HHHL_CHUNK = 45, 5
ATR_LEN, ADR_LEN, VOL_LEN = 14, 20, 20


def factors(df: pd.DataFrame, bench: pd.DataFrame) -> Optional[dict]:
    """I 7 fattori di Ratatouille per un titolo (None se la storia è troppo corta)."""
    days = LOOKBACK_DAYS
    if df is None or len(df) < max(days, 50, ATR_LEN + 1, ADR_LEN + 1) or bench is None or len(bench) < days:
        return None
    close = df["Close"].ffill()
    period = close.iloc[-days:].dropna()
    if len(period) < 10:
        return None
    last = float(close.dropna().iloc[-1])

    def ret(n):
        seg = close.iloc[-n:].dropna()
        return float((seg.iloc[-1] - seg.iloc[0]) / seg.iloc[0]) if len(seg) >= 2 and seg.iloc[0] else 0.0

    # 1. prezzo
    ret3m = float((last - period.iloc[0]) / period.iloc[0]) if period.iloc[0] else 0.0
    y = period.to_numpy(dtype=float)
    x = np.arange(len(y), dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])                       # linregress di scipy, senza scipy
    r = np.corrcoef(x, y)[0, 1] if y.std() > 0 else 0.0
    # 2. candele
    pdf = df.iloc[-days:][["Open", "Close"]].ffill().dropna()
    bullish_ratio = float((pdf.Close > pdf.Open).mean()) if len(pdf) else 0.0
    strong_bull = int(((pdf.Close - pdf.Open) / pdf.Open > 0.01).sum()) if len(pdf) else 0
    # 3. medie 10/20/50
    ma10, ma20, ma50 = (close.rolling(n).mean() for n in (10, 20, 50))
    aligned = bool(ma10.iloc[-1] > ma20.iloc[-1] > ma50.iloc[-1])
    pos_slopes = bool(ma10.iloc[-1] > ma10.iloc[-6] and ma20.iloc[-1] > ma20.iloc[-6] and ma50.iloc[-1] > ma50.iloc[-6])
    # 4. trend: drawdown massimo a 3 mesi e massimi/minimi crescenti su 9 blocchi da 5 sedute
    dd = float(((period - period.cummax()) / period.cummax()).min())
    hh = df.iloc[-HHHL_DAYS:]
    n_chunks = HHHL_DAYS // HHHL_CHUNK
    highs, lows = [], []
    for i in range(n_chunks):
        ch = hh.iloc[i * HHHL_CHUNK:(i + 1) * HHHL_CHUNK]
        h, lo = ch["High"].dropna(), ch["Low"].dropna()
        if len(h) and len(lo):
            highs.append(float(h.max()))
            lows.append(float(lo.min()))
    pairs = min(len(highs), len(lows)) - 1
    hhhl = sum(1 for i in range(pairs) if highs[i + 1] > highs[i] and lows[i + 1] > lows[i])
    lllh = sum(1 for i in range(pairs) if highs[i + 1] < highs[i] and lows[i + 1] < lows[i])
    consistency, ll_lh = hhhl / (n_chunks - 1), lllh / (n_chunks - 1)
    # 5. volatilità: coefficiente di variazione dell'ATR(14) nelle ultime 20 sedute
    pc = close.shift(1)
    tr = pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(ATR_LEN).mean().iloc[-20:].dropna()
    atr_stab = float(atr.std() / atr.mean()) if len(atr) >= 2 and atr.mean() else 1.0
    # 6. volume
    v = df.iloc[-VOL_LEN:]
    up = v.Volume[v.Close > v.Open].sum()
    down = v.Volume[v.Close < v.Open].sum()
    ud = float(up / down) if down else (float(up) if up else 1.0)
    vs = df.Volume.replace(0, np.nan)
    avg = vs.rolling(VOL_LEN, min_periods=VOL_LEN // 2).mean().dropna()
    surge = float(vs.dropna().iloc[-1] / avg.iloc[-1]) if len(avg) and avg.iloc[-1] else 1.0
    # 7. forza relativa contro SPY (benchmark di Ratatouille)
    sc = close.iloc[-days:]
    bc = bench["Close"].ffill().reindex(sc.index).ffill()
    both = pd.concat([sc, bc], axis=1).dropna()
    rs = float(both.iloc[-1, 0] / both.iloc[-1, 1] / (both.iloc[0, 0] / both.iloc[0, 1]) - 1) if len(both) >= 2 else 0.0
    return {"3m_return": ret3m, "1m_return": ret(21), "1w_return": ret(5), "3d_return": ret(3),
            "r_squared": float(r ** 2), "slope": slope,
            "bullish_ratio": bullish_ratio, "strong_bullish_count": strong_bull,
            "ma_aligned": aligned, "ma_positive_slopes": pos_slopes,
            "consistency_score": consistency, "ll_lh_score": ll_lh, "max_drawdown": dd,
            "atr_stability": atr_stab, "up_down_ratio": ud, "volume_surge": surge, "rs_rating": rs}


def _pct(s: pd.Series) -> pd.Series:
    """normalize_series di Ratatouille: percentile 0-100, i mancanti al minimo."""
    s = s.astype(float)
    s = s.fillna(s.min()) if s.count() else s.fillna(0)
    return s.rank(pct=True) * 100


def scores(f: pd.DataFrame, w: Optional[dict] = None) -> pd.DataFrame:
    """Final_Score (scorer.calculate_scores) per ogni titolo di `f`."""
    w = w or C.BASKET_WEIGHTS
    al, ps = f.ma_aligned.astype(int), f.ma_positive_slopes.astype(int)
    long_parts = {
        "price_performance": (_pct(f["3m_return"]) + _pct(f["1m_return"]) + _pct(f.r_squared) + _pct(f.slope)) / 4,
        "bullish_candles": (_pct(f.bullish_ratio) + _pct(f.strong_bullish_count)) / 2,
        "ma_alignment": (_pct(al) + _pct(ps)) / 2,
        "trend_consistency": (_pct(f.consistency_score) + _pct(f.max_drawdown)) / 2,
        "volatility": _pct(-f.atr_stability),
        "volume": (_pct(f.up_down_ratio) + _pct(f.volume_surge)) / 2,
        "relative_strength": _pct(f.rs_rating),
    }
    out = f.copy()
    out["Final_Score"] = sum(long_parts[k] * w[k] for k in w)
    return out


def universe_scores(daily: dict[str, pd.DataFrame], syms: list[str], bench: pd.DataFrame) -> pd.DataFrame:
    """Fattori + punteggi su tutto l'universo dato (i percentili si calcolano su questo insieme)."""
    rows = {}
    for s in syms:
        try:
            r = factors(daily.get(s), bench)
        except Exception:          # un titolo con dati rotti non ferma la classifica
            r = None
        if r:
            rows[s] = r
    if not rows:
        return pd.DataFrame()
    return scores(pd.DataFrame.from_dict(rows, orient="index"))


def basket_stats(members: list[str], sc: pd.DataFrame) -> Optional[dict]:
    """analyze_baskets per un tema: media del Final_Score, rendimenti medi e titolo migliore."""
    b = sc.loc[[t for t in members if t in sc.index]]
    if b.empty:
        return None
    return dict(score=float(b.Final_Score.mean()),
                ret3m=float(b["3m_return"].mean() * 100), ret1m=float(b["1m_return"].mean() * 100),
                ret1w=float(b["1w_return"].mean() * 100), ret3d=float(b["3d_return"].mean() * 100),
                n_scored=len(b), top_pick=b.Final_Score.idxmax())



# ------------------------------------------------------------------ classifica sulla performance degli ETF [RONIN 17/10]
def _ema(c: pd.Series, n: int) -> pd.Series:
    return c.ewm(span=n, adjust=False).mean()


def etf_levels(df: pd.DataFrame) -> Optional[dict]:
    """Livelli dell'ETF: sopra la EMA9/21/50 daily, 9 sopra 21, EMA50 in salita, close weekly sopra la EMA9 weekly."""
    if df is None or len(df) < 60:
        return None
    c = df["Close"].ffill().dropna()
    e9, e21, e50 = _ema(c, 9), _ema(c, 21), _ema(c, 50)
    w = c.resample("W-FRI").last().dropna()
    ew9 = _ema(w, 9)
    last = float(c.iloc[-1])
    lv = {"9": last > e9.iloc[-1], "21": last > e21.iloc[-1], "50": last > e50.iloc[-1],
          "9>21": e9.iloc[-1] > e21.iloc[-1], "50up": e50.iloc[-1] > e50.iloc[-6], "w9": float(w.iloc[-1]) > ew9.iloc[-1]}
    return {k: bool(v) for k, v in lv.items()}


def etf_perf_scores(daily: dict[str, pd.DataFrame], etfs: list[str], bench: pd.DataFrame,
                    w: Optional[dict] = None) -> pd.DataFrame:
    """Classifica dei temi sulla performance dei loro ETF [RONIN 17/10, Andrea: "riporta il ranking a prima dei 7
    fattori, cioè sulla performance degli ETF, considerando anche i livelli degli ETF"]: rendimento relativo allo SPY a
    1 settimana, 1 mese e 3 mesi, più la struttura (livelli: EMA 9/21/50, 9>21, 50 in salita, 9 weekly). Ogni misura
    è un percentile tra gli ETF dei temi; Final_Score = media pesata (THEME_PERF_WEIGHTS)."""
    w = w or C.THEME_PERF_WEIGHTS
    if bench is None or len(bench) < 64:
        return pd.DataFrame()
    bc = bench["Close"].ffill()
    def ret(c, n):
        return float(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n and c.iloc[-1 - n] else None
    rows = {}
    for e in etfs:
        df = daily.get(e)
        if df is None or len(df) < 64:
            continue
        c = df["Close"].ffill().dropna()
        lv = etf_levels(df)
        if lv is None:
            continue
        r = {n: ret(c, d) for n, d in (("1w", 5), ("1m", 21), ("3m", 63), ("3d", 3))}
        b = {n: ret(bc, d) for n, d in (("1w", 5), ("1m", 21), ("3m", 63))}
        if any(r[k] is None for k in ("1w", "1m", "3m")):
            continue
        rows[e] = {"rs_1w": r["1w"] - (b["1w"] or 0), "rs_1m": r["1m"] - (b["1m"] or 0), "rs_3m": r["3m"] - (b["3m"] or 0),
                   "levels": sum(lv.values()) / len(lv), "lv": lv,
                   "1w_return": r["1w"], "1m_return": r["1m"], "3m_return": r["3m"], "3d_return": r["3d"] or 0.0}
    if not rows:
        return pd.DataFrame()
    f = pd.DataFrame.from_dict(rows, orient="index")
    parts = {"rs_1w": _pct(f.rs_1w), "rs_1m": _pct(f.rs_1m), "rs_3m": _pct(f.rs_3m), "levels": _pct(f.levels)}
    f["Final_Score"] = sum(parts[k] * w[k] for k in w) / sum(w.values())
    return f
