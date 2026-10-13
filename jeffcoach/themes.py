"""Analisi dei temi [RONIN 13/10].

Per ogni tema (mappa di themes_map.py, con l'industria Yahoo come riserva per i titoli senza tema):
  - indice a pesi uguali dei titoli liquidi del tema (mediana delle variazioni giornaliere, ~1 anno);
  - trend dell'indice: uptrend (indice > EMA50 > EMA150 e EMA50 in salita), downtrend (indice < EMA50 < EMA150),
    altrimenti neutro;
  - punteggio: media dei ranghi tra i temi di rendimento a 21 e 63 sedute, forza rispetto all'S&P a 21 sedute,
    quota di titoli Leading (close > EMA50 > EMA150) e quota sopra la EMA21;
  - leading = uptrend e nel 30% più alto del punteggio.
Uso nella lista: i titoli il cui tema è in downtrend escono; quelli con tema leading vengono prima.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from . import config as C


def _member_stats(df: pd.DataFrame) -> Optional[dict]:
    c = df.Close.astype(float)
    if len(c) < C.THEME_EMA_SLOW + 10:
        return None
    e21 = c.ewm(span=21, adjust=False).mean().iloc[-1]
    e50 = c.ewm(span=50, adjust=False).mean().iloc[-1]
    e150 = c.ewm(span=150, adjust=False).mean().iloc[-1]
    last = c.iloc[-1]
    return dict(leading=bool(last > e50 > e150), lagging=bool(last < e50 < e150), above21=bool(last > e21))


def theme_table(groups: dict[str, list[str]], daily: dict[str, pd.DataFrame], spx: pd.Series,
                source: dict[str, str]) -> list[dict]:
    rets = {}
    stats = {}
    for mem in groups.values():
        for t in mem:
            if t not in rets and t in daily:
                c = daily[t].Close.astype(float).iloc[-320:]
                rets[t] = c.pct_change()
                stats[t] = _member_stats(daily[t])
    R = pd.DataFrame(rets)
    spx = spx.astype(float)
    rows = []
    for name, mem in groups.items():
        mem = [t for t in mem if t in R.columns and stats.get(t)]
        if len(mem) < C.THEME_MIN_MEMBERS:
            continue
        r = R[mem].median(axis=1, skipna=True).fillna(0.0)
        idx = (1 + r).cumprod()
        e50 = idx.ewm(span=C.THEME_EMA_FAST, adjust=False).mean()
        e150 = idx.ewm(span=C.THEME_EMA_SLOW, adjust=False).mean()
        last = idx.iloc[-1]
        up = bool(last > e50.iloc[-1] > e150.iloc[-1] and e50.iloc[-1] > e50.iloc[-1 - C.THEME_SLOPE_BARS])
        down = bool(last < e50.iloc[-1] < e150.iloc[-1])
        sp = spx.reindex(idx.index).ffill()
        ret21 = idx.iloc[-1] / idx.iloc[-22] - 1
        ret63 = idx.iloc[-1] / idx.iloc[-64] - 1
        rs21 = ret21 - (sp.iloc[-1] / sp.iloc[-22] - 1)
        st = [stats[t] for t in mem]
        rows.append(dict(theme=name, n=len(mem), members=sorted(mem), source=source.get(name, "industria Yahoo"),
                         trend="up" if up else "down" if down else "neutral",
                         ret21=float(ret21 * 100), ret63=float(ret63 * 100), rs21=float(rs21 * 100),
                         lead_share=float(np.mean([s["leading"] for s in st])),
                         lag_share=float(np.mean([s["lagging"] for s in st])),
                         above21=float(np.mean([s["above21"] for s in st])),
                         dist_e50=float((last / e50.iloc[-1] - 1) * 100)))
    if not rows:
        return []
    df = pd.DataFrame(rows)
    comps = ["ret21", "ret63", "rs21", "lead_share", "above21"]
    df["score"] = sum(df[c].rank(pct=True) for c in comps) / len(comps) * 100
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = np.arange(1, len(df) + 1)
    df["pctl"] = 1 - (df["rank"] - 1) / max(1, len(df) - 1)
    df["leading"] = (df.trend == "up") & (df.pctl >= C.THEME_LEADING_PCTL)
    out = df.to_dict("records")
    for r in out:                                      # tipi python (il json non vuole i tipi numpy)
        for k, v in r.items():
            if isinstance(v, np.bool_):
                r[k] = bool(v)
            elif isinstance(v, np.integer):
                r[k] = int(v)
            elif isinstance(v, np.floating):
                r[k] = float(v)
    return out


def build(doc_daily: dict[str, pd.DataFrame], spx: pd.Series, universe: set[str], metrics: dict[str, dict],
          industry: dict, tmap: dict) -> dict:
    """Tabella dei temi e tema principale di ogni titolo. Ritorna {"rows": [...], "ticker": {t: tema}}."""
    from . import themes_map as TM
    liquid = {s for s in universe if (metrics.get(s) or {}).get("adv") and metrics[s]["adv"] >= C.THEME_DV_MIN}
    mapped = TM.groups_from_map(tmap, liquid)
    groups = {k: v for k, v in mapped.items() if len(v) >= C.THEME_MIN_MEMBERS}
    in_map = {s for v in mapped.values() for s in v}
    for s in liquid:                                   # riserva: industria Yahoo per chi non ha tema
        i = (industry.get(s) or {}).get("industry")
        if i and s not in in_map:
            groups.setdefault(i, []).append(s)
    groups = {k: v for k, v in groups.items() if len(v) >= C.THEME_MIN_MEMBERS}
    rows = theme_table(groups, doc_daily, spx, tmap.get("themes") or {})
    ranked = {r["theme"]: r for r in rows}
    tick: dict[str, str] = {}
    for s in universe:                                 # tema principale della mappa se è in classifica
        p = ((tmap.get("tickers") or {}).get(s) or {}).get("primary")
        if p in ranked:
            tick[s] = p
            continue
        cand = [r for r in rows if s in r["members"]]   # altrimenti il tema col punteggio più alto che lo contiene
        if cand:
            tick[s] = max(cand, key=lambda r: r["score"])["theme"]
        else:
            i = (industry.get(s) or {}).get("industry")
            if i in ranked:
                tick[s] = i
    for r in rows:                                     # nel json bastano i primi nomi
        r["members"] = r["members"][:12]
    return {"rows": rows, "ticker": tick, "map_built": tmap.get("built_utc")}
