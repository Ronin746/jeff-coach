"""Pool dei titoli monitorati e sue liste Leading / Mediocre / Lagging [ANDREA 20/10].

Portato dal bot di Martin (Ronin746/Martin-coach, martincoach/pool.py), dove lo studio delle 99 trascrizioni delle live
ha tarato le soglie: i titoli di cui Martin parla hanno dollar volume alto, ADR oltre il 3,5% e forza relativa a 3-6 mesi
nell'alto dell'universo. Qui l'universo e' quello di Jeff Sun, quindi il pool e' la sua watchlist ricostruita.

Regola (ogni giorno, solo dati fino alla chiusura):
  candidati = dollar volume a 20 sedute nel 30% piu' alto dell'universo e percentile di forza relativa (rendimento a 3 o
              6 mesi tra i titoli liquidi) almeno POOL_RS_MIN in un momento qualsiasi degli ultimi 6 mesi,
              piu' ADR a 20 sedute almeno POOL_ADR_MIN;
  liste     = Leading se prezzo > EMA50 > EMA150, Lagging se prezzo < EMA50 < EMA150, Mediocre il resto.
Flusso: ogni titolo del pool che scende di una lista vale -1, due liste -2, chi sale + (in quota dei titoli del pool alla
data di partenza). Il flusso a 5 sedute e la tendenza dei flussi giornalieri decidono il regime (regime.pool_state).
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
    rsmax = np.maximum(p63.rolling(126, min_periods=20).max(), p126.rolling(126, min_periods=20).max())
    big = (c.pct_change(fill_method=None) >= 0.04).astype(float).where(c.notna()).rolling(60, min_periods=20).sum()
    cand = (dv20.rank(axis=1, pct=True) >= C.POOL_DV_RANK) & (rsmax >= C.POOL_RS_MIN) & c.notna()
    if C.POOL_ADR_MIN is not None:             # [19/10c, Andrea] ADR a 20 sedute almeno 3,5%
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
        members={s: lab(t, s) for s in members},
        moved_5d=sorted(moved),
        down_5d=sum(1 for _, a, b in moved if (a, b) in (("Leading", "Mediocre"), ("Mediocre", "Lagging"), ("Leading", "Lagging"))),
        up_5d=sum(1 for _, a, b in moved if (a, b) in (("Mediocre", "Leading"), ("Lagging", "Mediocre"), ("Lagging", "Leading"))),
    )
