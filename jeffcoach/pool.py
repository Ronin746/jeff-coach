"""Il "pool" di Martin: i titoli che avrebbe nelle sue liste Leading / Mediocre / Lagging [RONIN 17/10o, Andrea].

Studio (studi/pool_martin.py, 99 trascrizioni + log delle live, ott 2025 - ott 2026, 1.170 menzioni di 218 titoli):
i titoli di cui parla Martin hanno un dollar volume mediano di 1,3 mld$/giorno (10° percentile ~200M$), ADR mediano 6,4%,
+132% dal minimo a 52 settimane, 12 sedute da +4% nelle ultime 60, e il 75% è stato tra i primi ~8% per forza relativa a
3 mesi negli ultimi 6 mesi (leader o ex-leader). Liste: 53% Leading, 34% Mediocre, 13% Lagging.

Regola (ogni giorno, solo dati fino alla chiusura):
  candidati = dollar volume a 20 sedute nel 30% più alto dell'universo e percentile di forza relativa (rendimento a 3 o
              6 mesi tra i titoli liquidi) almeno POOL_RS_MIN in un momento qualsiasi degli ultimi 6 mesi;
  pool      = i POOL_N candidati con il punteggio più alto (percentile ADR + percentile sedute da +4% a 60 giorni +
              forza relativa massima a 6 mesi).
Con 130 titoli copre il 67% delle menzioni (72% senza le mega cap, che Martin segue a parte come "pillars").
Le liste sono quelle di Martin: Leading = prezzo > EMA50 > EMA150, Lagging = prezzo < EMA50 < EMA150, Mediocre il resto.
Flusso: ogni titolo del pool che scende di una lista vale -1, due liste -2, chi sale + (in % dei titoli del pool alla
data di partenza: Martin li tiene in lista anche quando peggiorano).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from . import config as C


def _panels(daily: dict, syms: list[str], index: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    return {k: pd.DataFrame({s: daily[s][k].reindex(index) for s in syms if s in daily})
            for k in ("High", "Low", "Close", "Volume")}


def pool_breadth(daily: dict, syms: list[str], index: pd.DatetimeIndex, days: int = 12) -> Optional[dict]:
    """Pool di Martin e sue liste nelle ultime `days` sedute. `index`: date di riferimento (quelle del QQQ)."""
    P = _panels(daily, syms, index)
    c, h, l, v = P["Close"], P["High"], P["Low"], P["Volume"]
    if c.shape[1] < 50 or len(c) < 300:
        return None
    dv20 = (c * v).rolling(20, min_periods=10).mean()
    adr = ((h / l - 1) * 100).rolling(20, min_periods=10).mean()
    liq = dv20 >= C.POOL_LIQ_RS
    p63 = (c / c.shift(63) - 1).where(liq).rank(axis=1, pct=True)
    p126 = (c / c.shift(126) - 1).where(liq).rank(axis=1, pct=True)
    w = C.POOL_RS_WINDOW                       # finestra della forza massima (126 = 6 mesi; studio 27/10: 252)
    rsmax = np.maximum(p63.rolling(w, min_periods=20).max(), p126.rolling(w, min_periods=20).max())
    big = (c.pct_change(fill_method=None) >= 0.04).astype(float).where(c.notna()).rolling(60, min_periods=20).sum()
    cand = (dv20.rank(axis=1, pct=True) >= C.POOL_DV_RANK) & (rsmax >= C.POOL_RS_MIN) & c.notna()
    if C.POOL_ADR_REL is not None:             # ADR relativo al mercato del giorno (studio 27/10, studi/pool_martin/
        #                                        parametri.py): almeno POOL_ADR_REL volte l'ADR mediano dei titoli
        #                                        negoziabili (dv20 >= POOL_ADR_REL_DV, prezzo >= PRICE_MIN)
        trad = (dv20 >= C.POOL_ADR_REL_DV) & (c >= C.PRICE_MIN)
        cand &= adr.ge(C.POOL_ADR_REL * adr.where(trad).median(axis=1), axis=0)
    elif C.POOL_ADR_MIN is not None:           # [19/10c, Andrea] ADR a 20 sedute almeno 3,5%
        cand &= adr >= C.POOL_ADR_MIN
    if C.POOL_ADR_RANK is not None:            # [19/10b] soglie in percentile: la dimensione del pool segue il mercato
        cand &= adr.rank(axis=1, pct=True) >= C.POOL_ADR_RANK
    if C.POOL_BIG_RANK is not None:
        cand &= big.rank(axis=1, pct=True) >= C.POOL_BIG_RANK
    if C.POOL_MIN_UP_LOW is not None:          # [RONIN 19/10, Andrea] almeno +100% dal minimo a 52 settimane
        lo252 = l.rolling(252, min_periods=60).min()
        cand &= (c / lo252 - 1) >= C.POOL_MIN_UP_LOW
    if C.POOL_N:
        score = (adr.rank(axis=1, pct=True) + big.rank(axis=1, pct=True) + rsmax).where(cand)
        pool = score.rank(axis=1, ascending=False, method="first") <= C.POOL_N
    else:
        pool = cand
    e50 = c.ewm(span=50, adjust=False, min_periods=50).mean()
    e150 = c.ewm(span=150, adjust=False, min_periods=150).mean()
    nbar = c.notna().cumsum()
    lead = (c > e50) & (e50 > e150) & (nbar >= 160)
    lag = (c < e50) & (e50 < e150) & (nbar >= 160)
    med = (nbar >= 160) & ~lead & ~lag
    rank = (lead.astype(int) * 2 + med.astype(int)).where(lead | med | lag)

    def flow(k: int) -> pd.Series:
        base = pool.shift(k, fill_value=False)
        d = (rank - rank.shift(k)).where(base & rank.notna() & rank.shift(k).notna())
        return d.sum(axis=1) / base.sum(axis=1).replace(0, np.nan) * 100

    f1, f5 = flow(1), flow(5)
    L, M, G = (lead & pool).sum(axis=1), (med & pool).sum(axis=1), (lag & pool).sum(axis=1)
    # andamento delle tre liste in % [RONIN 27/10, Andrea]: pool di Martin e universo liquido della lista (dollar volume
    # a 5 sedute >= DV_MIN, prezzo >= PRICE_MIN, come la breadth della lista)
    uni = ((c * v).rolling(C.DV_DAYS, min_periods=C.DV_DAYS).mean() >= C.DV_MIN) & (c >= C.PRICE_MIN) & (nbar >= 160)
    npool, nuni = pool.sum(axis=1), uni.sum(axis=1)
    pc = lambda a, n, d: round(float(a[d] / n[d] * 100), 1) if n[d] else None
    uL, uM, uG = (lead & uni).sum(axis=1), (med & uni).sum(axis=1), (lag & uni).sum(axis=1)
    lists_hist = [dict(date=str(d.date()), n=int(npool[d]), L=pc(L, npool, d), M=pc(M, npool, d), G=pc(G, npool, d),
                       un=int(nuni[d]), uL=pc(uL, nuni, d), uM=pc(uM, nuni, d), uG=pc(uG, nuni, d))
                  for d in c.index[-C.LISTS_CHART_DAYS:]]
    tail = slice(-days, None)
    t, t5 = c.index[-1], c.index[-6]
    lab = lambda d, s: "Leading" if lead.at[d, s] else ("Lagging" if lag.at[d, s] else "Mediocre")
    members = [s for s in c.columns if pool.at[t, s]]
    moved = [(s, lab(t5, s), lab(t, s)) for s in c.columns if pool.at[t5, s] and rank.at[t, s] == rank.at[t, s]
             and rank.at[t5, s] == rank.at[t5, s] and rank.at[t, s] != rank.at[t5, s]]
    return dict(
        n=int(pool.loc[t].sum()),
        lists={"Leading": int(L.iloc[-1]), "Mediocre": int(M.iloc[-1]), "Lagging": int(G.iloc[-1])},
        lists_1d={"Leading": int(L.iloc[-2]), "Mediocre": int(M.iloc[-2]), "Lagging": int(G.iloc[-2])},
        lists_5d={"Leading": int(L.iloc[-6]), "Mediocre": int(M.iloc[-6]), "Lagging": int(G.iloc[-6])},
        share=float(L.iloc[-1] / max(1, L.iloc[-1] + G.iloc[-1]) * 100),
        lead_pct=float(L.iloc[-1] / max(1, L.iloc[-1] + M.iloc[-1] + G.iloc[-1]) * 100),   # Leading sul totale [19/10]
        flow5=round(float(f5.iloc[-1]), 1) if f5.iloc[-1] == f5.iloc[-1] else None,
        flow_daily=[round(float(x), 1) for x in f1.iloc[tail] if x == x],
        series={str(d.date()): dict(L=int(L[d]), M=int(M[d]), G=int(G[d])) for d in c.index[tail]},
        lists_hist=lists_hist,
        members={s: lab(t, s) for s in members},
        moved_5d=sorted(moved),
        down_5d=sum(1 for _, a, b in moved if (a, b) in (("Leading", "Mediocre"), ("Mediocre", "Lagging"), ("Leading", "Lagging"))),
        up_5d=sum(1 for _, a, b in moved if (a, b) in (("Mediocre", "Leading"), ("Lagging", "Mediocre"), ("Lagging", "Leading"))),
    )
