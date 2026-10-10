"""Trendline discendente (downtrend line) e sua rottura: "wedge pop" alla Oliver Kell [RONIN 09/10].

Sulla daily si cerca la linea che parte dal massimo più alto (il picco da cui inizia la discesa) e passa per uno o
più massimi successivi più bassi, come la si traccia a mano (AAOI, PWR del 09/10). Poi:
  - rottura: primo close sopra la linea (di almeno break_atr ATR) dopo l'ultimo tocco; si misura il volume di quel
    giorno rispetto alla media a 50 giorni;
  - prima della rottura: distanza del close dalla linea, livello della linea per la seduta dopo.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from . import config as C


def _pivot_highs(h: np.ndarray, k: int) -> list[int]:
    n = len(h)
    return [i for i in range(k, n - k) if h[i] == h[i - k:i + k + 1].max()]


def read_dtl(df: pd.DataFrame, atr: float) -> dict:
    p = C.DTL
    out = {"dt_found": False}
    if df is None or len(df) < 80 or not atr or atr <= 0:
        return out
    h, l, c, v = (df[x].to_numpy(dtype=float) for x in ("High", "Low", "Close", "Volume"))
    n = len(c)
    lo = max(0, n - p["lookback"])
    piv = [i for i in _pivot_highs(h, p["pivot_k"]) if i >= lo]
    vol50 = pd.Series(v).rolling(50).mean().shift(1).to_numpy()
    best = None
    # si parte dal picco più alto (l'inizio della discesa, come la si disegna a mano); se da lì non esce una linea
    # valida si prova il picco successivo più basso. Il picco: nessun massimo più alto dopo di lui.
    peaks = sorted([i for i in piv if h[i] >= h[i:].max() - 1e-9], key=lambda i: -h[i])
    for a in peaks:
        if best is not None:
            break
        for b in [i for i in piv if i > a]:
            if b - a < p["min_gap"] or h[b] >= h[a]:
                continue
            s = (h[b] - h[a]) / (b - a)                      # pendenza per seduta (negativa)
            if -s / atr < p["min_slope_atr"]:
                continue
            line = h[a] + s * (np.arange(n) - a)
            # rottura: primo close sopra la linea dopo l'ultimo tocco b
            # rottura: close sopra la linea di break_atr ATR, o di break_atr_vol se quel giorno il volume è >= 1,5x
            # (MMED 08/10: 8x il volume, close appena sopra) [backtest 2017-2026, RONIN 10/10]
            hv = np.nan_to_num(v[b + 1:] / vol50[b + 1:], nan=0.0) >= p["break_vol_min"]
            thr = np.where(hv, p["break_atr_vol"], p["break_atr"]) * atr
            above = np.where(c[b + 1:] > line[b + 1:] + thr)[0]
            brk = int(b + 1 + above[0]) if len(above) else None
            end = brk if brk is not None else n
            seg = slice(a, end)
            # fino alla rottura i massimi stanno sotto la linea (qualche spike tollerato), i close sempre sotto
            viol = int(np.sum(h[seg] > line[seg] + p["tol_atr"] * atr))
            if viol > p["max_violations"] or np.any(c[a:end] > line[a:end] + p["break_atr"] * atr):
                continue
            touches = [i for i in piv if a <= i < end and abs(h[i] - line[i]) <= p["touch_atr"] * atr]
            if len(touches) < p["min_touches"]:
                continue
            drop = (h[a] - l[a:end].min()) / h[a] * 100
            if drop < p["min_drop_pct"] or end - a < p["min_span"]:
                continue
            # dal picco, la linea "attuale" è quella con l'ultimo tocco più recente (picco -> ultimo massimo più
            # basso prima della rottura); a parità, più tocchi
            score = (b, len(touches), end - a)
            if best is None or score > best[0]:
                best = (score, a, b, s, brk, touches, drop)
    if not best:
        return out
    _, a, b, s, brk, touches, drop = best
    line_now = h[a] + s * (n - 1 - a)
    out.update(
        dt_found=True, dt_start=str(df.index[a].date()), dt_start_high=float(h[a]), dt_slope=float(s),
        dt_touches=len(touches), dt_drop_pct=float(drop), dt_span=int((brk if brk is not None else n) - a),
        dt_line_now=float(line_now), dt_line_next=float(h[a] + s * (n - a)),
        dt_dist_atr=float((c[-1] - line_now) / atr),
        dt_broken=brk is not None,
    )
    if brk is not None:
        out.update(dt_break_ago=int(n - 1 - brk), dt_break_date=str(df.index[brk].date()),
                   dt_break_close=float(c[brk]), dt_break_line=float(h[a] + s * (brk - a)),
                   dt_break_vol=float(v[brk] / vol50[brk]) if vol50[brk] and not np.isnan(vol50[brk]) else None,
                   dt_max_since_atr=float((h[brk:].max() - (h[a] + s * (brk - a))) / atr))
        # conferma col volume [RONIN 09/10, caso P]: il volume >= break_vol_min può arrivare nei giorni subito dopo
        # la rottura (P: rotta il 17/09 a 1,1x, il 18/09 a 25x sopra la linea). Primo giorno così, entro confirm_days.
        line = h[a] + s * (np.arange(n) - a)
        conf = None
        for i in range(brk, min(n, brk + p["confirm_days"] + 1)):
            if vol50[i] and not np.isnan(vol50[i]) and v[i] / vol50[i] >= p["break_vol_min"] and c[i] > line[i]:
                conf = i
                break
        if conf is not None:
            out.update(dt_confirm_ago=int(n - 1 - conf), dt_confirm_vol=float(v[conf] / vol50[conf]),
                       dt_confirm_date=str(df.index[conf].date()))
    return out


def state(m: dict) -> Optional[str]:
    """'break' (rotta oggi con volume), 'near' (sotto la linea e vicina), 'pullback' (rotta da poco, ritorno)."""
    p = C.DTL
    if not m.get("dt_found"):
        return None
    if m.get("dt_broken"):
        ago = m["dt_break_ago"]
        if ago == 0 or m.get("dt_confirm_ago") == 0:     # rotta oggi, o confermata oggi dal volume
            return "break"
        if ago <= p["pullback_max_days"] and m["dt_dist_atr"] >= -p["failed_atr"]:
            return "pullback"
        return None
    if -m["dt_dist_atr"] <= p["near_atr"]:
        return "near"
    return None
