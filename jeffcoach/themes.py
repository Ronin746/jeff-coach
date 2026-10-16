"""Analisi dei temi, come Martin-coach [RONIN 13/10, 15/10, 16/10].

Mappa (themes_map.py, copiata da Martin): solo gruppi degli ETF tematici della lista di Andrea, partecipazioni complete
SEC N-PORT; un titolo resta in un tema solo se l'ETF lo sovrappesa rispetto al mercato; tema principale = gruppo con
più ETF che lo tengono, mai un gruppo generico; a parità decide la correlazione a 60 sedute.

Classifica (dal 16/10, come Martin): il tema si misura direttamente sui suoi ETF.
  - ogni ETF dei temi (almeno 250k$ al giorno) riceve il punteggio a 7 fattori di Ratatouille (basket_score.py:
    prezzo 25%, candele 15%, medie 15%, regolarità del trend 15%, volatilità 10%, volume 10%, forza contro SPY 10%;
    percentili tra gli ETF dei temi, ultimi 3 mesi);
  - punteggio del tema = media dei suoi ETF; d5 = variazione rispetto allo stesso calcolo di 5 sedute prima;
  - stadio come Ratatouille (stage()): LEADING, FADING, BUILDING, SLIPPING, HOLDING, RECOVERY, WEAK, BEARISH.
Uso nella lista (daily.build): long solo con tema LEADING o BUILDING (FADING se lo studio 20% ha -20% >= 200 nelle
ultime 10 sedute); titoli senza tema in classifica: nessun filtro; prima i temi LEADING, poi BUILDING.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from . import basket_score as BS
from . import config as C

log = logging.getLogger("jeffcoach.themes")

STAGE_ORDER = {"LEADING": 0, "BUILDING": 1}


def stage(score: float, d5: float) -> str:
    """Stadio del tema come `_sector_signal` di Ratatouille (copia di Martin-coach)."""
    if score >= 70:
        return "LEADING" if d5 >= 0 else "FADING"
    if score >= 55:
        return "BUILDING" if d5 > 2 else ("SLIPPING" if d5 < -3 else "HOLDING")
    if d5 > 3:
        return "RECOVERY"
    return "WEAK" if score >= 40 else "BEARISH"


def break_ties(closes: pd.DataFrame, theme_groups: dict[str, list[str]], ties: dict[str, list[str]],
               window: int = 60, min_members: int = 3) -> dict[str, str]:
    """Copia di Martin-coach: titolo in pari merito tra più temi (stesso numero di ETF), vince il tema con cui si
    muove di più (correlazione delle variazioni % con la mediana degli altri membri del tema)."""
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


def _dv(df: Optional[pd.DataFrame], n: int = 20) -> float:
    if df is None or not len(df):
        return 0.0
    d = df.iloc[-n:]
    return float((d.Close * d.Volume).mean())


def _ret(df: pd.DataFrame, n: int = 21) -> Optional[float]:
    c = df.Close.dropna()
    return float((c.iloc[-1] / c.iloc[-1 - n] - 1) * 100) if len(c) > n else None


def build(daily: dict[str, pd.DataFrame], spx: pd.Series, universe: set[str], metrics: dict[str, dict], tmap: dict) -> dict:
    """Ritorna {"rows": [...], "ticker": {titolo: tema}, "map_built"}. Righe in ordine di punteggio."""
    from . import themes_map as TM
    bench = daily.get(C.BASKET_BENCHMARK)
    theme_etfs = tmap.get("theme_etfs") or {}
    all_etfs = sorted({e for v in theme_etfs.values() for e in v})
    tetfs = [e for e in all_etfs if e in daily and _dv(daily[e]) >= C.THEME_ETF_DV_MIN]
    esc = BS.universe_scores(daily, tetfs, bench)
    cut = {e: daily[e].iloc[:-5] for e in tetfs + [C.BASKET_BENCHMARK] if e in daily}
    esc_prev = BS.universe_scores(cut, tetfs, cut.get(C.BASKET_BENCHMARK))
    if esc is None or not len(esc):
        raise RuntimeError("nessun ETF dei temi con dati sufficienti")

    liquid = {s for s in universe if (metrics.get(s) or {}).get("adv") and metrics[s]["adv"] >= C.THEME_DV_MIN}
    mapped = TM.groups_from_map(tmap, liquid)
    try:                                   # punteggio a 7 fattori dei titoli: ordine dei nomi tra parentesi (Martin)
        ssc = BS.universe_scores(daily, sorted(liquid), bench)
        fs = ssc["Final_Score"].to_dict() if len(ssc) else {}
    except Exception as e:
        log.warning("punteggi a 7 fattori dei titoli: %s", e)
        fs = {}
    spy21 = _ret(bench) if bench is not None else None
    rows = []
    for th, es in theme_etfs.items():
        basis = [e for e in es if e in esc.index]
        st = BS.basket_stats(basis, esc) if basis else None
        if st is None:
            continue
        mem = sorted(mapped.get(th, []), key=lambda x: (x not in fs, -fs.get(x, 0), -(metrics[x].get("adv") or 0)))
        r21 = [x for x in (_ret(daily[e]) for e in basis) if x is not None]
        ret21 = sum(r21) / len(r21) if r21 else None
        row = dict(theme=th, etfs=basis, n=len(mem), members=mem, score=st["score"], ret21=ret21,
                   rs21=(ret21 - spy21) if (ret21 is not None and spy21 is not None) else None,
                   ret3m=st["ret3m"], source=(tmap.get("themes") or {}).get(th, "etf"))
        pv = BS.basket_stats(basis, esc_prev) if esc_prev is not None and len(esc_prev) else None
        row["d5"] = round(st["score"] - pv["score"], 1) if pv else 0.0
        row["stage"] = stage(st["score"], row["d5"])
        rows.append(row)
    rows.sort(key=lambda r: -r["score"])
    for k, r in enumerate(rows, 1):
        r["rank"] = k
        r["leading"] = r["stage"] == "LEADING"
        r["trend"] = {"LEADING": "up", "BUILDING": "up", "SLIPPING": "down", "WEAK": "down", "BEARISH": "down"}.get(r["stage"], "neutral")

    # tema di ogni titolo (come Martin): il tema col punteggio più alto che lo contiene, mai un generico; poi il
    # principale della mappa se è in classifica; pari merito tra temi: decide l'andamento
    ranked = {r["theme"] for r in rows}
    generic = frozenset(TM.GENERIC_GROUPS)
    tick: dict[str, str] = {}
    for r in rows:
        if r["theme"] in generic:
            continue
        for t in r["members"]:
            tick.setdefault(t, r["theme"])
    tinfo = tmap.get("tickers") or {}
    for s, info in tinfo.items():
        if s in liquid and info.get("primary") in ranked:
            tick[s] = info["primary"]
    try:
        ties = {s: [th for th in info["tied"] if th in ranked] for s, info in tinfo.items()
                if s in liquid and info.get("tied")}
        ties = {s: v for s, v in ties.items() if len(v) > 1}
        map_groups = {k: v for k, v in mapped.items() if len(v) >= C.THEME_MIN_MEMBERS}
        cols = sorted(({s for s in ties} | {x for v in map_groups.values() for x in v}) & set(daily))
        closes = pd.DataFrame({s: daily[s].Close for s in cols}).iloc[-62:]
        tick.update(break_ties(closes, map_groups, ties, min_members=C.THEME_MIN_MEMBERS))
    except Exception as e:
        log.warning("pari merito temi: %s", e)
    for r in rows:
        r["members"] = r["members"][:10]
        for k, v in list(r.items()):
            if isinstance(v, (np.floating,)):
                r[k] = float(v)
    return {"rows": rows, "ticker": tick, "map_built": tmap.get("built_utc"), "membership": tmap.get("membership")}
