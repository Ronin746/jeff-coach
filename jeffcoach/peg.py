"""Reazione ritardata agli utili (PEG delayed reaction), dai post per abbonati di Jeff Sun (set-ott 2026).

Il titolo fa un gap al rialzo forte e con volume sugli utili (power earnings gap, PEG). Nelle settimane dopo non
scappa subito: torna dentro il range del giorno del gap, e lì costruisce una base stretta sopra le medie (ANF, SNOW,
ESTC, FROG, ACN, MGNI, CRSR). Si guarda per un ingresso sopra il massimo dei primi 30 minuti con RVOL.

Qui il gap si riconosce dai prezzi (apertura >= 4% o 1 ATR sopra il close prima, volume >= 2x la media);
se le date degli utili sono note, si segna se il gap è proprio il giorno (o il giorno dopo) degli utili.
Non cambia Focus/Stalk: è una lista a parte nel riepilogo [RONIN 08/10].
"""
from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
import pandas as pd

from . import config as C
from . import indicators as I


def read_peg(df: pd.DataFrame, atr: float) -> dict:
    p = C.PEG
    o, h, l, c, v = (df[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close", "Volume"))
    n = len(c)
    out: dict = {"peg_found": False}
    if n < 120 or not atr:
        return out
    atr_s = I.atr(df).to_numpy()
    sma200 = I.sma(df.Close, 200).to_numpy()
    sma50 = I.sma(df.Close, 50).to_numpy()
    g = None
    for i in range(n - 1 - p["min_bars_ago"], max(51, n - 1 - p["max_bars_ago"]), -1):    # il più recente prima
        a = atr_s[i - 1] if not np.isnan(atr_s[i - 1]) else atr
        gap = o[i] - c[i - 1]
        avg = v[i - 50:i].mean()
        gpct = gap / c[i - 1] * 100
        big = gpct >= p["gap_min_pct"] or gap >= p["gap_min_atr"] * a
        if big and avg and (v[i] >= p["vol_mult"] * avg or gpct >= p["gap_big_pct"]):
            g = i
            break
    if g is None:
        return out
    gl, gh = c[g - 1], h[g]          # range del PEG: dal close prima del gap al massimo del giorno del gap
    after_high = float(h[g:].max())
    range5 = (h[-5:].max() - l[-5:].min()) / atr
    atr5_20 = float(I.atr(df, 5).iloc[-1] / I.atr(df, 20).iloc[-1])
    hl = l[-1] > l[-6:-1].min() or l[-2] > l[-7:-2].min()          # un minimo crescente negli ultimi giorni
    out.update(
        peg_found=True, peg_date=str(df.index[g].date()), peg_bars_ago=int(n - 1 - g),
        peg_gap_pct=float((o[g] / c[g - 1] - 1) * 100), peg_vol_mult=float(v[g] / v[g - 50:g].mean()),
        peg_day_low=float(gl), peg_day_high=float(gh), peg_gap_day_low=float(l[g]), peg_after_high=after_high,
        peg_run_after_pct=float((after_high / gh - 1) * 100),
        peg_pos=float((c[-1] - gl) / (gh - gl)) if gh > gl else None,
        peg_range5_atr=float(range5), peg_atr5_20=atr5_20, peg_higher_low=bool(hl),
        peg_pivot=float(h[-10:].max()),                               # livello da rompere: massimo della base
    )
    why = []
    if c[-1] < gl - p["range_below_atr"] * atr:
        why.append("gave back the whole gap")
    if c[-1] > gh + p["range_above_atr"] * atr:
        why.append("already above the gap-day range")
    if not (range5 <= p["range5_max_atr"] or atr5_20 <= p["atr5_atr20_max"]):
        why.append(f"not tight (5-day range {range5:.1f} ATR)")
    if not np.isnan(sma200[-1]) and c[-1] < sma200[-1] - p["sma200_tol_atr"] * atr:
        why.append("under the 200-day")
    if not np.isnan(sma50[-1]) and c[-1] < sma50[-1] - p["range_below_atr"] * atr and c[-1] < gl:
        why.append("under the 50-day and the gap")
    out["peg_ok"], out["peg_why"] = (not why), why
    return out


def confirm_earnings(m: dict, dates: Iterable[str]) -> Optional[bool]:
    """True se una data degli utili cade il giorno del gap o il giorno prima (utili dopo la chiusura)."""
    if not m.get("peg_found"):
        return None
    ds = set(dates or [])
    if not ds:
        return None
    d = pd.Timestamp(m["peg_date"])
    near = {str((d - pd.tseries.offsets.BDay(k)).date()) for k in (0, 1, 2)}
    return bool(ds & near)


def describe_peg(m: dict) -> str:
    kind = "PEG" if m.get("peg_earnings") else "gap on volume"
    return (f"{kind} {m['peg_date']} +{m['peg_gap_pct']:.0f}% ({m['peg_vol_mult']:.1f}x vol), "
            f"back in the PEG range {m['peg_day_low']:.2f}-{m['peg_day_high']:.2f}, pivot {m['peg_pivot']:.2f}")
