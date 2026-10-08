"""Indicatori allineati agli script Pine di Ronin (stesse formule di pine_metrics.py,
vcp-tightness/score.py e rs-rating/compute_rs.py, che usavano Dua e Sydney).

Tutto lavora su DataFrame daily con colonne Open, High, Low, Close, Volume e indice di date.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pandas as pd

from . import config as C


# ------------------------------------------------------------------ Pine base
def rma(s: pd.Series, length: int) -> pd.Series:
    """ta.rma (Wilder): seed = SMA dei primi `length` valori."""
    v = s.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    if len(v) < length:
        return pd.Series(out, index=s.index)
    a = 1.0 / length
    out[length - 1] = np.nanmean(v[:length])
    for i in range(length, len(v)):
        out[i] = a * v[i] + (1 - a) * out[i - 1]
    return pd.Series(out, index=s.index)


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df.Close.shift(1)
    return pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return rma(true_range(df), length)


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.astype(float).rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.astype(float).ewm(span=n, adjust=False).mean()


def avg_vol_adv(df: pd.DataFrame, n: int = 50) -> tuple[Optional[float], Optional[float]]:
    """Pine: sma(volume[1],50), sma(volume[1]*close[1],50) sull'ultima barra."""
    if len(df) < n + 1:
        return None, None
    v = df.Volume.astype(float).shift(1)
    c = df.Close.astype(float).shift(1)
    av = v.rolling(n, min_periods=n).mean().iloc[-1]
    adv = (v * c).rolling(n, min_periods=n).mean().iloc[-1]
    return (float(av) if pd.notna(av) else None, float(adv) if pd.notna(adv) else None)


def atr_ext(close: float, ma: float, atr_abs: float) -> Optional[float]:
    """Atr Ext di Ronin = ((close-MA)/MA*100)/ATR%  (NON (close-MA)/ATR)."""
    if not ma or not atr_abs or ma <= 0 or atr_abs <= 0:
        return None
    return (close - ma) * close / (ma * atr_abs)


def range_pct(df: pd.DataFrame) -> pd.Series:
    """Range della barra come nello script VCP: (H-L)/L*100."""
    return (df.High - df.Low) / df.Low * 100.0


def adr_pct(df: pd.DataFrame, n: int = C.VCP_ADR_LEN) -> pd.Series:
    return range_pct(df).rolling(n, min_periods=n).mean()


# ------------------------------------------------------------------ VCP Tightness
def vcp_series(df: pd.DataFrame, length=C.VCP_LEN, adr_len=C.VCP_ADR_LEN, baseline=C.VCP_BASELINE) -> pd.Series:
    """VCP Tightness Score 0-100 per ogni barra (identico a score.py / vcp_tightness.pine).
    NaN se lo storico non riempie la baseline: la finestra non si accorcia mai."""
    adr = adr_pct(df, adr_len).replace(0, 0.0001)
    hc, lc = df.Close.rolling(length).max(), df.Close.rolling(length).min()
    hp, lp = df.High.rolling(length).max(), df.Low.rolling(length).min()
    cs = (hc - lc) / lc * 100.0
    ps = (hp - lp) / lp * 100.0
    comb = (cs / adr + ps / adr) / 2.0
    hi = comb.rolling(baseline, min_periods=baseline).max()
    lo = comb.rolling(baseline, min_periods=baseline).min()
    span = hi - lo
    sc = (comb - lo) / span * 100.0
    sc = sc.where(span != 0, 0.0)
    return sc.where(hi.notna())


def vcp_band(score: Optional[float]) -> Optional[str]:
    if score is None or pd.isna(score):
        return None
    return "super tight" if score <= 10 else "tight" if score <= 25 else "loose" if score <= 50 else "above 50"


def compression_days(df: pd.DataFrame, window=C.COMPRESSION_WINDOW) -> int:
    """Quante delle ultime `window` barre hanno range% < ADR20% dello stesso giorno."""
    r = range_pct(df)
    a = adr_pct(df)
    ok = (r < a).iloc[-window:]
    return int(ok.sum())


# ------------------------------------------------------------------ RS Rating Fred6724 (pine_replay)
_PERIODS = (63, 126, 189, 252)
_WEIGHTS = (0.4, 0.2, 0.2, 0.2)


def _strength(closes: Sequence[float]) -> Optional[float]:
    """0.4*C/C[n63] + 0.2*C/C[n126] + ... con n = min(bar_index, N) come nello script (IPO)."""
    n = len(closes)
    if n < 2:
        return None
    last = float(closes[-1])
    s = 0.0
    for p, w in zip(_PERIODS, _WEIGHTS):
        k = min(n - 1, p)
        base = float(closes[-1 - k])
        if base <= 0:
            return None
        s += w * (last / base)
    return s


def rs_raw(stock_closes: Sequence[float], spx_closes: Sequence[float]) -> Optional[float]:
    a, b = _strength(stock_closes), _strength(spx_closes)
    if a is None or b is None or b == 0:
        return None
    return a / b * 100.0


def _attr(score, taller, smaller, up, dn, weight):
    s = score + (score - smaller) * weight
    if s > taller - 1:
        s = taller - 1
    k1 = smaller / dn
    k2 = (taller - 1) / up
    k3 = (k1 - k2) / (taller - 1 - smaller)
    r = s / (k1 - k3 * (score - smaller))
    return min(max(r, dn), up)


def rs_rating(raw: Optional[float], th: Sequence[float] = C.RS_PINE_REPLAY) -> Optional[int]:
    if raw is None:
        return None
    f1, f2, f3, f4, f5, f6, f7 = th
    if raw >= f1:
        return 99
    if raw <= f7:
        return 1
    if raw >= f2:
        r = _attr(raw, f1, f2, 98, 90, 0.33)
    elif raw >= f3:
        r = _attr(raw, f2, f3, 89, 70, 2.1)
    elif raw >= f4:
        r = _attr(raw, f3, f4, 69, 50, 0)
    elif raw >= f5:
        r = _attr(raw, f4, f5, 49, 30, 0)
    elif raw >= f6:
        r = _attr(raw, f5, f6, 29, 10, 0)
    else:
        r = _attr(raw, f6, f7, 9, 2, 0)
    return int(round(r))
