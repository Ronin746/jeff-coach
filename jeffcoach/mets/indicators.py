"""Indicatori usati dal charting di METS (copiati da martincoach/indicators.py)."""
from __future__ import annotations

import pandas as pd

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def adr_pct(df: pd.DataFrame, n: int = 20) -> float:
    """Average daily range in %: media di (High/Low - 1) sulle ultime n barre."""
    r = (df.High / df.Low - 1.0).iloc[-n:]
    return float(r.mean() * 100.0)


def swing_highs(df: pd.DataFrame, k: int, lookback: int) -> list[int]:
    """Posizioni dei massimi locali (massimo di 2k+1 barre) nelle ultime `lookback` barre, ultime k escluse."""
    h = df.High.to_numpy()
    n = len(h)
    out = []
    for i in range(max(k, n - lookback), n - k):
        if h[i] >= h[i - k:i + k + 1].max():
            out.append(i)
    return out


def swing_lows(df: pd.DataFrame, k: int, lookback: int) -> list[int]:
    lo = df.Low.to_numpy()
    n = len(lo)
    out = []
    for i in range(max(k, n - lookback), n - k):
        if lo[i] <= lo[i - k:i + k + 1].min():
            out.append(i)
    return out


def weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Barre settimanali (settimana chiusa il venerdì) dalle daily."""
    w = df.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    return w.dropna(subset=["Close"])

