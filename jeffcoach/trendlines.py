"""Trendline e canali paralleli sul daily [RONIN 22/10, Andrea: "un sistema che delinei trendline e parallel channels
sul giornaliero in maniera corretta e coerente"; J Law, serie METS EP2: candele, medie, trendline e canali paralleli
come strumenti del trend].

Regole (tutto in scala logaritmica, come i grafici di Martin [ML]):
- la linea passa per due swing veri (pivot di 2k+1 barre), distanti almeno TL_MIN_SPAN sedute;
- rialzista = per due minimi crescenti, sotto il prezzo; ribassista = per due massimi decrescenti, sopra il prezzo;
- dal primo ancoraggio a oggi nessuna CHIUSURA dall'altra parte della linea oltre la tolleranza (TL_TOL_ADR × ADR);
  tra i due ancoraggi nemmeno le code la attraversano oltre due tolleranze (le code dopo il secondo ancoraggio possono
  bucarla: undercut e reclaim);
- tocchi = swing entro la tolleranza dalla linea, ancoraggi compresi; la linea vale con almeno TL_MIN_TOUCHES tocchi;
- tra le linee valide vince quella con più tocchi, poi quella con l'ultimo tocco più recente, poi la più lunga;
- canale parallelo: stessa inclinazione, passa per l'estremo più lontano dall'altra parte (massimi per il canale
  rialzista, minimi per quello ribassista) dal primo ancoraggio a oggi, così nessuna barra lo buca; è un canale solo se
  anche la parallela ha almeno TL_CHANNEL_MIN_TOUCHES tocchi (swing rispetto alla linea entro la tolleranza).

Le funzioni sono pure (DataFrame daily → dizionari): le usano la lista (livelli e M&T) e il grafico degli alert, così le
linee disegnate sono esattamente quelle calcolate.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from . import config as C
from . import indicators as I


def _pivots(df: pd.DataFrame, kind: str, k: int, lookback: int) -> list[int]:
    return I.swing_lows(df, k, lookback) if kind == "up" else I.swing_highs(df, k, lookback)


def _line(df: pd.DataFrame, kind: str, adr: float, k: int, lookback: int) -> Optional[dict]:
    """Migliore trendline del verso `kind` ("up" = supporto rialzista sui minimi, "down" = resistenza ribassista sui
    massimi), con l'eventuale canale parallelo."""
    n = len(df)
    if n < max(30, k * 4) or not adr or adr <= 0:
        return None
    lo = np.log(df.Low.to_numpy(dtype=float))
    hi = np.log(df.High.to_numpy(dtype=float))
    cl = np.log(df.Close.to_numpy(dtype=float))
    if not (np.isfinite(lo).all() and np.isfinite(hi).all() and np.isfinite(cl).all()):
        return None
    tol = math.log(1 + C.TL_TOL_ADR * adr / 100.0)
    piv = _pivots(df, kind, k, lookback)
    if len(piv) < 2:
        return None
    anchor = lo if kind == "up" else hi           # i punti per cui passa la linea
    other = hi if kind == "up" else lo            # il lato opposto (canale)
    sgn = 1 if kind == "up" else -1               # +1: il prezzo deve stare sopra la linea; -1: sotto
    t_all = np.arange(n)
    best, best_key = None, None
    for x, i in enumerate(piv[:-1]):
        for j in piv[x + 1:]:
            if j - i < C.TL_MIN_SPAN:
                continue
            a = (anchor[j] - anchor[i]) / (j - i)
            if sgn * a <= 0:                      # rialzista per i minimi, ribassista per i massimi
                continue
            ln = anchor[i] + a * (t_all - i)
            seg = slice(i, n)
            # nessuna chiusura dall'altra parte oltre la tolleranza, dal primo ancoraggio a oggi
            if (sgn * (cl[seg] - ln[seg]) < -tol).any():
                continue
            # tra gli ancoraggi nemmeno le code oltre due tolleranze
            mid = slice(i + 1, j)
            if j - i > 1 and (sgn * (anchor[mid] - ln[mid]) < -2 * tol).any():
                continue
            touch = [p for p in piv if p >= i and abs(anchor[p] - ln[p]) <= tol]
            if len(touch) < C.TL_MIN_TOUCHES:
                continue
            key = (len(touch), touch[-1], j - i)
            if best_key is None or key > best_key:
                best_key, best = key, dict(i=i, j=j, a=a, touches=touch)
    if best is None:
        return None
    i, a = best["i"], best["a"]
    ln = anchor[i] + a * (t_all - i)
    out = dict(
        kind=kind, a=float(a), b=float(anchor[i] - a * i), i0=int(i), i1=int(best["j"]),
        d0=str(df.index[i].date()), d1=str(df.index[best["j"]].date()),
        touches=len(best["touches"]), touch_dates=[str(df.index[p].date()) for p in best["touches"]],
        last_touch_ago=int(n - 1 - best["touches"][-1]),
        value=float(math.exp(ln[-1])),                          # valore della linea sull'ultima barra
        slope_pct_day=float((math.exp(a) - 1) * 100),
        dist_pct=float((math.exp(cl[-1] - ln[-1]) - 1) * 100),  # chiusura rispetto alla linea
        channel=None,
    )
    # canale parallelo: la stessa inclinazione per l'estremo opposto più lontano dalla linea, dal primo ancoraggio a oggi
    # (così nessun massimo, o minimo per il canale ribassista, la buca); tocchi = swing rispetto alla linea (massimi
    # locali della distanza su 2k+1 barre) entro la tolleranza dalla parallela, più l'estremo stesso
    dist = sgn * (other - ln)                                  # distanza (log) del lato opposto dalla trendline
    w = float(dist[i:].max())
    if w > tol:
        p_ext = i + int(np.argmax(dist[i:]))
        loc = [p for p in range(max(i, k), n - k) if dist[p] >= dist[p - k:p + k + 1].max() and dist[p] >= w - tol]
        touch = sorted(set(loc) | {p_ext})
        if len(touch) >= C.TL_CHANNEL_MIN_TOUCHES:
            par = ln + sgn * w
            out["channel"] = dict(
                b=float(out["b"] + sgn * w), touches=len(touch), touch_dates=[str(df.index[p].date()) for p in touch],
                value=float(math.exp(par[-1])), width_pct=float((math.exp(w) - 1) * 100),
                # posizione della chiusura nel canale: 0 = sulla trendline, 1 = sulla parallela
                position=float((sgn * (cl[-1] - ln[-1])) / w),
            )
    return out


def find_lines(df: pd.DataFrame, adr: float, lookback: Optional[int] = None, k: Optional[int] = None) -> dict:
    """{'up': trendline rialzista (supporto) o None, 'down': trendline ribassista (resistenza) o None}, ciascuna con il
    canale parallelo se confermato. Indici e date si riferiscono a `df` (l'ultima barra è la seduta di riferimento)."""
    lookback = lookback or C.TL_LOOKBACK
    k = k or C.TL_PIVOT_K
    out = {}
    for kind in ("up", "down"):
        try:
            out[kind] = _line(df, kind, adr, k, lookback)
        except Exception:
            out[kind] = None
    return out


def value_at(line: dict, pos: float, channel: bool = False) -> float:
    """Prezzo della linea (o della sua parallela) alla posizione `pos` del DataFrame usato per calcolarla."""
    b = line["channel"]["b"] if channel else line["b"]
    return float(math.exp(b + line["a"] * pos))
