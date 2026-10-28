"""Supporti e resistenze orizzontali su daily e weekly, come linee o come aree [RONIN 23/10, Andrea: "migliorare l'individuazione
di supporti e resistenze orizzontali, anche nella forma di area"; i livelli bianchi dei suoi grafici TradingView].

Regole (scala logaritmica, numeri in config.py con prefisso HZ_):
- punti = swing del daily degli ultimi HZ_LOOKBACK giorni: massimi e minimi di 2k+1 barre (k = HZ_PIVOT_K, 5 barre:
  con 7 o 11 barre si perdevano i doppi massimi e i ritest dei grafici di Andrea, KLAC 236,90 e 266,67);
- un livello è un gruppo di swing entro HZ_TOL_ADR ADR l'uno dall'altro: almeno HZ_MIN_TOUCHES tocchi; valgono sia i
  massimi sia i minimi (un vecchio massimo che diventa supporto è un livello più forte: cambio di ruolo);
- punteggio = tocchi pesati per la reazione (uno swing che si allontana di HZ_REACT_ADR ADR vale 1) + cambio di ruolo
  + recenza − attraversamenti (chiusure che passano da una parte all'altra
  senza fermarsi: un livello tagliato tante volte conta poco); si prendono i migliori, uno alla volta, finché i gruppi
  non si sovrappongono e restano ad almeno HZ_GAP_ADR ADR l'uno dall'altro; servono almeno HZ_MIN_SCORE punti;
- se i tocchi del gruppo sono sparsi per almeno HZ_ZONE_MIN_ADR ADR il livello è un'AREA (rettangolo dal tocco più basso al
  più alto), altrimenti una LINEA al prezzo mediano dei tocchi.
- lo stesso sul weekly (settimane fatte dal daily, ultimi HZ_W_LOOKBACK settimane, ~5 anni) per i livelli di mesi e anni
  prima [Andrea 23/10: "usa anche il timeframe weekly e daily su una più ampia scala"], con tolleranze e reazioni in
  proporzione; i weekly valgono HZ_W_BONUS punti in più e nell'edge S&R pesano come un livello weekly;
- tra daily e weekly, due livelli a meno di HZ_GAP_ADR ADR: resta il più forte.
Le funzioni sono pure: la lista le usa come livelli (S&R) e il grafico degli alert le disegna, le stesse.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from . import config as C
from . import indicators as I


def _pivots(df: pd.DataFrame, k: int, lookback: int) -> list[tuple[int, float, str]]:
    """(posizione, prezzo, 'H'|'L') degli swing (massimo/minimo di 2k+1 barre) delle ultime `lookback` barre."""
    n = len(df)
    hi, lo = df.High.to_numpy(dtype=float), df.Low.to_numpy(dtype=float)
    out = [(p, hi[p], "H") for p in I.swing_highs(df, k, min(lookback, n))]
    out += [(p, lo[p], "L") for p in I.swing_lows(df, k, min(lookback, n))]
    return sorted(out)


def _params(tf: str) -> dict:
    """Soglie per timeframe: 'D' daily (ultimi ~14 mesi), 'W' weekly (ultimi ~5 anni, livelli di mesi e anni prima)."""
    if tf == "W":
        return dict(k=C.HZ_W_PIVOT_K, lookback=C.HZ_W_LOOKBACK, tol=C.HZ_W_TOL_ADR, react_bars=C.HZ_W_REACT_BARS,
                    react=C.HZ_W_REACT_ADR, recency=C.HZ_W_RECENCY, zone=C.HZ_W_ZONE_MIN_ADR, min_bars=30)
    return dict(k=C.HZ_PIVOT_K, lookback=C.HZ_LOOKBACK, tol=C.HZ_TOL_ADR, react_bars=C.HZ_REACT_BARS,
                react=C.HZ_REACT_ADR, recency=C.HZ_RECENCY_DAYS, zone=C.HZ_ZONE_MIN_ADR, min_bars=40)


def _levels(df: pd.DataFrame, adr: float, tf: str) -> list[dict]:
    """Livelli di un timeframe (barre di `df`, ADR daily in %), dal più forte, senza filtro di distanza tra loro."""
    P = _params(tf)
    n = len(df)
    if n < P["min_bars"] or not adr or adr <= 0:
        return []
    piv = _pivots(df, P["k"], P["lookback"])
    if len(piv) < C.HZ_MIN_TOUCHES:
        return []
    tol = math.log(1 + P["tol"] * adr / 100)
    lp = np.array([math.log(v) for _, v, _ in piv])
    # peso di ogni tocco = quanto il prezzo si è allontanato dallo swing (prima o dopo, react_bars barre) rispetto a
    # react ADR: uno swing vero conta 1, un'esitazione di poche candele quasi niente
    lh, ll = np.log(df.High.to_numpy(dtype=float)), np.log(df.Low.to_numpy(dtype=float))
    rb, full = P["react_bars"], math.log(1 + P["react"] * adr / 100)
    wt = np.empty(len(piv))
    for j, (p, v, kind) in enumerate(piv):
        a, b = max(0, p - rb), min(n, p + rb + 1)
        away = (lp[j] - min(ll[a:p + 1].min(), ll[p:b].min())) if kind == "H" else \
            (max(lh[a:p + 1].max(), lh[p:b].max()) - lp[j])
        wt[j] = min(1.0, max(0.0, away) / full)
    cl = np.log(df.Close.to_numpy(dtype=float)[max(0, n - P["lookback"]):])
    free = np.ones(len(piv), dtype=bool)
    out: list[dict] = []
    while free.any():
        best, best_key = None, None
        for i in np.flatnonzero(free):
            mem = np.flatnonzero(free & (np.abs(lp - lp[i]) <= tol))
            if len(mem) < C.HZ_MIN_TOUCHES:
                continue
            lo_l, hi_l = lp[mem].min(), lp[mem].max()
            kinds = {piv[j][2] for j in mem}
            last = max(piv[j][0] for j in mem)
            # attraversamenti: chiusure che passano da sopra a sotto la fascia (o il contrario) senza fermarcisi dentro
            side = np.where(cl > hi_l + tol / 2, 1, np.where(cl < lo_l - tol / 2, -1, 0))
            sd = side[side != 0]
            cross = int((np.diff(sd) != 0).sum()) if len(sd) > 1 else 0
            recency = math.exp(-(n - 1 - last) / P["recency"])
            score = (float(wt[mem].sum()) + (C.HZ_ROLE_BONUS if len(kinds) == 2 else 0) + recency
                     - C.HZ_CROSS_PENALTY * max(0, cross - C.HZ_CROSS_FREE))
            key = (round(score, 6), len(mem), last)
            if best_key is None or key > best_key:
                best_key, best = key, dict(mem=mem, lo=lo_l, hi=hi_l, mid=float(np.median(lp[mem])), last=last,
                                           cross=cross, score=score)
        if best is None:
            break
        free[best["mem"]] = False
        if best["score"] < C.HZ_MIN_SCORE:
            continue
        mem = best["mem"]
        zone = (math.exp(best["hi"] - best["lo"]) - 1) * 100 >= P["zone"] * adr
        mid = float(math.exp(best["mid"]))
        out.append(dict(tf=tf, kind="zone" if zone else "line", price=mid,
                        lo=float(math.exp(best["lo"])) if zone else mid, hi=float(math.exp(best["hi"])) if zone else mid,
                        touches=int(len(mem)), highs=int(sum(piv[j][2] == "H" for j in mem)),
                        lows=int(sum(piv[j][2] == "L" for j in mem)),
                        first=str(df.index[min(piv[j][0] for j in mem)].date()), last=str(df.index[best["last"]].date()),
                        crossings=best["cross"], score=round(best["score"] + (C.HZ_W_BONUS if tf == "W" else 0), 2)))
    return out


def find_levels(df: pd.DataFrame, adr: float) -> list[dict]:
    """Livelli orizzontali significativi su daily e weekly (le settimane fatte dal daily di `df`, l'ultima barra è la
    seduta di riferimento), dal più forte al più debole: {tf 'D'|'W', kind 'line'|'zone', price, lo, hi, touches, highs,
    lows, first, last, crossings, score}. I weekly vedono i livelli di mesi e anni prima e valgono di più (HZ_W_BONUS);
    due livelli a meno di HZ_GAP_ADR ADR non stanno insieme: resta il più forte."""
    if df is None or len(df) < 40 or not adr or adr <= 0:
        return []
    cand = _levels(df, adr, "D")
    try:
        cand += _levels(I.weekly(df), adr, "W")
    except Exception:
        pass
    pad = math.log(1 + C.HZ_GAP_ADR * adr / 100)
    levels: list[dict] = []
    for lv in sorted(cand, key=lambda x: -x["score"]):
        near = [x for x in levels
                if math.log(lv["lo"]) - pad <= math.log(x["hi"]) and math.log(x["lo"]) <= math.log(lv["hi"]) + pad]
        if near:
            if lv["tf"] == "W":                # un weekly sullo stesso prezzo conferma il daily: diventa un livello weekly
                for x in near:
                    x["tf"] = "W"
            continue
        levels.append(lv)
        if len(levels) >= C.HZ_MAX_LEVELS:
            break
    return levels


def name(lv: dict) -> str:
    """Nome per la confluenza, con timeframe e tocchi: 'HZW 164.60-169.81 x7' (area weekly), 'HL 236.36 x2' (linea
    daily)."""
    w = "W" if lv.get("tf") == "W" else ""
    if lv["kind"] == "zone":
        return f"HZ{w} {lv['lo']:.2f}-{lv['hi']:.2f} x{lv['touches']}"
    return f"HL{w} {lv['price']:.2f} x{lv['touches']}"


def is_name(name: str) -> bool:
    return name.split(" ", 1)[0] in ("HZ", "HL", "HZW", "HLW")


def touches_of(name: str) -> int:
    """Tocchi dal nome ('HZ ... x7' -> 7); 0 se il nome non è di un livello orizzontale."""
    if not is_name(name):
        return 0
    try:
        return int(name.rsplit(" x", 1)[1])
    except (IndexError, ValueError):
        return 0


def as_levels(levels: list[dict], close: float) -> dict:
    """Livelli per la confluenza: {'long': supporti, 'short': resistenze}. Le aree hanno 'lo' e 'hi' (la distanza dal
    livello d'ingresso si misura dal bordo); un'area con il close dentro vale per i due lati."""
    sup, res = [], []
    for lv in levels:
        x = {"name": name(lv), "price": lv["price"], "lo": lv["lo"], "hi": lv["hi"]}
        if lv["lo"] < close:
            sup.append(x)
        if lv["hi"] > close:
            res.append(x)
    return {"long": sup, "short": res}


def near(levels: list[dict], price: float, adr: float, max_adr: float = 1.0) -> Optional[dict]:
    """Il livello orizzontale più vicino a `price` entro `max_adr` ADR (0 se il prezzo è dentro l'area)."""
    best = None
    for lv in levels:
        d = 0.0 if lv["lo"] <= price <= lv["hi"] else min(abs(lv["lo"] / price - 1), abs(lv["hi"] / price - 1)) * 100
        if d <= max_adr * adr and (best is None or d < best[0]):
            best = (d, lv)
    return best[1] if best else None
