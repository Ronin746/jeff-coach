"""Lettura D: canale rialzista lungo, comprato nella PARTE BASSA del range.

Imparata dai grafici di Ronin (XLK, NET, CRWD, FTNT, RNG, RBRK, 08/10): due trendline di 2-5 mesi, con
almeno 2-3 tocchi ciascuna, entro cui il prezzo sale a gradini. Le medie 10/21/50 sono impilate sotto il prezzo
e fanno da supporto. Si compra quando il prezzo torna verso la linea bassa o sulle medie, non sul bordo alto:
  - NET: scende dal bordo alto sulla EMA21 (zona di acquisto se regge);
  - RNG: sul bordo basso del canale ripido, sulle EMA10/21;
  - CRWD / FTNT: rotto il bordo alto, il ritorno sulla linea rotta (backtest) è il "basso" del nuovo range;
  - RBRK / XLK: sul bordo alto = esteso, non si compra; XLK ha rotto sopra e rientrato = rottura fallita.

Non cambia mai la lista: è una lettura in più (come la C), mostrata nel riepilogo.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from . import config as C
from . import indicators as I


def _pivots(x: np.ndarray, k: int, kind: str, lo: int, hi: int) -> list[int]:
    out = []
    for i in range(max(lo, k), min(hi, len(x) - k)):
        w = x[i - k:i + k + 1]
        if (kind == "high" and x[i] >= w.max()) or (kind == "low" and x[i] <= w.min()):
            if not out or i - out[-1] > 2:
                out.append(i)
    return out


def _parallel(h: np.ndarray, l: np.ndarray, ph: list[int], pl: list[int], lo: int, end: int, tol: float, min_gap: int,
              side_tol: float = None, max_viol: int = 0, min_spread: float = 0.0):
    """Canale = due linee PARALLELE. Si prova ogni coppia di pivot (minimi per la linea bassa, massimi per
    l'alta): la linea passa per i due pivot, tutte le barre dopo il primo stanno dal lato giusto (tol), e la
    parallela si mette sull'estremo opposto. Tocchi = pivot entro tol da ciascuna linea.
    Sceglie più tocchi in totale, poi più lungo. Ritorna dict o None."""
    side_tol = tol if side_tol is None else side_tol
    xs = np.arange(lo, end + 1)
    hs, ls_ = h[lo:end + 1], l[lo:end + 1]
    best = None
    for kind, piv, ser in (("low", pl, l), ("high", ph, h)):
        for a in range(len(piv)):
            for b in range(a + 1, len(piv)):
                i, j = piv[a], piv[b]
                if j - i < min_gap:
                    continue
                s = (ser[j] - ser[i]) / (j - i)
                base = s * xs + (ser[i] - s * i)
                after = xs >= i
                if kind == "low":
                    if np.sum(ls_[after] < base[after] - side_tol) > max_viol:
                        continue
                    off = float(np.sort((hs - base)[after])[-1 - min(max_viol, int(after.sum()) - 1)])  # parallela alta sul massimo (senza le spike)
                    lo_i, up_i = ser[i] - s * i, ser[i] - s * i + off
                else:
                    if np.sum(hs[after] > base[after] + side_tol) > max_viol:
                        continue
                    off = float(np.sort((base - ls_)[after])[-1 - min(max_viol, int(after.sum()) - 1)])  # parallela bassa sul minimo (senza le spike)
                    up_i, lo_i = ser[i] - s * i, ser[i] - s * i - off
                ku = [k for k in ph if k >= i and abs(h[k] - (s * k + up_i)) <= tol]
                kl = [k for k in pl if k >= i and abs(l[k] - (s * k + lo_i)) <= tol]
                tu, tl = len(ku), len(kl)
                span = max(1, end - i)
                # i tocchi di ciascuna linea devono coprire una buona parte del canale (non tutti in fondo)
                spread = min((ku[-1] - ku[0]) / span if tu > 1 else 0, (kl[-1] - kl[0]) / span if tl > 1 else 0)
                if spread < min_spread:
                    continue
                key = (min(tu, 3) + min(tl, 3), tu + tl, end - i)
                if best is None or key > best["key"]:
                    best = dict(key=key, slope=s, up_i=up_i, lo_i=lo_i, tu=tu, tl=tl, start=i, anchor=kind)
    return best


def read_channel(df: pd.DataFrame, atr: float) -> dict:
    p = C.CHANNEL
    c, h, l = (df[k].to_numpy(dtype=float) for k in ("Close", "High", "Low"))
    n = len(c)
    out: dict = {"d_ok_data": False}
    if n < 160 or not atr:
        return out
    ema10, ema21 = I.ema(df.Close, 10).to_numpy(), I.ema(df.Close, 21).to_numpy()
    sma50, sma200 = I.sma(df.Close, 50).to_numpy(), I.sma(df.Close, 200).to_numpy()
    tol = p["tol_atr"] * atr
    t = n - 1
    # Si provano tutte le finestre (2-7 mesi) e, per ognuna, anche lasciando fuori le ultime barre (se il prezzo
    # ha rotto il bordo alto dopo il canale: backtest / rottura fallita). Vince il canale con più tocchi su
    # ENTRAMBE le linee e più stretto; la versione "senza le ultime barre" vale solo se il prezzo è poi uscito sopra.
    found, best = None, None
    for excl in p["exclude_last"]:
        end = n - 1 - excl
        for L in p["windows"]:
            lo = max(0, n - L)
            ph = _pivots(h, p["pivot_k"], "high", lo, end)
            pl = _pivots(l, p["pivot_k"], "low", lo, end)
            if len(ph) < 2 or len(pl) < 2:
                continue
            ch = _parallel(h, l, ph, pl, lo, end, tol, p["min_gap"], p["side_tol_atr"] * atr, p["max_violations"],
                           p["min_touch_spread"])
            if ch is None or min(ch["tu"], ch["tl"]) < p["min_touches_each"] \
                    or ch["tu"] + ch["tl"] < p["min_touches_total"] or end - ch["start"] < p["min_span"]:
                continue
            width = (ch["up_i"] - ch["lo_i"]) / atr
            if width > p["max_width_atr"]:
                continue
            if excl:
                k = np.arange(end + 1, n)
                if not np.any(c[k] > ch["slope"] * k + ch["up_i"] + 0.3 * atr):
                    continue
            score = min(ch["tu"], 4) + min(ch["tl"], 4) - p["width_penalty"] * width + 0.005 * (end - ch["start"]) \
                + (0.5 if not excl else 0)
            if best is None or score > best:
                best, found = score, (excl, L, ch)
    if not found:
        out.update(d_ok_data=True, d_found=False)
        return out
    excl, L, ch = found
    s, iu, il = ch["slope"], ch["up_i"], ch["lo_i"]
    up_now, lo_now = s * t + iu, s * t + il
    width = up_now - lo_now
    idx = np.arange(max(0, n - 25), n)
    up_line = s * idx + iu
    closes_above = c[idx] > up_line + 0.3 * atr
    pos = (c[-1] - lo_now) / width
    broke = bool(closes_above.any())
    out.update(
        d_ok_data=True, d_found=True, d_window=L, d_excluded_last=excl, d_span=int(t - ch["start"]),
        d_anchor=ch["anchor"], d_slope_atr=s / atr, d_touch_up=int(ch["tu"]), d_touch_lo=int(ch["tl"]),
        d_upper=float(up_now), d_lower=float(lo_now), d_upper_next=float(s * (t + 1) + iu), d_lower_next=float(s * (t + 1) + il),
        d_width_atr=width / atr, d_rise_width=float(s * (t - ch["start"]) / width), d_pos=float(pos), d_dist_upper_atr=float((c[-1] - up_now) / atr),
        d_dist_lower_atr=float((c[-1] - lo_now) / atr), d_low_vs_lower_atr=float((l[-1] - lo_now) / atr),
        d_broke_above=broke, d_broke_ago=int(n - 1 - idx[np.argmax(closes_above)]) if broke else None,
        d_max_above_atr=float(np.max((c[idx] - up_line) / atr)) if broke else 0.0,
        d_close_vs_ema21_atr=float((c[-1] - ema21[-1]) / atr), d_low_vs_ema21_atr=float((l[-1] - ema21[-1]) / atr),
        d_low_vs_ema10_atr=float((l[-1] - ema10[-1]) / atr),
        d_under_sma50=bool(c[-1] < sma50[-1]),
        d_stacked=bool(ema21[-1] > sma50[-1] and (np.isnan(sma200[-1]) or sma50[-1] > sma200[-1])),
        d_lines=(int(ch["start"]), float(s * ch["start"] + iu), float(s * ch["start"] + il), t, float(up_now), float(lo_now)),
    )
    out["d_state"] = state(out)
    return out


def state(m: dict) -> str:
    """Dove sta il prezzo rispetto al canale."""
    p = C.CHANNEL
    if not m.get("d_found"):
        return "no channel"
    if m["d_broke_above"] and m["d_dist_upper_atr"] < -p["failed_back_atr"] and (m["d_broke_ago"] or 99) <= p["failed_within"]:
        return "failed breakout"                                   # rotto sopra e rientrato (XLK)
    if m["d_dist_upper_atr"] > p["breakout_atr"]:
        return "breakout" if (m["d_broke_ago"] or 0) <= p["fresh_breakout_bars"] else "extended above"
    if m["d_broke_above"] and -p["backtest_band_atr"] <= m["d_dist_upper_atr"] <= p["backtest_band_atr"] + 0.3 \
            and m["d_max_above_atr"] >= p["backtest_min_break_atr"]:
        return "backtest of the broken line"                      # CRWD / FTNT
    if m["d_pos"] >= p["upper_zone"]:
        return "at the upper line"                                # RBRK: esteso, non si compra
    if m["d_pos"] <= p["lower_zone"] or m["d_dist_lower_atr"] <= p["near_lower_atr"]:
        return "lower part of the channel"                        # RNG, il punto di acquisto
    if m["d_low_vs_ema21_atr"] <= p["ema_touch_atr"] and m["d_pos"] <= p["ema_pullback_max_pos"]:
        return "pullback to the EMAs"                             # NET sulla EMA21
    return "middle of the channel"


BUY_STATES = ("lower part of the channel", "pullback to the EMAs", "backtest of the broken line")


def reading_d(m: dict) -> tuple[bool, list[str], list[str]]:
    """Ok = canale rialzista valido E prezzo nella zona di acquisto (parte bassa / EMA / backtest)."""
    p = C.CHANNEL
    if not m.get("d_ok_data") or not m.get("d_found"):
        return False, ["no clean channel"], ["no channel"]
    why, sh = [], []
    if m["d_slope_atr"] < p["min_slope_atr"] and m.get("d_state") != "backtest of the broken line":
        why.append("channel not rising"); sh.append("not rising")
    if m.get("d_rise_width", 9) < p["min_rise_width"] and m.get("d_state") != "backtest of the broken line":
        why.append(f"channel rose only {m['d_rise_width']:.1f}x its width (sideways)"); sh.append("sideways")
    if m["d_width_atr"] < p["min_width_atr"]:
        why.append(f"channel only {m['d_width_atr']:.1f} ATR wide"); sh.append("too narrow")
    if not m["d_stacked"]:
        why.append("EMA21/SMA50/SMA200 not stacked"); sh.append("MAs not stacked")
    s = m["d_state"]
    if s not in BUY_STATES:
        why.append(f"{s}, not the lower part"); sh.append(s)
    if m.get("d_under_sma50"):
        why.append("closed under the SMA50"); sh.append("under SMA50")
    if m["d_dist_lower_atr"] < -p["lost_lower_atr"]:
        why.append("under the lower line"); sh.append("under the lower line")
    return (not why), why, sh


def describe_d(m: dict) -> str:
    s = m.get("d_state", "?")
    stop = m.get("d_lower_next")
    return (f"{s}, channel {m['d_width_atr']:.1f} ATR over {m['d_span']}d, "
            f"{m['d_pos'] * 100:.0f}% up the range, lower line {m['d_lower_next']:.2f}" if stop else s)
