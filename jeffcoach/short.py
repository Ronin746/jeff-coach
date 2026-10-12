"""Sezione SHORT: le stesse regole della lista long, al contrario [RONIN 12/10].

Come funziona: il grafico di ogni titolo si capovolge (prezzo -> K/prezzo; il massimo diventa il minimo) e passa dagli
stessi gate e dalle stesse letture del pattern del long. Così "sopra la SMA200 che sale" diventa "sotto la SMA200 che
scende", "entro 1,5 ATR sopra la EMA9" diventa "entro 1,5 ATR sotto la EMA9", un flag rialzista diventa un bear flag,
la base ascendente una base discendente, e così via, senza riscrivere le regole.

Differenze volute:
  - l'RS non è un gate (Ronin: "non considerare necessariamente l'RS"); si mostra quella vera e si ordina dalla più bassa;
  - universo, utili e controvalore si controllano sui prezzi veri, come nel long;
  - lista, card e alert sono separati da quelli long (stessi canali, riquadri rossi invece che verdi).
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from . import config as C
from . import engine as E

log = logging.getLogger("jeffcoach.short")

K = C.SHORT["mirror_k"]
LABELS = {"flag": "bear flag", "pennant": "bear pennant", "ascending base": "descending base", "box": "box"}


def mirror(df: pd.DataFrame) -> pd.DataFrame:
    """Grafico capovolto: K/prezzo. Il massimo del giorno capovolto è il minimo vero, e viceversa."""
    out = pd.DataFrame(index=df.index)
    out["Open"] = K / df.Open
    out["High"] = K / df.Low
    out["Low"] = K / df.High
    out["Close"] = K / df.Close
    out["Volume"] = df.Volume
    return out


def short_metrics(df: pd.DataFrame, spx_close: pd.Series) -> Optional[dict]:
    """Metriche del motore sul grafico capovolto. L'RS calcolata qui non ha senso e si sostituisce dopo."""
    m = E.compute_metrics(mirror(df), spx_close)
    if m:
        m["rs_mirror"] = m.get("rs")
    return m


def numeric_open(m: dict, s65: Optional[dict]) -> list[str]:
    """Gate numerici aperti sul grafico capovolto, senza l'RS (sempre neutra nello short)."""
    mm = dict(m, rs=99)
    return [g.code for g in E.focus_gates(mm, s65) if not g.ok and g.code not in E.SOFT_GATES]


def mirror_s65(v: Optional[dict]) -> Optional[dict]:
    """SMA30 65m vera -> capovolta. Chiudere SOTTO la SMA30 65m vera = sopra quella capovolta."""
    if not v or v.get("sma30_65m") is None:
        return None
    return {"sma30_65m": K / v["sma30_65m"]}


SHORT_TEXT = {
    "sma200": "SMA200 not falling", "ext": "extended below SMA50", "sma5": "over 5% from SMA5",
    "sma65": "above 65m SMA30", "vcp": "loose VCP", "review": "review",
}


def gate_short_text(g: E.Gate, m: dict) -> str:
    if g.code == "ema9":
        e = m["ema9_dist_atr"]
        return "above 9 EMA" if e <= 0 else f"{e:.1f} ATR under 9 EMA"
    if g.code == "comp":
        n = m["compression_days"]
        return f"{n} tight day{'s' if n != 1 else ''}"
    if g.code == "sma200" and not m["above_sma200"]:
        return "above the SMA200"
    if g.code == "pattern":
        return "pattern " + g.short.replace("pattern ", "").replace("still trending", "still falling")
    return SHORT_TEXT.get(g.code, g.short)


def reason_short(lst: str, m: dict, gates: list[E.Gate], orig: dict) -> str:
    if lst == "Focus":
        lab = LABELS.get(E.pattern_label(m), "box")
        lo, hi = K / m["range10_hi"], K / m["range10_lo"]
        x = m["a_off_high20_pct"] / 100                  # capovolto: sotto il massimo a 20 giorni
        above_low = (1 / (1 + x) - 1) * 100                 # vero: sopra il minimo a 20 giorni
        return (f"{lab} {E._px(lo)}–{E._px(hi)}, {above_low:.1f}% above the 20-day low, "
                f"{m['compression_days']} tight days")
    fails = [g for g in gates if not g.ok]
    numeric = [gate_short_text(g, m) for g in fails if g.code not in E.SOFT_GATES]
    return "; ".join(numeric or [gate_short_text(g, m) for g in fails])


def build_short(doc: dict, prev: Optional[dict], info: dict, earn: dict, window: tuple[str, str],
                fetch_info, fetch_earnings) -> dict:
    """Lista short del giorno. fetch_info / fetch_earnings: le stesse funzioni del long (si passano per non
    scaricare due volte)."""
    sm, metrics, s65 = doc.get("short_metrics") or {}, doc["metrics"], doc.get("sma65_short") or {}
    prev = prev or {}
    prev_listed = set(prev.get("short_focus", [])) | set(prev.get("short_stalk", []))
    prev_carry = {t["ticker"]: int(t.get("carry_days") or 0) for t in prev.get("short_tickers", [])}
    rows: dict[str, E.Row] = {}
    stale = {}
    for s, m0 in sm.items():
        m = dict(m0, rs=99)                                 # RS neutra: non decide nello short
        gates = [g for g in E.focus_gates(m, mirror_s65(s65.get(s))) if g.code != "rs"]
        lst = E.classify(m, gates, s in prev_listed)
        m["carry_days"] = 0
        if lst == "Stalk" and E.classify(m, gates, False) == "Out":
            m["carry_days"] = prev_carry.get(s, 0) + 1
            if m["carry_days"] > C.STALK_CARRY_MAX_SESSIONS:
                lst = "Out"
                stale[s] = m["carry_days"] - 1
        rows[s] = E.Row(s, lst, m, gates)

    listed = [s for s, r in rows.items() if r.list != "Out"]
    need = [s for s in listed if s not in info or "err" in info[s]]
    if need:
        info.update(fetch_info(need))
    out_universe = {}
    for s in listed:
        inf = dict(info.get(s, {}))
        if not inf.get("industry") and (doc.get("industry") or {}).get(s):
            inf["industry"] = doc["industry"][s].get("industry")
        why = E.universe_check(metrics[s], inf, s)          # controvalore, ATR%, market cap sui prezzi veri
        if why:
            out_universe[s] = why
            rows[s].list = "Out"
            rows[s].out_reason = why
    listed = [s for s, r in rows.items() if r.list != "Out"]
    lo, hi = window
    missing = [s for s in listed if s not in earn]
    if missing:
        earn.update(fetch_earnings(missing, since=doc["as_of"]))
    earn_out = {}
    for s in listed:
        e = earn.get(s, {})
        dates = set(e.get("calendar", [])) | set(e.get("earnings_dates", []))
        if (doc.get("meta") or {}).get(s, {}).get("earnings"):
            dates.add(doc["meta"][s]["earnings"])
        inside = [d for d in dates if lo <= d <= hi]
        if inside:
            earn_out[s] = min(inside)
            rows[s].list = "Out"
            rows[s].out_reason = f"earnings {earn_out[s]}"

    ind = doc.get("industry") or {}

    def pub(r: E.Row) -> dict:
        m, o = r.m, metrics[r.ticker]
        meta = ind.get(r.ticker) or {}
        inf = info.get(r.ticker) or {}
        return dict(
            ticker=r.ticker, list=r.list, side="short", rs=o.get("rs"), vcp=E._r(m["vcp"]),
            sma5=E._r(o["sma5_dist_pct"]), atr_ext=E._r(o["ext"]),
            reason_en=reason_short(r.list, m, r.gates, o),
            pattern_a=("tight" if m.get("pattern_a_ok") else "wide"), pattern_b=("tight" if m.get("pattern_b_ok") else "wide"),
            open_gates=[g.code for g in r.fails], extreme_rvol_ok=False, prior_day_low=E._r(o["low"]),
            industry=inf.get("industry") or meta.get("industry"), sector=inf.get("sector") or meta.get("sector"),
            carry_days=m.get("carry_days", 0),
        )

    key = lambda r: ((metrics[r.ticker].get("rs") or 0), r.ticker)      # RS più bassa prima
    focus = sorted([r for r in rows.values() if r.list == "Focus"], key=key)
    stalk = sorted([r for r in rows.values() if r.list == "Stalk"], key=key)
    return dict(focus=[pub(r) for r in focus], stalk=[pub(r) for r in stalk], stale=stale,
                out_universe=out_universe, earnings_excluded=earn_out, candidates=len(sm))
