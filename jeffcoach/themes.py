"""Analisi dei temi [RONIN 13/10].

Per ogni tema (mappa di themes_map.py, copiata da Martin-coach: solo gruppi degli ETF tematici della lista di Andrea
con le partecipazioni complete SEC N-PORT; niente industria Yahoo) [RONIN 15/10]:
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
                source: dict[str, str], min_one: set = frozenset()) -> list[dict]:
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
        if len(mem) < (1 if name in min_one else C.THEME_MIN_MEMBERS):
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
        rows.append(dict(theme=name, n=len(mem), members=sorted(mem), source=source.get(name, "etf"),
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


def break_ties(closes: pd.DataFrame, theme_groups: dict[str, list[str]], ties: dict[str, list[str]],
               window: int = 60, min_members: int = 3) -> dict[str, str]:
    """Copia di Martin-coach: titolo in pari merito tra più temi (stesso numero di ETF), vince il tema con cui si
    muove di più (correlazione delle variazioni % con la mediana degli altri membri del tema) [RONIN 15/10]."""
    rets = closes.pct_change(fill_method=None).iloc[-window:]
    out = {}
    for t, cand in ties.items():
        if t not in rets.columns or rets[t].isna().sum() > window // 4:
            continue
        best, best_c = None, -2.0
        for th in cand:
            cols = [x for x in theme_groups.get(th, []) if x in rets.columns and x != t]
            if len(cols) < min_members:
                continue
            c = rets[t].corr(rets[cols].median(axis=1))
            if c == c and c > best_c:
                best, best_c = th, c
        if best:
            out[t] = best
    return out


def _dv(df: pd.DataFrame) -> float:
    d = df.iloc[-20:]
    return float((d.Close * d.Volume).mean())


def build(daily: dict[str, pd.DataFrame], spx: pd.Series, universe: set[str], metrics: dict[str, dict], tmap: dict) -> dict:
    """Temi come Martin-coach [RONIN 15/10]: solo ETF tematici della lista di Andrea (tutti i gruppi, nomi invariati)
    con le partecipazioni complete; niente basket, niente industria Yahoo: chi non è in un ETF tematico resta senza tema.
    Gruppi generici in classifica ma mai tema di un titolo; ETF senza azioni (GLD, IBIT, USO...) membri del loro tema.
    Ritorna {"rows": [...], "ticker": {titolo: tema}}."""
    from . import themes_map as TM
    liquid = {s for s in universe if (metrics.get(s) or {}).get("adv") and metrics[s]["adv"] >= C.THEME_DV_MIN}
    mapped = TM.groups_from_map(tmap, liquid)
    groups = {k: v for k, v in mapped.items() if len(v) >= C.THEME_MIN_MEMBERS}
    map_groups = dict(groups)
    proxy_only = set()
    for th, es in (tmap.get("proxy_etfs") or {}).items():          # ETF senza azioni: l'ETF è membro del tema
        px = [e for e in es if e in daily and _dv(daily[e]) >= C.THEME_DV_MIN]
        if px:
            groups[th] = mapped.get(th, []) + px
            if len(groups[th]) < C.THEME_MIN_MEMBERS:
                proxy_only.add(th)
    rows = theme_table(groups, daily, spx, tmap.get("themes") or {}, min_one=proxy_only)
    ranked = {r["theme"]: r for r in rows}
    generic = frozenset(TM.GENERIC_GROUPS)
    tick: dict[str, str] = {}
    for r in sorted(rows, key=lambda x: -x["score"]):              # tema col punteggio più alto, mai un generico
        if r["theme"] in generic:
            continue
        for t in r["members"]:
            if t in universe:
                tick.setdefault(t, r["theme"])
    tinfo = tmap.get("tickers") or {}
    for s, info in tinfo.items():                                 # tema principale della mappa, se è in classifica
        if s in universe and info.get("primary") in ranked:
            tick[s] = info["primary"]
    try:                                                          # pari merito tra temi: decide l'andamento
        ties = {s: [th for th in info["tied"] if th in ranked] for s, info in tinfo.items()
                if s in universe and info.get("tied")}
        ties = {s: v for s, v in ties.items() if len(v) > 1}
        cols = sorted(({s for s in ties} | {x for v in map_groups.values() for x in v}) & set(daily))
        closes = pd.DataFrame({s: daily[s].Close for s in cols}).iloc[-62:]
        tick.update(break_ties(closes, map_groups, ties, min_members=C.THEME_MIN_MEMBERS))
    except Exception as e:
        import logging
        logging.getLogger("jeffcoach.themes").warning("pari merito temi: %s", e)
    for r in rows:                                     # nel json bastano i primi nomi
        r["members"] = r["members"][:12]
    return {"rows": rows, "ticker": tick, "map_built": tmap.get("built_utc")}
