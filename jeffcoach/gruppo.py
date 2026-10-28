"""Il gruppo del titolo e il grafico del suo ETF [RONIN 28/10, Andrea: "metti su entrambi questa versione" — studio
studi/gruppo_etf.py, claude/studio_gruppo_etf.md].

Gruppo: il tema principale del titolo nella mappa degli ETF tematici di Andrea di prima dei basket LST
(data/themes/mappa_etf.json, mappa del 19/10), con l'ETF più liquido del tema (almeno THEME_ETF_DV_MIN; prima gli ETF che
tengono azioni, poi i proxy come IBIT o GLD); senza un tema utilizzabile, il gruppo "di settore" della stessa lista
(Retail, Consumer discretionary...); altrimenti nessun gruppo (le regole del gruppo non si applicano: il titolo passa).

Regole (config GROUP_*):
  1. preferenza nei Focus, a parità di pool ed edge: prima i titoli più forti della media del gruppo per i long e più
     deboli per gli short (media dei rendimenti a 1 settimana e a 1 mese degli altri titoli del tema, almeno 3);
  2. niente short con l'ETF del gruppo in trend su (EMA9 sopra la 21, 21 in salita, prezzo sopra la 21);
  3. long solo se al trigger l'ETF del gruppo è entro GROUP_LONG_NEAR_ADR ADR da una sua area di supporto con almeno
     GROUP_LONG_MIN_LEVELS livelli (il minimo di oggi ci è arrivato vicino) e non l'ha rotta di oltre GROUP_BREAK_ADR.
Livelli dell'ETF come per i titoli (EMA daily e weekly, AVWAP, swing, gap, orizzontali), ognuno come area
± GROUP_AREA_PAD_ADR ADR (aree orizzontali dal bordo basso al bordo alto ± GROUP_HZ_PAD_ADR); aree che si toccano = una.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Optional

import pandas as pd

from . import config as C

log = logging.getLogger("jeffcoach.gruppo")

MAP_FILE = C.HOME / "themes" / "mappa_etf.json"
GENERIC_SECTOR = ("Retail", "Consumer discretionary", "Consumer staples", "Financial services", "Natural resources",
                  "Metals & mining", "Internet")


def load_map() -> dict:
    try:
        return json.loads(MAP_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("mappa ETF dei gruppi: %s", e)
        return {}


def all_etfs(mp: dict) -> list[str]:
    return sorted({e for v in (mp.get("theme_etfs") or {}).values() for e in v})


def assign(tickers, mp: dict, dv: dict[str, float]) -> dict[str, dict]:
    """{ticker: {etf, group, source}} per i titoli con un gruppo."""
    te = mp.get("theme_etfs") or {}
    proxies = {e for v in (mp.get("proxy_etfs") or {}).values() for e in v}

    def best(theme):
        es = [e for e in te.get(theme, []) if dv.get(e, 0) >= C.THEME_ETF_DV_MIN]
        pool = [e for e in es if e not in proxies] or es
        return max(pool, key=lambda e: dv[e]) if pool else None
    out = {}
    tk = mp.get("tickers") or {}
    for t in tickers:
        info = tk.get(t) or {}
        th, src = info.get("primary"), "tema"
        e = best(th) if th else None
        if e is None:
            for g in GENERIC_SECTOR:
                if g in (info.get("themes") or []) and best(g):
                    th, e, src = g, best(g), "gruppo di settore"
                    break
        if e:
            out[t] = dict(etf=e, group=th, source=src)
    return out


def areas_of(m: dict, hz: list, adr: float, close: float) -> dict:
    """Aree di interesse dell'ETF {'long': supporti, 'short': resistenze}: [{lo, hi, n}] (n = livelli dentro)."""
    pad, zpad = C.GROUP_AREA_PAD_ADR * adr / 100, C.GROUP_HZ_PAD_ADR * adr / 100
    raw = {"long": [], "short": []}
    for side, key in (("long", "supports"), ("short", "resistances")):
        for x in m.get(key) or []:
            raw[side].append((x["price"] * (1 - pad), x["price"] * (1 + pad), x["name"]))
    for z in hz:
        lo, hi = (z["lo"] * (1 - zpad), z["hi"] * (1 + zpad)) if z["kind"] == "zone" else (z["price"] * (1 - pad), z["price"] * (1 + pad))
        nm = f"HZ{z.get('tf', '')} {z['price']:.2f}"
        if z["lo"] < close:
            raw["long"].append((lo, hi, nm))
        if z["hi"] > close:
            raw["short"].append((lo, hi, nm))
    out = {}
    for side, xs in raw.items():
        merged = []
        for lo, hi, nm in sorted(xs):
            if merged and lo <= merged[-1]["hi"]:
                merged[-1]["hi"] = max(merged[-1]["hi"], hi)
                merged[-1]["members"].add(nm)
            else:
                merged.append(dict(lo=lo, hi=hi, members={nm}))
        out[side] = [dict(lo=round(a["lo"], 4), hi=round(a["hi"], 4), n=len(a["members"])) for a in merged]
    return out


def etf_state(df: pd.DataFrame, q: Optional[pd.DataFrame]) -> Optional[dict]:
    """Stato dell'ETF alla sua ultima barra: trend, ADR, aree di supporto e resistenza."""
    from . import engine as E, orizzontali as HZ
    m = E.compute_metrics(df, q)
    if not m or not m.get("adr"):
        return None
    sub = df[df.index > df.index[-1] - pd.Timedelta(days=1900)]
    try:
        hz = HZ.find_levels(sub, m["adr"])
    except Exception:
        hz = []
    return dict(adr=round(m["adr"], 3), close=m["close"],
                up=bool(m["e9"] > m["e21"] and m["e21_slope"] > 0 and m["close"] > m["e21"]),
                dn=bool(m["e9"] < m["e21"] and m["e21_slope"] < 0 and m["close"] < m["e21"]),
                areas=areas_of(m, hz, m["adr"], m["close"]))


def morning(daily: dict, syms: list[str], as_of, download=None) -> dict:
    """Gruppi della lista del mattino: {"tickers": {t: {etf, group, source, rs_group}}, "etfs": {etf: stato}}.
    `rs_group` = forza del titolo contro la media del gruppo (media dei rendimenti a 1 settimana e a 1 mese, punti %)."""
    from . import data as D
    mp = load_map()
    if not mp:
        return {}
    etfs = all_etfs(mp)
    dl = download or D.download_daily
    ed = dl(etfs + ["QQQ"], (as_of - timedelta(days=C.GROUP_HISTORY_DAYS)).isoformat(), as_of)
    ed = {e: df for e, df in ed.items() if len(df) and df.index[-1].date() == as_of}
    dv = {e: float((df.Close * df.Volume).iloc[-60:].mean()) for e, df in ed.items() if len(df) > 250}
    grp = assign([s for s in syms if s in daily], mp, dv)
    q = ed.get("QQQ") if ed.get("QQQ") is not None else daily.get("QQQ")
    states = {}
    for e in sorted({v["etf"] for v in grp.values()}):
        try:
            states[e] = etf_state(ed[e], q)
        except Exception as ex:
            log.warning("ETF del gruppo %s: %s", e, ex)
    # forza contro la media del gruppo (gli altri titoli del tema con i dati, almeno GROUP_RS_MIN_MEMBERS)
    tk = mp.get("tickers") or {}
    mem: dict[str, set] = {}
    for t, v in tk.items():
        for th in v.get("themes") or []:
            mem.setdefault(th, set()).add(t)
    ret = {}
    for s, df in daily.items():
        c = df.Close
        if len(c) > 22 and df.index[-1].date() == as_of:
            ret[s] = ((float(c.iloc[-1]) / float(c.iloc[-6]) - 1) * 100, (float(c.iloc[-1]) / float(c.iloc[-22]) - 1) * 100)
    out = {}
    for t, g in grp.items():
        if states.get(g["etf"]) is None:
            continue
        x = dict(g)
        ms = [ret[m] for m in mem.get(g["group"], ()) if m != t and m in ret]
        if t in ret and len(ms) >= C.GROUP_RS_MIN_MEMBERS:
            a5 = sum(r[0] for r in ms) / len(ms)
            a21 = sum(r[1] for r in ms) / len(ms)
            x["rs_group"] = round(((ret[t][0] - a5) + (ret[t][1] - a21)) / 2, 2)
        out[t] = x
    log.info("gruppi: %d titoli su %d con un ETF del gruppo, %d ETF", len(out), len(syms), len(states))
    return {"tickers": out, "etfs": {e: s for e, s in states.items() if s is not None}}


def row_fields(t: str, side: str, g: Optional[dict]) -> dict:
    """Campi del gruppo per una riga della lista (candidato o Focus)."""
    if not g:
        return {}
    x = (g.get("tickers") or {}).get(t)
    st = (g.get("etfs") or {}).get((x or {}).get("etf"))
    if not x or not st:
        return {}
    rs = x.get("rs_group")
    fav = 0 if rs is None else ((1 if rs > 0 else -1) if side == "long" else (1 if rs < 0 else -1))
    out = dict(group=x["group"], group_etf=x["etf"], group_up=st["up"], group_dn=st["dn"], rs_group=rs, group_fav=fav,
               group_adr=st["adr"])
    if side == "long":                 # aree di supporto con abbastanza livelli, per la condizione al trigger
        out["group_sup"] = [[a["lo"], a["hi"], a["n"]] for a in st["areas"]["long"] if a["n"] >= C.GROUP_LONG_MIN_LEVELS]
    return out


def long_near_support(r: dict, bars: Optional[pd.DataFrame]) -> Optional[str]:
    """Condizione dei long al trigger: None se va bene (o se non si può misurare: titolo senza gruppo, ETF senza
    barre), altrimenti il motivo. L'ETF deve avere oggi il minimo entro GROUP_LONG_NEAR_ADR ADR da un'area di supporto
    con almeno GROUP_LONG_MIN_LEVELS livelli e il prezzo non sotto l'area di oltre GROUP_BREAK_ADR ADR."""
    if not C.GROUP_ETF or not C.GROUP_LONG_NEAR_SUPPORT or not r.get("group_etf") or r.get("group_sup") is None:
        return None
    if bars is None or not len(bars):
        return None
    lo, px = float(bars.Low.min()), float(bars.Close.iloc[-1])
    u = (r.get("group_adr") or 0) / 100 * px
    if u <= 0:
        return None
    for alo, ahi, n in r["group_sup"]:
        if px < alo - C.GROUP_BREAK_ADR * u:
            continue
        if max(0.0, (lo - ahi) / u) <= C.GROUP_LONG_NEAR_ADR + 1e-12:
            return None
    return f"ETF del gruppo {r['group_etf']} lontano da un supporto con {C.GROUP_LONG_MIN_LEVELS}+ livelli"
