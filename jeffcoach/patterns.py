"""Lettura C del pattern: struttura con pivot e trendline, come si guarda un grafico a mano.

Fonti:
  - Qullamaggie, "breakout": spinta forte nei 1-3 mesi prima, poi consolidamento ordinato con minimi
    crescenti e range che si stringono, che "surfa" le medie 10/20 (a volte tocca la 50). Ingresso sul
    massimo del range di apertura, stop non più largo dell'ATR.
  - Oliver Kell, ciclo del prezzo: Base n' Break e EMA crossback sopra le 10/20 EMA; bull flag = massimi e
    minimi decrescenti, pennant = massimi decrescenti e minimi crescenti; il 2B (rottura del minimo
    recuperata) è un segnale di forza; il rising wedge in alto è esaurimento.
  - Mancini: un minimo significativo perso e recuperato (failed breakdown) intrappola i venditori.
  - Monis: trendline tracciate su pivot massimi e minimi, si entra sulla rottura della linea alta.

Come lavora:
  1. trova il massimo della spinta (picco) e il minimo da cui è partita;
  2. dal picco a oggi è il consolidamento: pivot massimi -> linea di resistenza, pivot minimi -> supporto;
  3. dalle pendenze delle due linee viene la forma (flag, pennant, base piatta, base ascendente, falling wedge;
     rising wedge, triangolo discendente, canale largo che sale e allargamento sono scartati, come nella
     lista chiusa di Ronin);
  4. controlla che si stia stringendo, che il close sia vicino alla linea alta e non già oltre,
     che le medie reggano.
Tutte le soglie sono in config.PATTERN_C.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from . import config as C
from . import indicators as I


def _pivots(x: np.ndarray, k: int, right: int, kind: str) -> list[int]:
    """Indici dei pivot: massimo (o minimo) su k barre a sinistra e `right` a destra."""
    out = []
    for i in range(k, len(x) - right):
        w = x[i - k:i + right + 1]
        if (kind == "high" and x[i] >= w.max()) or (kind == "low" and x[i] <= w.min()):
            if not out or i - out[-1] > 1:
                out.append(i)
    return out


def _best_line(idx: list[int], y: np.ndarray, series: np.ndarray, start: int, end: int,
               tol: float, kind: str) -> Optional[tuple[float, float, int]]:
    """Trendline per due pivot che nessuna barra da `start` a `end` attraversa (oltre tol).
    Resistenza (kind="high"): tutti i massimi dal picco in poi stanno sotto la linea, così la linea rispetta
    il picco come quella tracciata a mano. Supporto (kind="low"): passa per l'ULTIMO pivot minimo e per uno
    precedente, e nessun minimo da quel pivot in poi sta sotto (niente linee ripide su due minimi vecchi).
    Sceglie quella con più tocchi; a parità, la più recente. Ritorna (pendenza, intercetta, tocchi)."""
    best = None
    xs = np.arange(start, end + 1)
    seg = series[start:end + 1]
    pairs = ([(a, b) for a in range(len(idx)) for b in range(a + 1, len(idx))] if kind == "high"
             else [(a, len(idx) - 1) for a in range(len(idx) - 1)])
    for a, b in pairs:
        i, j = idx[a], idx[b]
        slope = (y[j] - y[i]) / (j - i)
        icpt = y[i] - slope * i
        line = slope * xs + icpt
        if kind == "high":
            if np.any(seg > line + tol):
                continue
            touches = int(np.sum(np.abs(seg - line) <= tol))
        else:
            sel = xs >= i
            if np.any(seg[sel] < line[sel] - tol):
                continue
            touches = int(np.sum(np.abs(seg[sel] - line[sel]) <= tol))
        key = (touches, j, i)
        if best is None or key > best[0]:
            best = (key, slope, icpt, touches)
    if best is None:
        return None
    return best[1], best[2], best[3]


def read_structure(df: pd.DataFrame, atr: float) -> dict:
    """Misure grezze della struttura. Nessun giudizio qui: lo dà reading_c."""
    p = C.PATTERN_C
    c, h, l, v = (df[k].to_numpy(dtype=float) for k in ("Close", "High", "Low", "Volume"))
    n = len(c)
    out: dict = {"c_ok_data": False}
    if n < 120 or not atr:
        return out
    ema10, ema20 = I.ema(df.Close, 10).to_numpy(), I.ema(df.Close, 20).to_numpy()
    sma50 = I.sma(df.Close, 50).to_numpy()

    # 1) inizio della base. Di norma è il picco della spinta (massimo più alto delle ultime `base_max_bars`).
    #    Se il picco è di 1-3 giorni fa il titolo sta facendo una pausa stretta sui massimi (il caso tipico dei
    #    Focus di Jeff): la base è allora la finestra più lunga che finisce oggi con range <= shelf_max_atr.
    look = min(p["base_max_bars"], n - 70)
    peak = n - look + int(np.argmax(h[n - look:]))
    base_len = n - 1 - peak
    out["c_kind"] = "pullback base"
    if base_len < p["base_min_bars"]:
        s = n - 1
        while s - 1 >= n - look and h[s - 1:].max() - l[s - 1:].min() <= p["shelf_max_atr"] * atr:
            s -= 1
        if n - 1 - s >= p["base_min_bars"] - 1:
            peak, base_len = s, n - 1 - s
            out["c_kind"] = "tight at the highs"
    lo_from = max(0, peak - p["thrust_lookback"])
    start = lo_from + int(np.argmin(l[lo_from:peak + 1]))
    top = peak + int(np.argmax(h[peak:]))            # massimo della base (= picco nella base di pullback)
    hp = h[top]
    thrust_pct = (hp / l[start] - 1) * 100
    thrust_atr = (hp - l[start]) / atr
    depth = hp - l[peak:].min()
    out.update(c_ok_data=True, c_peak_i=peak, c_start_i=start, c_base_len=base_len,
               c_thrust_pct=thrust_pct, c_thrust_atr=thrust_atr, c_thrust_bars=peak - start,
               c_depth_pct=depth / hp * 100, c_depth_atr=depth / atr,
               c_retrace=depth / (hp - l[start]) if hp > l[start] else 1.0,
               c_peak=hp)
    if base_len < p["base_min_bars"] - (1 if out["c_kind"] == "tight at the highs" else 0):
        return out

    # 2) trendline sul consolidamento (pivot confermati da 2 barre a destra)
    tol = p["line_tol_atr"] * atr
    seg_h, seg_l = h.copy(), l.copy()
    ph = [i for i in _pivots(h, 2, 2, "high") if i >= top]
    if top not in ph:
        ph = [top] + ph
    pl = [i for i in _pivots(l, 2, 2, "low") if i > peak]
    up = _best_line(ph, h, seg_h, top, n - 2, tol, "high") if len(ph) >= 2 else None
    if up is None:                                    # un solo massimo: tetto piatto sul picco
        up = (0.0, float(hp), 1)
    lo_line = _best_line(pl, l, seg_l, pl[0], n - 1, tol, "low") if len(pl) >= 2 else None
    if lo_line is None:                               # nessun doppio minimo: supporto piatto sul minimo
        m_i = peak + int(np.argmin(l[peak:]))
        lo_line = (0.0, float(l[m_i]), 1)
    su, iu, tu = up
    sl, il, tl = lo_line
    t = n - 1
    upper_now, lower_now = su * t + iu, sl * t + il
    b0 = peak + 1
    upper_0, lower_0 = su * b0 + iu, sl * b0 + il
    first = slice(peak, min(peak + 5, n))
    last5 = slice(n - 5, n)
    out.update(
        c_slope_up_atr=su / atr, c_slope_lo_atr=sl / atr, c_touch_up=tu, c_touch_lo=tl,
        c_upper=upper_now, c_lower=lower_now, c_upper_next=su * (t + 1) + iu,
        c_width_atr=(upper_now - lower_now) / atr, c_width0_atr=(upper_0 - lower_0) / atr,
        c_dist_upper_atr=(upper_now - c[-1]) / atr,
        c_range5_atr=(h[last5].max() - l[last5].min()) / atr,
        c_range_first5_atr=(h[first].max() - l[first].min()) / atr,
        c_atr5_atr20=float(I.atr(df, 5).iloc[-1] / I.atr(df, 20).iloc[-1]),
        c_close_vs_ema20_atr=(c[-1] - ema20[-1]) / atr, c_close_vs_ema10_atr=(c[-1] - ema10[-1]) / atr,
        c_closes_under_sma50=int(np.sum(c[peak:] < sma50[peak:] - p["sma50_tol_atr"] * atr)),
        c_close_vs_sma50_atr=float((c[-1] - sma50[-1]) / atr),
        c_closes_above_ema20=float(np.mean(c[peak:] >= ema20[peak:])),
        c_vol_dryup=float(v[last5].mean() / v[-55:-5].mean()) if v[-55:-5].mean() else None,
        c_line_up=(int(top), float(su * top + iu), t, float(upper_now)),
        c_line_lo=(int(pl[0]) if pl else int(peak), float(sl * (pl[0] if pl else peak) + il), t, float(lower_now)),
    )
    # 3) 2B / failed breakdown: negli ultimi 5 giorni un minimo sotto il supporto, poi close di nuovo sopra
    under = [(i, sl * i + il - l[i]) for i in range(n - 5, n) if l[i] < sl * i + il - p["undercut_min_atr"] * atr]
    out["c_undercut_reclaim"] = bool(under) and c[-1] > lower_now
    return out


def shape(m: dict) -> str:
    p = C.PATTERN_C
    su, sl, flat = m["c_slope_up_atr"], m["c_slope_lo_atr"], p["flat_slope_atr"]
    conv = m["c_width_atr"] < m["c_width0_atr"] - 0.3
    if abs(su) <= flat and abs(sl) <= flat:
        return "flat base"
    if abs(su) <= flat and sl > flat:
        return "ascending base"
    if su < -flat and sl > flat:
        return "pennant"
    if su < -flat and sl < -flat:
        if conv:
            return "falling wedge"
        if m["c_width_atr"] > m["c_width0_atr"] + 0.5:
            return "broadening"
        return "bull flag"
    if su < -flat and abs(sl) <= flat:
        return "descending triangle"
    if su > flat and sl > flat:
        if conv:
            return "rising wedge"
        return "tight channel up" if m["c_width_atr"] <= C.PATTERN_C["channel_ok_width_atr"] else "channel up"
    if su > flat and sl <= flat:
        return "broadening"
    return "box"


BAD_SHAPES = {"rising wedge", "channel up", "broadening", "descending triangle"}   # lista chiusa di Ronin (METODOLOGIA §6)


def reading_c(m: dict) -> tuple[bool, list[str], list[str]]:
    """Giudizio della lettura C. Ritorna ok, motivi (detail), motivi brevi (card)."""
    p = C.PATTERN_C
    if not m.get("c_ok_data"):
        return False, ["short history"], ["short history"]
    why, sh = [], []
    if m["c_thrust_pct"] < p["thrust_min_pct"] and m["c_thrust_atr"] < p["thrust_min_atr"]:
        why.append(f"no real prior thrust (+{m['c_thrust_pct']:.0f}%, {m['c_thrust_atr']:.1f} ATR)"); sh.append("no prior thrust")
    if m["c_base_len"] < p["base_min_bars"] - (1 if m.get("c_kind") == "tight at the highs" else 0):
        why.append(f"still running, {m['c_base_len']} bars off the high"); sh.append("no base yet")
        m["c_shape"] = "no base"
        return False, why, sh
    if m["c_retrace"] > p["retrace_max"] or m["c_depth_pct"] > p["depth_max_pct"]:
        why.append(f"pullback {m['c_depth_pct']:.0f}% ({m['c_retrace'] * 100:.0f}% of the thrust), too deep"); sh.append("pullback too deep")
    s = shape(m)
    m["c_shape"] = s
    if s in BAD_SHAPES:
        why.append(s); sh.append(s)
    if m["c_width_atr"] > p["width_max_atr"]:
        why.append(f"range between the lines {m['c_width_atr']:.1f} ATR, wide"); sh.append(f"wide ({m['c_width_atr']:.1f} ATR)")
    tight = m["c_range5_atr"] <= p["range5_max_atr"] or m["c_atr5_atr20"] <= p["atr5_atr20_max"]
    if not tight:
        why.append(f"not tightening (5-day range {m['c_range5_atr']:.1f} ATR)"); sh.append("not tightening")
    d = m["c_dist_upper_atr"]
    if d < -p["broken_above_atr"]:
        why.append(f"already {abs(d):.1f} ATR above the trendline"); sh.append("already broken out")
    elif d > p["dist_upper_max_atr"]:
        why.append(f"{d:.1f} ATR under the trendline"); sh.append(f"{d:.1f} ATR under the line")
    if m["c_close_vs_ema20_atr"] < -p["ema20_tol_atr"]:
        why.append("closed under the 20 EMA"); sh.append("under 20 EMA")
    if m["c_close_vs_sma50_atr"] < 0 or m["c_closes_under_sma50"] >= p["sma50_max_closes_under"]:
        why.append("lost the 50-day during the base"); sh.append("lost the 50")
    return (not why), why, sh


def describe(m: dict) -> str:
    """Frase per la card: forma, linea di ingresso, dettagli utili."""
    s = m.get("c_shape") or "base"
    extra = []
    if m.get("c_undercut_reclaim"):
        extra.append("undercut & reclaim")
    if m.get("c_vol_dryup") is not None and m["c_vol_dryup"] < 0.8:
        extra.append("volume drying up")
    line = m.get("c_upper_next")
    lvl = "" if line is None else f", line {line:.2f}"
    return f"{s} {m['c_base_len']}d after +{m['c_thrust_pct']:.0f}%{lvl}" + (f", {', '.join(extra)}" if extra else "")
