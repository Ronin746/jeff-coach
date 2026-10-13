"""Regime di mercato [RONIN 13/10] — stessa logica di Martin-coach (martincoach/engine.py e data.py).

Il Market Monitor di Stockbee (letto dal repo pubblico di NEL) decide: Expansion -> LONG, Defensive -> SHORT,
Mixed -> MIXED. Il punteggio sugli indici (QQQ e IWM: trend EMA9/21 e EMA50; stato MM ±1; T2108 a 5 sedute ±1)
resta come contesto e decide solo se manca la riga del Market Monitor della seduta.
JeffCoach è solo long: come si usa il bias è scritto in config (REGIME_*) e applicato in daily.build().
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import pandas as pd

from . import config as C

log = logging.getLogger("jeffcoach.regime")
MM_FILE = C.STATE / "market_monitor.json"


def fetch_market_monitor() -> list[dict]:
    """Righe del Market Monitor dalla più recente; se la rete non risponde, l'ultima copia salvata."""
    import urllib.request
    for url in C.MM_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "JeffCoach/2.0"})
            rows = json.loads(urllib.request.urlopen(req, timeout=60).read())
            if isinstance(rows, list) and rows and "date" in rows[0]:
                rows = rows[:300]
                C.STATE.mkdir(parents=True, exist_ok=True)
                tmp = MM_FILE.with_suffix(".tmp")
                tmp.write_text(json.dumps(rows), encoding="utf-8")
                tmp.replace(MM_FILE)
                return rows
        except Exception as e:
            log.warning("Market Monitor %s: %s", url, e)
    if MM_FILE.exists():
        log.warning("Market Monitor: uso la copia salvata")
        return json.loads(MM_FILE.read_text(encoding="utf-8"))
    return []


def mm_state(row: dict) -> Optional[str]:
    if not row or any(row.get(k) is None for k in ("ratio5", "ratio10", "up4", "down4")):
        return None
    if (row["down4"] >= C.MM_DEF_DOWN4 or row["ratio10"] < C.MM_DEF_RATIO10
            or (row["ratio5"] < C.MM_DEF_RATIO5 and row["down4"] > row["up4"] * 2)):
        return "Defensive"
    if (row["ratio10"] >= C.MM_EXP_RATIO10 and row["ratio5"] >= C.MM_EXP_RATIO5 and row["up4"] >= C.MM_EXP_UP4
            and row["down4"] < C.MM_EXP_DOWN4):
        return "Expansion"
    return "Mixed"


def market_monitor(rows: list[dict], as_of) -> Optional[dict]:
    day = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)
    i = next((k for k, r in enumerate(rows or []) if r.get("date") == day), None)
    if i is None:
        return None
    r = rows[i]
    st = mm_state(r)
    if st is None:
        return None
    old = rows[i + 5] if i + 5 < len(rows) else None
    d5 = (r["t2108"] - old["t2108"]) if (old and r.get("t2108") is not None and old.get("t2108") is not None) else None
    return dict(date=day, state=st, up4=r["up4"], down4=r["down4"], ratio5=r["ratio5"], ratio10=r["ratio10"],
                t2108=r.get("t2108"), t2108_d5=None if d5 is None else round(d5, 2))


def index_state(df: Optional[pd.DataFrame]) -> dict:
    if df is None or len(df) < 60:
        return {}
    c = df.Close.astype(float)
    e9, e21, e50 = (c.ewm(span=n, adjust=False).mean().iloc[-1] for n in (9, 21, 50))
    last = c.iloc[-1]
    trend = 1 if (last > e21 and e9 > e21) else (-1 if (last < e21 and e9 < e21) else 0)
    return dict(close=round(float(last), 2), above21=bool(last > e21), above50=bool(last > e50), e9_gt_21=bool(e9 > e21),
                trend=trend, ret21=round(float((last / c.iloc[-22] - 1) * 100), 2))


def regime(indices: dict[str, dict], mm: Optional[dict]) -> dict:
    score, why = 0, []
    q, iwm = indices.get("QQQ") or {}, indices.get("IWM") or {}
    if q:
        score += q["trend"] + (1 if q["above50"] else -1)
        why.append(f"QQQ trend {q['trend']:+d}, {'above' if q['above50'] else 'below'} EMA50")
    if iwm:
        score += iwm["trend"]
        why.append(f"IWM trend {iwm['trend']:+d}")
        if q and iwm.get("ret21") is not None and q.get("ret21") is not None and iwm["ret21"] < q["ret21"] - 3:
            why.append("IWM lagging QQQ (caution)")
    if mm is not None:
        score += {"Expansion": 1, "Defensive": -1}.get(mm["state"], 0)
        if mm.get("t2108_d5") is not None:
            score += 1 if mm["t2108_d5"] >= C.MM_T2108_DELTA else -1 if mm["t2108_d5"] <= -C.MM_T2108_DELTA else 0
            why.append(f"T2108 5d {mm['t2108_d5']:+.1f}pp")
    score_bias = "LONG" if score >= C.BIAS_LONG_MIN else ("SHORT" if score <= C.BIAS_SHORT_MAX else "MIXED")
    if mm is not None:
        bias = C.MM_BIAS[mm["state"]]
        why.insert(0, f"Market Monitor {mm['state']} → {bias}; index score {score:+d} ({score_bias})")
    else:
        bias = score_bias
        why.insert(0, f"Market Monitor unavailable: index score {score:+d} → {bias}")
    return {"bias": bias, "score": score, "score_bias": score_bias, "why": why, "market_monitor": mm, "indices": indices}
