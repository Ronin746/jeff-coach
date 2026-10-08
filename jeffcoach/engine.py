"""Motore unico: metriche, gate, doppia lettura del pattern, classificazione Focus/Stalk.

Niente liste scritte a mano: ogni nome dell'universo passa dagli stessi gate,
sempre nello stesso ordine, e ogni esclusione ha un motivo scritto.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from . import config as C
from . import indicators as I
from . import patterns as P


def _r(x, n=2):
    return None if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))) else round(float(x), n)


# ------------------------------------------------------------------ metriche per titolo
def compute_metrics(df: pd.DataFrame, spx_close: pd.Series) -> Optional[dict]:
    """df = daily RTH del titolo fino al close di riferimento compreso."""
    if df is None or len(df) < 60:
        return None
    c, h, l = df.Close, df.High, df.Low
    close = float(c.iloc[-1])
    atr_s = I.atr(df)
    atr = float(atr_s.iloc[-1]) if pd.notna(atr_s.iloc[-1]) else None
    if not atr:
        return None
    av, adv = I.avg_vol_adv(df)
    s5, s25, s50, s200 = (I.sma(c, n) for n in (5, 25, 50, 200))
    e9, e21 = I.ema(c, 9), I.ema(c, 21)
    sma200 = s200.iloc[-1]
    sma200_then = s200.iloc[-1 - C.SMA200_SLOPE_BARS] if len(s200) > C.SMA200_SLOPE_BARS else np.nan
    vcp = I.vcp_series(df)
    ref = spx_close.reindex(df.index).ffill()
    raw = I.rs_raw(list(c.values), list(ref.values)) if ref.notna().all() else None
    rng = I.range_pct(df)
    adr = I.adr_pct(df)
    adr_last = float(adr.iloc[-1]) if pd.notna(adr.iloc[-1]) else None
    m = dict(
        close=close, high=float(h.iloc[-1]), low=float(l.iloc[-1]),
        ret1_pct=(close / float(c.iloc[-2]) - 1) * 100,
        atr=atr, atr_pct=atr / close * 100, avg_vol_50=av, adv=adv,
        sma5=float(s5.iloc[-1]), sma5_dist_pct=(close / float(s5.iloc[-1]) - 1) * 100,
        sma25=float(s25.iloc[-1]) if pd.notna(s25.iloc[-1]) else None,
        sma50=float(s50.iloc[-1]) if pd.notna(s50.iloc[-1]) else None,
        sma200=float(sma200) if pd.notna(sma200) else None,
        sma200_slope_ok=bool(sma200 >= sma200_then) if pd.notna(sma200) and pd.notna(sma200_then) else None,
        ema9=float(e9.iloc[-1]), ema21=float(e21.iloc[-1]),
        ema9_dist_atr=(close - float(e9.iloc[-1])) / atr,
        vcp=float(vcp.iloc[-1]) if pd.notna(vcp.iloc[-1]) else None,
        vcp_prev=float(vcp.iloc[-2]) if pd.notna(vcp.iloc[-2]) else None,
        compression_days=I.compression_days(df),
        rs_raw=raw, rs=I.rs_rating(raw),
        adr_pct=adr_last, last_range_adr=(float(rng.iloc[-1]) / adr_last) if adr_last else None,
        off_52w_high_pct=(close / float(h.iloc[-252:].max()) - 1) * 100,
        n_bars=len(df),
        ret21_pct=(close / float(c.iloc[-22]) - 1) * 100 if len(c) > 22 else None,
        ret63_pct=(close / float(c.iloc[-64]) - 1) * 100 if len(c) > 64 else None,
        ret126_pct=(close / float(c.iloc[-127]) - 1) * 100 if len(c) > 127 else None,
    )
    m["ext"] = I.atr_ext(close, m["sma50"], atr) if m["sma50"] else None
    m["above_sma200"] = bool(m["sma200"] is not None and close > m["sma200"])
    m.update(pattern_metrics(df, atr, adr_last))
    m.update(gap_resistance(df, atr))
    try:
        m.update(P.read_structure(df, atr))
    except Exception:                       # una struttura illeggibile non deve togliere il titolo dai calcoli
        m["c_ok_data"] = False
    try:
        m.update(P.read_triangle(df, atr))
    except Exception:
        m["t_ok"] = False
    return m


def gap_resistance(df: pd.DataFrame, atr: float) -> dict:
    """Gap al ribasso ancora aperto sopra il prezzo (Jeff: "gap down resistance to fill" prima del Focus).
    Gap = massimo del giorno sotto il minimo del giorno prima; si riempie quando un massimo successivo torna
    al minimo del giorno prima. Conta il gap aperto più vicino sopra il close, entro GAP_NEAR_ATR."""
    h, l, c = df.High.to_numpy(dtype=float), df.Low.to_numpy(dtype=float), df.Close.to_numpy(dtype=float)
    n = len(c)
    best = None
    for i in range(max(1, n - C.GAP_LOOKBACK), n):
        top, bot = l[i - 1], h[i]
        if top - bot < C.GAP_MIN_ATR * atr:
            continue
        if i + 1 < n and h[i + 1:].max() >= top:
            continue                                   # già riempito
        if top <= c[-1] or top - c[-1] > C.GAP_NEAR_ATR * atr:
            continue
        if best is None or top < best[0]:
            best = (float(top), float(bot), int(n - 1 - i), df.index[i])
    if not best:
        return {"gap_open": False}
    return {"gap_open": True, "gap_top": best[0], "gap_bottom": best[1], "gap_bars_ago": best[2],
            "gap_date": str(best[3].date()) if hasattr(best[3], "date") else str(best[3]),
            "gap_dist_atr": (best[0] - c[-1]) / atr}


def pattern_metrics(df: pd.DataFrame, atr: float, adr: Optional[float]) -> dict:
    c, h, l = df.Close.to_numpy(), df.High.to_numpy(), df.Low.to_numpy()
    n = len(c)
    close = c[-1]
    out = {}
    # --- lettura A (Dua): tutto rapportato all'ADR20%
    if adr:
        out["a_range10_adr"] = (h[-10:].max() - l[-10:].min()) / close * 100 / adr
        out["a_range5_adr"] = (h[-5:].max() - l[-5:].min()) / close * 100 / adr
        out["a_close5_adr"] = (c[-5:].max() - c[-5:].min()) / close * 100 / adr
    lo60, hi60 = l[-60:], h[-60:]
    out["a_thrust60_pct"] = max((hi60[i:].max() / lo60[i] - 1) * 100 for i in range(len(lo60) - 5))
    out["a_off_high20_pct"] = (close / h[-20:].max() - 1) * 100
    out["range10_lo"], out["range10_hi"] = float(l[-10:].min()), float(h[-10:].max())
    out["high20"] = float(h[-20:].max())
    # --- lettura B (Sydney): tutto in ATR
    best = 0.0
    for j in range(max(20, n - 15), n):
        w = c[j - 20:j]
        best = max(best, (c[j] - w.min()) / atr)
    out["b_rally20_atr"] = best
    out["b_range5_atr"] = (h[-5:].max() - l[-5:].min()) / atr
    out["b_range12_atr"] = (h[-12:].max() - l[-12:].min()) / atr
    out["b_dist_hi10_atr"] = (h[-10:].max() - close) / atr
    x = np.arange(8)
    out["b_slope_h8"] = float(np.polyfit(x, h[-8:], 1)[0]) / atr
    out["b_slope_l8"] = float(np.polyfit(x, l[-8:], 1)[0]) / atr
    seg_l = l[-45:]
    lo_i = n - 45 + int(np.argmin(seg_l[:38]))
    hi_i = lo_i + int(np.argmax(h[lo_i:]))
    out["b_thrust_atr"] = (h[hi_i] - l[lo_i]) / atr
    out["b_pullback_atr"] = (h[hi_i] - l[hi_i:].min()) / atr
    out["b_bars_since_peak"] = n - 1 - hi_i
    out["b_last_range_atr"] = (h[-1] - l[-1]) / atr
    return out


# ------------------------------------------------------------------ letture del pattern
def reading_a(m: dict) -> tuple[bool, list[str], list[str]]:
    """Lettura A (Dua): range e close rapportati all'ADR20. Ritorna ok, motivi, motivi brevi."""
    p, why, sh = C.PATTERN_A, [], []
    if m.get("a_range10_adr") is None:
        return False, ["ADR n/a"], ["ADR n/a"]
    if m["a_range10_adr"] > p["range10_adr_max"]:
        why.append(f"10-day range {m['a_range10_adr']:.1f}× ADR, wide"); sh.append(f"wide, 10d range {m['a_range10_adr']:.1f}× ADR")
    if m["a_off_high20_pct"] < p["off_high20_min_pct"]:
        why.append(f"{abs(m['a_off_high20_pct']):.1f}% under the 20-day high"); sh.append(f"{abs(m['a_off_high20_pct']):.0f}% off the 20d high")
    if (m.get("last_range_adr") or 0) > p["last_range_adr_max"]:
        why.append(f"last range {m['last_range_adr']:.1f}× ADR"); sh.append(f"last bar {m['last_range_adr']:.1f}× ADR")
    if m["a_close5_adr"] > p["close5_adr_max"]:
        why.append(f"5-day closes span {m['a_close5_adr']:.1f}× ADR"); sh.append("closes not tight")
    if m["a_thrust60_pct"] < p["thrust60_min_pct"]:
        why.append(f"only a {m['a_thrust60_pct']:.0f}% prior thrust"); sh.append(f"{m['a_thrust60_pct']:.0f}% thrust only")
    return (not why), why, sh


def reading_b(m: dict) -> tuple[bool, list[str], list[str]]:
    """Lettura B (Sydney): spinta, contrazione e trend misurati in ATR."""
    p, why, sh = C.PATTERN_B, [], []
    if m["b_rally20_atr"] < p["rally20_min_atr"]:
        why.append(f"no real prior thrust ({m['b_rally20_atr']:.1f} ATR)"); sh.append("no fresh thrust")
    if m["b_pullback_atr"] > p["pullback_max_atr"]:
        why.append(f"base after a {m['b_pullback_atr']:.1f} ATR pullback, not a continuation"); sh.append(f"base after a {m['b_pullback_atr']:.1f} ATR pullback")
    if m["b_slope_h8"] >= p["trend_slope_atr"] and m["b_slope_l8"] >= p["trend_slope_atr"]:
        why.append("still trending, not consolidated"); sh.append("still trending")
    if m["b_last_range_atr"] >= p["expansion_range_atr"] and m["ret1_pct"] >= p["expansion_ret_pct"]:
        why.append(f"expansion bar {m['ret1_pct']:+.1f}%, the 30m high would chase"); sh.append(f"expansion bar {m['ret1_pct']:+.1f}%")
    if m["b_range5_atr"] > p["range5_max_atr"]:
        why.append(f"5-day range {m['b_range5_atr']:.1f} ATR"); sh.append(f"5d range {m['b_range5_atr']:.1f} ATR")
    if m["b_dist_hi10_atr"] > p["dist_hi10_max_atr"]:
        why.append(f"{m['b_dist_hi10_atr']:.1f} ATR under the 10-day high"); sh.append(f"{m['b_dist_hi10_atr']:.1f} ATR under the 10d high")
    return (not why), why, sh


def pattern_label(m: dict) -> str:
    """Etichetta indicativa del pattern (la conferma a occhio può cambiarla)."""
    sh, sl = m["b_slope_h8"], m["b_slope_l8"]
    if sh < -0.05 and sl > 0.05:
        return "pennant"
    if sh < -0.05 and sl < -0.05:
        return "flag"
    if sl > 0.08 and sh > -0.05:
        return "ascending base"
    return "box"


# ------------------------------------------------------------------ gate
@dataclass
class Gate:
    code: str
    ok: bool
    text: str = ""          # motivo completo in inglese quando NON passa (file di dettaglio)
    short: str = ""         # versione corta per la card

    def __post_init__(self):
        self.short = self.short or self.text


def focus_gates(m: dict, sma65: Optional[dict]) -> list[Gate]:
    g: list[Gate] = []
    rs = m.get("rs")
    g.append(Gate("rs", rs is not None and rs >= C.RS_FOCUS_MIN, f"RS {rs} under 80", f"RS {rs}"))
    ok200 = m["above_sma200"] and m["sma200_slope_ok"] is True
    g.append(Gate("sma200", ok200, "SMA200 declining" if m["above_sma200"] else "under the SMA200"))
    ext = m.get("ext")
    g.append(Gate("ext", ext is not None and ext <= C.EXT_MAX,
                  f"Atr Ext {ext:.2f}× over 4×" if ext is not None else "ext n/a", "extended"))
    d5 = m["sma5_dist_pct"]
    g.append(Gate("sma5", abs(d5) <= C.SMA5_MAX_DIST_PCT, f"{d5:+.1f}% from the 5-day SMA", "over 5% from SMA5"))
    s30 = (sma65 or {}).get("sma30_65m")
    if s30 is None:
        g.append(Gate("sma65", False, "65m SMA30 n/a"))
    else:
        g.append(Gate("sma65", m["close"] > s30, f"closed under the 65m SMA30 ({m['close']:.2f} vs {s30:.2f})",
                      f"under 65m SMA30 ({(m['close'] / s30 - 1) * 100:+.1f}%)"))
    e = m["ema9_dist_atr"]
    g.append(Gate("ema9", 0 < e <= C.EMA9_MAX_ATR,
                  "under the 9 EMA" if e <= 0 else f"{e:.1f} ATR above the 9 EMA",
                  "under 9 EMA" if e <= 0 else f"{e:.1f} ATR over 9 EMA"))
    v = m.get("vcp")
    g.append(Gate("vcp", v is not None and v <= C.VCP_FOCUS_MAX,
                  f"VCP {v:.1f}, loose" if v is not None else "VCP n/a (short history)", "loose VCP" if v is not None else "VCP n/a"))
    cd = m["compression_days"]
    g.append(Gate("comp", cd >= C.COMPRESSION_DAYS_MIN,
                  f"{cd} compression day{'s' if cd != 1 else ''} in the last {C.COMPRESSION_WINDOW}",
                  f"{cd} tight day{'s' if cd != 1 else ''}"))
    if m.get("gap_open") is not None:
        g.append(Gate("gap", not m["gap_open"],
                      f"gap-down resistance to fill at {m.get('gap_top', 0):.2f} ({m.get('gap_date')})",
                      f"gap to fill {m.get('gap_top', 0):.2f}"))
    a_ok, a_why, a_sh = reading_a(m)
    b_ok, b_why, b_sh = reading_b(m)
    c_ok, c_why, c_sh = P.reading_c(m)
    m["pattern_a_ok"], m["pattern_a_why"], m["pattern_b_ok"], m["pattern_b_why"] = a_ok, a_why, b_ok, b_why
    m["pattern_c_ok"], m["pattern_c_why"] = c_ok, c_why
    mode = C.PATTERN_MODE
    if mode == "C":
        ok, why, sh = c_ok, c_why[:2], c_sh[:2]
    elif mode == "C+1":
        ok = c_ok and (a_ok or b_ok)
        why = c_why[:2] if not c_ok else (a_why[:1] + b_why[:1])
        sh = c_sh[:2] if not c_ok else (a_sh[:1] + b_sh[:1])
    else:
        ok = a_ok and b_ok
        why = a_why[:1] + [w for w in b_why[:1] if w not in a_why[:1]]
        sh = a_sh[:1] + [w for w in b_sh[:1] if w not in a_sh[:1]]
    g.append(Gate("pattern", ok, "pattern: " + "; ".join(why), "pattern " + ", ".join(sh)))
    gp = m.get("group_pctl")
    if C.GROUP_FOCUS_MIN_PCTL is not None and gp is not None:
        g.append(Gate("group", gp >= C.GROUP_FOCUS_MIN_PCTL, f"weak group ({m.get('industry')}, {gp:.0f}th pctl)",
                      f"weak group ({gp:.0f})"))
    return g


# ------------------------------------------------------------------ classificazione
@dataclass
class Row:
    ticker: str
    list: str                       # Focus | Stalk | Out
    m: dict
    gates: list[Gate] = field(default_factory=list)
    out_reason: str = ""

    @property
    def fails(self) -> list[Gate]:
        return [g for g in self.gates if not g.ok]


def universe_check(m: dict, info: dict, ticker: str) -> Optional[str]:
    """Motivo di esclusione dall'universo, o None se passa."""
    if ticker in C.EXCLUDED_TICKERS:
        return "biotech (manual list)"
    qt = (info or {}).get("quoteType")
    if qt and qt != "EQUITY":
        return f"not a stock ({qt})"
    ind = (info or {}).get("industry")
    if ind in C.EXCLUDED_INDUSTRIES:
        return f"single-name {ind}"
    mc = (info or {}).get("marketCap")
    if mc is not None and mc <= C.MCAP_MIN:
        return f"market cap {mc/1e6:.0f}M"
    if m["adv"] is None or m["adv"] < C.ADV_MIN:
        return f"adv$ {0 if m['adv'] is None else m['adv']/1e6:.1f}M"
    if m["atr_pct"] < C.ATR_PCT_MIN:
        return f"ATR% {m['atr_pct']:.2f}"
    return None


SOFT_GATES = ("pattern", "group", "gap")   # non sono gate numerici: se manca solo questo è Stalk


def classify(m: dict, gates: list[Gate], was_listed: bool = False) -> str:
    fails = [g.code for g in gates if not g.ok]
    if not fails:
        return "Focus"
    if not m["above_sma200"]:
        return "Out"                 # sotto la 200: mai Focus né Stalk finché non la riprende [RONIN 01/10]
    rs = m.get("rs") or 0
    numeric = [f for f in fails if f not in SOFT_GATES]
    if C.STALK_RS_THEME_MIN <= rs < C.STALK_RS_MIN:
        return "Stalk" if fails == ["rs"] else "Out"
    if rs < C.STALK_RS_MIN:
        return "Out"
    some_tight = (m.get("pattern_a_ok") or m.get("pattern_b_ok") or (C.PATTERN_MODE != "AB" and m.get("pattern_c_ok"))
                  or m.get("t_ok"))          # triangolo ascendente: basta per lo Stalk [RONIN 08/10]
    if len(numeric) <= C.STALK_NEW_MAX_NUMERIC_OPEN and some_tight:
        return "Stalk"
    if was_listed and len(numeric) <= C.STALK_CARRY_MAX_NUMERIC_OPEN:
        return "Stalk"
    return "Out"


def _px(x: float) -> str:
    return f"{x:.0f}" if x >= 1000 else f"{x:.1f}" if x >= 100 else f"{x:.2f}"


def reason_en(row: Row, sma65: Optional[dict] = None) -> str:
    """Frase breve in inglese sulla stessa riga del nome [RONIN 04/10]."""
    m = row.m
    if row.list == "Focus" and C.PATTERN_MODE != "AB" and m.get("pattern_c_ok") and not m.get("pattern"):
        return P.describe(m)
    if row.list == "Focus":
        lab = m.get("pattern") or pattern_label(m)
        return (f"{lab} {_px(m['range10_lo'])}–{_px(m['range10_hi'])}, "
                f"{abs(m['a_off_high20_pct']):.1f}% under the high, {m['compression_days']} tight days")
    numeric = [g.short for g in row.fails if g.code not in SOFT_GATES]
    if numeric:
        return "; ".join(numeric)
    return "; ".join(g.short for g in row.fails)
