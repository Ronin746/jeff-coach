"""Motore unico: metriche, gate, lettura unica del pattern (patterns.py), classificazione Focus/Stalk.

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
def prev_week_cut(index) -> Optional[int]:
    """Quante barre tenere per fermarsi alla chiusura della settimana precedente a quella dell'ultima barra."""
    if len(index) == 0:
        return None
    last = index[-1].isocalendar()[:2]
    for i in range(len(index) - 1, -1, -1):
        if index[i].isocalendar()[:2] != last:
            return i + 1
    return None


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
    # RS alla chiusura della settimana precedente (ultima seduta della settimana prima), per la variazione dei
    # titoli forti per settore nella card [RONIN 09/10]
    k = prev_week_cut(df.index)
    raw_w1 = (I.rs_raw(list(c.values[:k]), list(ref.values[:k]))
              if k and ref.notna().all() and k > 255 else None)
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
        rs_raw=raw, rs=I.rs_rating(raw), rs_w1=I.rs_rating(raw_w1),
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
    try:
        from .dtl import read_dtl            # trendline discendente / wedge pop [RONIN 09/10]
        m.update(read_dtl(df, atr))
    except Exception:
        m["dt_found"] = False
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
    """Livelli per la frase della card. Il giudizio sul pattern è in patterns.reading() (lettura unica)."""
    c, h, l = df.Close.to_numpy(), df.High.to_numpy(), df.Low.to_numpy()
    return dict(range10_lo=float(l[-10:].min()), range10_hi=float(h[-10:].max()), high20=float(h[-20:].max()),
                off_high20_pct=(c[-1] / h[-20:].max() - 1) * 100)


def pattern_label(m: dict) -> str:
    """Nome del pattern dalla lettura unica (flag, pennant, base...)."""
    return m.get("c_shape") or "base"


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
    s30 = (sma65 or {}).get("ma65", (sma65 or {}).get("sma30_65m"))
    if s30 is None:
        g.append(Gate("sma65", False, f"65m {C.MA65_KIND.upper()}{C.MA65_LEN} n/a"))
    else:
        g.append(Gate("sma65", m["close"] > s30, f"closed under the 65m {C.MA65_KIND.upper()}{C.MA65_LEN} ({m['close']:.2f} vs {s30:.2f})",
                      f"under 65m {C.MA65_KIND.upper()}{C.MA65_LEN} ({(m['close'] / s30 - 1) * 100:+.1f}%)"))
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
    if C.GAP_GATE_ON and m.get("gap_open") is not None:
        g.append(Gate("gap", not m["gap_open"],
                      f"gap-down resistance to fill at {m.get('gap_top', 0):.2f} ({m.get('gap_date')})",
                      f"gap to fill {m.get('gap_top', 0):.2f}"))
    st, why, sh = P.reading(m)
    m["pattern_state"], m["pattern_why"] = st, why
    m["pattern_ok"] = ok = st == "tight"
    g.append(Gate("pattern", ok, "pattern: " + "; ".join(why[:2]), "pattern " + ", ".join(sh[:2])))
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
    admitted = m.get("pattern_state") in ("tight", "forming")   # pattern ammesso, anche se non ancora stretto
    if len(numeric) <= C.STALK_NEW_MAX_NUMERIC_OPEN and admitted:
        return "Stalk"
    if was_listed and len(numeric) <= C.STALK_CARRY_MAX_NUMERIC_OPEN:
        return "Stalk"
    return "Out"


def _px(x: float) -> str:
    return f"{x:.0f}" if x >= 1000 else f"{x:.1f}" if x >= 100 else f"{x:.2f}"


def reason_en(row: Row, sma65: Optional[dict] = None) -> str:
    """Frase breve in inglese sulla stessa riga del nome [RONIN 04/10]."""
    m = row.m
    if row.list == "Focus":
        return f"{P.describe(m)}, {m['compression_days']} tight days"
    numeric = [g.short for g in row.fails if g.code not in SOFT_GATES]
    if numeric:
        return "; ".join(numeric)
    return "; ".join(g.short for g in row.fails)
