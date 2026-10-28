"""Indicatori usati da Martin: EMA, ATR, ADR%, dollar volume, AVWAP, swing, weekly."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """ATR di Wilder."""
    pc = df.Close.shift(1)
    tr = pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adr_pct(df: pd.DataFrame, n: int = 20) -> float:
    """Average daily range in %: media di (High/Low - 1) sulle ultime n barre."""
    r = (df.High / df.Low - 1.0).iloc[-n:]
    return float(r.mean() * 100.0)


def dollar_volume(df: pd.DataFrame, n: int = 5) -> float:
    return float((df.Close * df.Volume).iloc[-n:].mean())


def avwap(df: pd.DataFrame, anchor_pos: int) -> float:
    """AVWAP (prezzo tipico HLC3) dalla barra in posizione `anchor_pos` all'ultima."""
    sub = df.iloc[anchor_pos:]
    tp = (sub.High + sub.Low + sub.Close) / 3.0
    v = sub.Volume.replace(0, np.nan).fillna(1.0)
    return float((tp * v).sum() / v.sum())


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


def classify(close: float, e50: float, e150: float) -> str:
    """Liste di Martin [ML 12/03/2026]."""
    if close > e50 and e50 > e150:
        return "Leading"
    if close < e50 and e50 < e150:
        return "Lagging"
    return "Mediocre"


def unfilled_gaps(df: pd.DataFrame, lookback: int = 60) -> list[tuple[str, float, float]]:
    """Gap non chiusi nelle ultime `lookback` barre: ('up'|'down', bordo vicino, bordo lontano)."""
    out = []
    n = len(df)
    hi, lo = df.High.to_numpy(), df.Low.to_numpy()
    for i in range(max(1, n - lookback), n):
        if lo[i] > hi[i - 1]:                       # gap up: zona hi[i-1]..lo[i]
            if lo[i:].min() > hi[i - 1]:
                out.append(("up", float(lo[i]), float(hi[i - 1])))
        elif hi[i] < lo[i - 1]:                     # gap down: zona hi[i]..lo[i-1]
            if hi[i:].max() < lo[i - 1]:
                out.append(("down", float(hi[i]), float(lo[i - 1])))
    return out


def pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b in (None, 0):
        return None
    return (a / b - 1.0) * 100.0
