"""Temi: gruppi di titoli e loro punteggio (design_modulo_temi.md).

Versione 1 (prototipo):
  - gruppi base = industria Yahoo (la mappa automatica da filing/ETF/notizie arriverà nel passo successivo);
  - gruppi emergenti = titoli che si muovono insieme (correlazione delle variazioni % giornaliere su 40 e 60
    sedute, QQQ escluso dal calcolo [RONIN 12/10]) e che appartengono a industrie diverse;
  - punteggio per tema e variazione del rango rispetto a 5 sedute prima.
"""
from __future__ import annotations

import json
from datetime import date

from typing import Optional

import numpy as np
import pandas as pd

from . import config as C


def _clusters(returns: pd.DataFrame, threshold: float) -> list[list[str]]:
    """Gruppi a legame medio: si uniscono i gruppi finché la correlazione media tra loro supera la soglia."""
    cols = list(returns.columns)
    if len(cols) < 2:
        return []
    corr = np.nan_to_num(returns.corr().to_numpy(), nan=0.0)
    n = len(cols)
    S = corr.copy()                       # somma delle correlazioni tra gruppi
    size = np.ones(n)
    alive = np.ones(n, dtype=bool)
    groups = {i: [i] for i in range(n)}
    while True:
        avg = S / np.outer(size, size)
        np.fill_diagonal(avg, -np.inf)
        avg[~alive, :] = -np.inf
        avg[:, ~alive] = -np.inf
        a, b = np.unravel_index(np.argmax(avg), avg.shape)
        if avg[a, b] <= threshold:
            break
        S[a, :] += S[b, :]
        S[:, a] += S[:, b]
        S[a, a] = 0.0
        size[a] += size[b]
        alive[b] = False
        groups[a] += groups.pop(b)
    return [[cols[i] for i in g] for g in groups.values() if len(g) >= C.THEME_MIN_MEMBERS]


def correlation_groups(closes: pd.DataFrame) -> list[list[str]]:
    """Gruppi stabili: presenti (con almeno il 75% dei membri in comune) sia a 40 sia a 60 sedute."""
    rets = closes.pct_change().iloc[1:]
    res = {}
    for w in C.CORR_WINDOWS:
        sub = rets.iloc[-w:].dropna(axis=1, how="any")
        res[w] = _clusters(sub, C.CORR_THRESHOLD)
    a, b = res[C.CORR_WINDOWS[0]], res[C.CORR_WINDOWS[1]]
    out = []
    for g in a:
        for h in b:
            common = set(g) & set(h)
            if len(common) >= C.THEME_MIN_MEMBERS and len(common) >= 0.75 * min(len(g), len(h)):
                out.append(sorted(common))
                break
    return out


def score_groups(groups: dict[str, list[str]], metrics: dict[str, dict], closes: pd.DataFrame,
                 qqq_close: pd.Series, potent_hist: dict[str, list[str]], min_members: Optional[int] = None,
                 bscores: Optional[pd.DataFrame] = None, etfs: Optional[dict[str, list[str]]] = None,
                 bscores_prev: Optional[pd.DataFrame] = None) -> list[dict]:
    """Componenti del tema (breadth, forza nei giorni rossi, scan... servono a fasi e messaggi) e classifica.
    - Con `etfs` ({tema: [ETF]}) e `bscores` = punteggi a 7 fattori degli ETF: il tema si misura direttamente sui suoi
      ETF [RONIN 16/10, Andrea: "usa direttamente l'ETF al posto dei singoli titoli"]. Punteggio = media del
      Final_Score dei suoi ETF (percentili calcolati tra gli ETF dei temi); anche breadth, RS e tenuta nei giorni rossi
      sono quelli degli ETF. I titoli (`groups`) restano solo come membri: tema di ogni titolo e conteggio negli scan.
    - Con `bscores` dei titoli e senza `etfs`: basket di Ratatouille, media del Final_Score dei titoli del tema.
    - Senza `bscores`: vecchio metodo, media dei ranghi delle 7 misure del tema.
    Con `bscores_prev` (stessi punteggi calcolati 5 sedute fa): d5 = variazione del punteggio e stadio di Ratatouille
    (stage(): LEADING, FADING, BUILDING, SLIPPING, HOLDING, RECOVERY, WEAK, BEARISH)."""
    from . import basket_score as BS
    rets = closes.pct_change()
    q = qqq_close.reindex(closes.index).pct_change()
    red = q.iloc[-C.RED_DAY_LOOKBACK:]
    red_days = red[red < 0].index
    scan_count: dict[str, int] = {}
    for d, names in potent_hist.items():
        for n in names:
            scan_count[n] = scan_count.get(n, 0) + 1
    use_bs = bscores is not None and len(bscores)
    rows = []
    names = list(etfs) if etfs is not None else list(groups)
    for name in names:
        mem = [t for t in groups.get(name, []) if t in metrics]
        if etfs is not None:
            basis = [e for e in etfs[name] if e in metrics and (not use_bs or e in bscores.index)]
            if not basis:
                continue
        else:
            basis = mem
            if len(mem) < (min_members or C.THEME_MIN_MEMBERS):
                continue
        ms = [metrics[t] for t in basis]
        lead = np.mean([m["list"] == "Leading" for m in ms])
        above21 = np.mean([m["close"] > m["e21"] for m in ms])
        rs = np.nanmedian([m.get("rs21") if m.get("rs21") is not None else np.nan for m in ms])
        cols = [t for t in basis if t in rets.columns]
        if len(red_days) and cols:
            redrs = float(np.nanmean(rets.loc[red_days, cols].mean(axis=1) - q.loc[red_days]) * 100)
        else:
            redrs = np.nan
        scans = sum(1 for t in mem if scan_count.get(t))
        liq = np.nanmedian([m["dv20"] / m["dv60"] if m["dv60"] else np.nan for m in ms])
        struct = np.mean([m["e9"] > m["e21"] for m in ms])
        top = sorted(ms, key=lambda m: m.get("ret21") or -999, reverse=True)[:3]
        ext50_top = float(np.mean([m["ext50"] or 0 for m in top]))
        row = dict(theme=name, n=len(mem), members=mem, lead=lead, above21=above21, rs21=rs, red_rs=redrs,
                   scans5=scans, liq=liq, struct=struct, ext50_top=ext50_top)
        if etfs is not None:
            row["etfs"] = basis
        if use_bs:
            st = BS.basket_stats(basis, bscores)
            if st is None:          # nessun titolo/ETF con storia sufficiente (es. IPO, ETF nuovo): fuori classifica
                continue
            row.update(st)
            if bscores_prev is not None and len(bscores_prev):
                pv = BS.basket_stats(basis, bscores_prev)
                if pv is not None:
                    row["score_prev"] = pv["score"]
                    row["d5"] = round(st["score"] - pv["score"], 1)
                    if C.THEME_STAGES:
                        row["stage"] = stage(st["score"], row["d5"])
        rows.append(row)
    if not rows:
        return []
    df = pd.DataFrame(rows)
    if not use_bs:
        comps = ["lead", "above21", "rs21", "red_rs", "scans5", "liq", "struct"]
        df["score"] = sum(df[c].rank(pct=True, na_option="bottom") for c in comps) / len(comps) * 100
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = np.arange(1, len(df) + 1)
    return df.to_dict("records")


def stage(score: float, d5: float) -> str:
    """Stadio del tema come `_sector_signal` di Ratatouille (Screener/update_archive.py): punteggio e sua variazione
    a 5 sedute."""
    if score >= 70:
        return "LEADING" if d5 >= 0 else "FADING"
    if score >= 55:
        return "BUILDING" if d5 > 2 else ("SLIPPING" if d5 < -3 else "HOLDING")
    if d5 > 3:
        return "RECOVERY"
    return "WEAK" if score >= 40 else "BEARISH"


def add_phase(rows: list[dict], prev_ranks: dict[str, int]) -> list[dict]:
    """Fase del tema: maturità, accensione, preparazione (risale la classifica), attivo, neutro."""
    n = len(rows)
    for r in rows:
        pr = prev_ranks.get(r["theme"])
        r["rank_prev"] = pr
        r["rank_change"] = (pr - r["rank"]) if pr else None
        if r["ext50_top"] >= 40:
            r["phase"] = "maturità"
        elif r["scans5"] >= 3:
            r["phase"] = "accensione"
        elif r["rank_change"] is not None and r["rank_change"] >= max(3, n // 10) and (r["red_rs"] or 0) > 0:
            r["phase"] = "preparazione"
        elif r["rank"] <= max(3, n // 10):
            r["phase"] = "attivo"
        else:
            r["phase"] = "neutro"
    return rows


def ticker_theme(rows: list[dict], exclude: frozenset = frozenset()) -> dict[str, str]:
    """Per ogni titolo, il tema col punteggio più alto a cui appartiene (esclusi i temi in `exclude`)."""
    out: dict[str, str] = {}
    for r in sorted(rows, key=lambda x: x["score"], reverse=True):
        if r["theme"] in exclude:
            continue
        for t in r["members"]:
            out.setdefault(t, r["theme"])
    return out


def theme_rank_pct(rows: list[dict]) -> dict[str, float]:
    n = len(rows)
    return {r["theme"]: 1 - (r["rank"] - 1) / max(1, n - 1) for r in rows}


def load_prev_ranks(hist_dir, before: date, sessions_back: int = 5) -> dict[str, int]:
    files = sorted(p for p in hist_dir.glob("themes_*.json") if p.stem[7:] < before.isoformat())
    if len(files) < sessions_back:
        return {} if not files else json.loads(files[0].read_text(encoding="utf-8"))
    return json.loads(files[-sessions_back].read_text(encoding="utf-8"))


def proposals(closes: pd.DataFrame, theme_groups: dict[str, list[str]], unmapped: list[str], window: int = 60,
              min_corr: float = 0.60, min_members: int = 3) -> list[dict]:
    """Titoli senza tema che si muovono con un tema (correlazione delle variazioni % con la mediana del tema)."""
    rets = closes.pct_change().iloc[-window:]
    med = {}
    for th, mem in theme_groups.items():
        cols = [t for t in mem if t in rets.columns]
        if len(cols) >= min_members:
            med[th] = rets[cols].median(axis=1)
    out = []
    for t in unmapped:
        if t not in rets.columns or rets[t].isna().sum() > window // 4:
            continue
        best = max(((th, float(rets[t].corr(m))) for th, m in med.items()), key=lambda x: (x[1] if x[1] == x[1] else -1),
                   default=None)
        if best and best[1] == best[1] and best[1] >= min_corr:
            out.append({"ticker": t, "theme": best[0], "corr": round(best[1], 2)})
    return sorted(out, key=lambda r: -r["corr"])


def break_ties(closes: pd.DataFrame, theme_groups: dict[str, list[str]], ties: dict[str, list[str]],
               window: int = 60, min_members: int = 3) -> dict[str, str]:
    """Titolo in pari merito tra più temi (stesso numero di ETF): vince il tema con cui si muove di più
    (correlazione delle variazioni % con la mediana degli altri membri del tema) [RONIN 15/10]."""
    rets = closes.pct_change().iloc[-window:]
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



from .rs_chart import add_rs, quadrant  # noqa: E402,F401  (RS settimana / mese dei basket, 21/10)
