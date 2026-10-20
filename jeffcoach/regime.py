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
DISPLAY = {"SHORT": "DEFENSIVE"}
MM_FILE = C.STATE / "market_monitor.json"


def fetch_market_monitor() -> list[dict]:
    """Copia di Martin-coach [RONIN 15/10]. Righe dalla più recente; fonti in ordine:
    1. il Google Sheet pubblico di Stockbee (stockbee.py: la fonte da cui legge anche NEL);
    2. il file già pronto nel repo pubblico di NEL;
    3. l'archivio nel repo (data/breadth/market_monitor_nel.json), a cui ogni download riuscito si aggiunge;
    4. se manca la riga del giorno, la replica nostra (daily.themes_and_regime)."""
    import urllib.request
    from . import breadth as B
    from . import stockbee as SB
    try:
        return B.archive_nel(SB.fetch())[:300]
    except Exception as e:
        log.warning("Market Monitor dal foglio Stockbee: %s", e)
    for url in C.MM_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "JeffCoach/2.0"})
            rows = json.loads(urllib.request.urlopen(req, timeout=60).read())
            if isinstance(rows, list) and rows and "date" in rows[0]:
                return B.archive_nel(rows)[:300]
        except Exception as e:
            log.warning("Market Monitor %s: %s", url, e)
    arch = B.nel_archive()
    if arch:
        log.warning("Market Monitor: NEL non raggiungibile, uso l'archivio (ultima riga %s)", arch[0]["date"])
        return arch[:300]
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


def mm_state_pradeep(rows: list[dict], i: int, up20: Optional[dict] = None) -> Optional[tuple[str, list[str], dict]]:
    """Lettura del Market Monitor come la usa Pradeep Bonde [RONIN 16/10] (righe dalla più recente, `i` = seduta).
    Quello che guarda lui: acquisti contro vendite (giorni a ±4%), l'indicatore primario (titoli +25% contro -25% nel
    trimestre), il T2108 (sotto 20 rialzista, sotto 10 molto), lo studio 20% (titoli +20% in 5 sedute >= 200: storno
    entro 5-10 sedute, ignorato uscendo da un ipervenduto; -20% >= 200: vendita estrema, niente "Breakouts fail") e
    il "think 30 days ahead".
    None se mancano le sedute necessarie."""
    need = max(C.PB_T30A, C.PB_UP20_WINDOW, C.PB_FLOW_DAYS + 5) + 1
    win = rows[i:i + need]
    if len(win) < C.PB_FLOW_DAYS + 6 or any(r.get(k) is None for r in win[:C.PB_FLOW_DAYS + 6]
                                            for k in ("up4", "down4", "t2108")):
        return None
    r = win[0]
    def u20(x, key="up20w"):          # studio 20% dalla replica nostra (Stockbee non lo pubblica)
        v = (up20 or {}).get(x["date"])
        v = v.get(key) if isinstance(v, dict) else (v if key == "up20w" else None)
        return v if v is not None else x.get(key)
    t = r["t2108"]
    t5 = win[5]["t2108"]
    flow = sum((x["up4"] > x["down4"]) - (x["down4"] > x["up4"]) for x in win[:C.PB_FLOW_DAYS])
    buying, selling = flow >= C.PB_FLOW_MIN, flow <= -C.PB_FLOW_MIN
    oversold = t < C.PB_T2108_OVERSOLD
    last_os = next((k for k, x in enumerate(win[:C.PB_T30A + 1]) if x.get("t2108") is not None
                    and x["t2108"] < C.PB_T2108_OVERSOLD), None)
    t30a = last_os is not None
    hi = [u20(x) for x in win[:C.PB_UP20_WINDOW] if u20(x) is not None]
    caution = bool(hi) and max(hi) >= C.PB_UP20_CAUTION and not t30a
    lo = [u20(x, "down20w") for x in win[:C.PB_UP20_WINDOW] if u20(x, "down20w") is not None]
    caution_dn = bool(lo) and max(lo) >= C.PB_DOWN20_CAUTION      # vendita estrema: niente "Breakouts fail"
    extended = t > C.PB_T2108_EXTENDED
    q_up, q_dn = r.get("up25q"), r.get("down25q")
    primary = None if q_up is None or q_dn is None else q_up > q_dn
    why = [f"buying vs selling 5d {flow:+d}", f"25%Q {'green' if primary else 'red'}" if primary is not None else "25%Q n/a",
           f"T2108 {t:.0f}% ({t - t5:+.0f} 5d)"]
    if u20(r) is not None:
        why.append(f"20% study {u20(r):.0f} up / {u20(r, 'down20w') or 0:.0f} down")
    if oversold:
        st = "Expansion"
        why.append("T2108 < 10: extremely bullish" if t < C.PB_T2108_EXTREME else "T2108 < 20: start getting bullish")
    elif t30a and not selling:
        st = "Expansion"
        why.append(f"T30A: T2108 < 20 {last_os} sessions ago")
    elif primary and not selling and not caution and not extended and (buying or t > t5):
        st = "Expansion"
    elif primary is False and selling and t < t5 and not caution_dn:
        st = "Defensive"
        why.append("down-surges dominate, T2108 falling")
    else:
        st = "Mixed"
        if caution:
            why.append(f"20% study up >= {C.PB_UP20_CAUTION} in {C.PB_UP20_WINDOW}d: dip likely")
        if caution_dn:
            why.append(f"20% study down >= {C.PB_DOWN20_CAUTION} in {C.PB_UP20_WINDOW}d: bounce likely")
        if extended:
            why.append("T2108 extended")
    flags = dict(flow5=flow, primary=primary, oversold=oversold, t30a=t30a, caution=caution, caution_down=caution_dn,
                 extended=extended, up20w=u20(r), down20w=u20(r, "down20w"))
    return st, why, flags


def market_monitor(rows: list[dict], as_of, up20: Optional[dict] = None) -> Optional[dict]:
    """Riga del Market Monitor della seduta `as_of` (righe dalla più recente) + variazione T2108 a 5 sedute."""
    day = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)
    i = next((k for k, r in enumerate(rows or []) if r.get("date") == day), None)
    if i is None:
        return None
    r = rows[i]
    why, flags = [], {}
    pb = mm_state_pradeep(rows, i, up20) if C.MM_READ == "pradeep" else None
    if pb:
        st, why, flags = pb
    else:
        st = mm_state(r)
    if st is None:
        return None
    old = rows[i + 5] if i + 5 < len(rows) else None
    d5 = (r["t2108"] - old["t2108"]) if (old and r.get("t2108") is not None and old.get("t2108") is not None) else None
    return dict(date=day, state=st, up4=r["up4"], down4=r["down4"], ratio5=r.get("ratio5"), ratio10=r.get("ratio10"),
                t2108=r.get("t2108"), t2108_d5=None if d5 is None else round(d5, 2), up25q=r.get("up25q"),
                down25q=r.get("down25q"), read="pradeep" if pb else "nel", label=C.MM_LABEL.get(st, st),
                mm_why=why, **{k: v for k, v in flags.items() if k in ("flow5", "up20w", "down20w", "t30a", "caution")})


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
        if mm.get("mm_why"):
            why.append("Market Monitor: " + ", ".join(mm["mm_why"]))   # lettura di Pradeep [RONIN 16/10]
    score_bias = "LONG" if score >= C.BIAS_LONG_MIN else ("SHORT" if score <= C.BIAS_SHORT_MAX else "MIXED")
    if mm is not None:
        bias = C.MM_BIAS[mm["state"]]
        why.insert(0, f"Market Monitor {mm['state']} → {DISPLAY.get(bias, bias)}; index score {score:+d} ({score_bias})")
    else:
        bias = score_bias
        why.insert(0, f"Market Monitor unavailable: index score {score:+d} → {bias}")
    return {"bias": bias, "score": score, "score_bias": score_bias, "why": why, "market_monitor": mm, "indices": indices}


def regime_pool(pb: Optional[dict], indices: dict[str, dict], mm: Optional[dict]) -> dict:
    """Bias dalle liste del pool monitorato [ANDREA 20/10, dal bot di Martin (martincoach/engine.regime_pool)].

    Punteggio: livello (quota Leading su Leading+Lagging del pool), flusso a 5 sedute (chi scende di una lista vale -1,
    di due -2, chi sale +) e tendenza dei flussi giornalieri. >= BIAS_LONG_MIN LONG, <= BIAS_SHORT_MAX SHORT
    (DEFENSIVE), in mezzo MIXED. Gli indici e il Market Monitor restano come contesto nella card."""
    pb = pb or {}
    if not pb.get("lists"):
        return regime(indices, mm)                 # senza il pool si torna al Market Monitor
    score, why = 0, []
    sh = pb["share"]
    score += 1 if sh >= C.POOL_SHARE_GOOD else (-1 if sh <= C.POOL_SHARE_BAD else 0)
    why.append(f"pool ({pb['n']}): Leading {sh:.0f}% of Leading+Lagging · Leading {pb['lists']['Leading']} / "
               f"Mediocre {pb['lists']['Mediocre']} / Lagging {pb['lists']['Lagging']}")
    f5 = pb.get("flow5")
    if f5 is not None:
        score += (2 if f5 >= C.POOL_FLOW_STRONG else 1 if f5 >= C.POOL_FLOW_MIN else
                  -2 if f5 <= -C.POOL_FLOW_STRONG else -1 if f5 <= -C.POOL_FLOW_MIN else 0)
        why.append(f"pool flow 5d {f5:+.1f}% ({pb.get('up_5d', 0)} up, {pb.get('down_5d', 0)} down)")
    fd = pb.get("flow_daily") or []
    if len(fd) >= C.POOL_TREND_DAYS:
        ch = fd[-C.POOL_TREND_DAYS:]
        up = sum(x >= C.POOL_FLOW_DAY_MIN for x in ch)
        dn = sum(x <= -C.POOL_FLOW_DAY_MIN for x in ch)
        tr = 1 if up >= C.POOL_TREND_MIN else (-1 if dn >= C.POOL_TREND_MIN else 0)
        score += tr
        why.append(f"pool flow trend {'up' if tr > 0 else 'down' if tr < 0 else 'mixed'} ("
                   + " ".join(f"{x:+.1f}%" for x in ch) + ")")
    bias = "LONG" if score >= C.BIAS_LONG_MIN else ("SHORT" if score <= C.BIAS_SHORT_MAX else "MIXED")
    why.insert(0, f"pool lists: score {score:+d} → {DISPLAY.get(bias, bias)}")
    if mm is not None:
        why.append(f"Market Monitor {mm['state']} (context)")
    return {"bias": bias, "score": score, "score_bias": bias, "why": why, "market_monitor": mm,
            "indices": indices, "pool": {k: pb.get(k) for k in ("n", "lists", "share", "flow5", "flow_daily")}}


def flow_reversal(hist: list[dict], days: int = None) -> Optional[dict]:
    """Inversione del trend ±4% [RONIN 16/10, Andrea]: una seduta con +4% > -4% dopo una fase di vendite (flusso
    delle PB_FLOW_DAYS sedute prima <= -PB_FLOW_MIN, flusso = giorni ▲ meno giorni ▼), o il contrario. Vale nelle
    prime `days` sedute (REVERSAL_DAYS = 2: il giorno dell'inversione e il successivo); vince la più recente.
    `hist`: righe con date, up4, down4, dalla più vecchia."""
    days = days or C.REVERSAL_DAYS
    h = [r for r in hist if r.get("up4") is not None and r.get("down4") is not None]
    sign = [(r["up4"] > r["down4"]) - (r["down4"] > r["up4"]) for r in h]
    n = C.PB_FLOW_DAYS
    for k in range(len(h) - 1, max(n - 1, len(h) - 1 - days), -1):      # ultime `days` sedute, dalla più recente
        before = sum(sign[k - n:k])
        if sign[k] > 0 and before <= -C.PB_FLOW_MIN:
            d = "buying"
        elif sign[k] < 0 and before >= C.PB_FLOW_MIN:
            d = "selling"
        else:
            continue
        return dict(direction=d, date=h[k]["date"], day=len(h) - k, flow_before=before,
                    up4=h[k]["up4"], down4=h[k]["down4"])
    return None
