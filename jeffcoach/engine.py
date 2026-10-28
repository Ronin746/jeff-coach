"""Motore: metriche per titolo, liste Leading/Mediocre/Lagging, livelli di confluenza, candidati long/short, regime.

Tutte le soglie vengono da config.py. Le funzioni sono pure (dati in ingresso → dizionari), così si
possono provare senza rete (tests/).
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from . import config as C
from . import edges as EDG
from . import indicators as I
from . import orizzontali as HZ
from . import trendlines as TL


def _r(x, n=2):
    if x is None:
        return None
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return None
        return round(float(x), n)
    except Exception:
        return None


# ------------------------------------------------------------------ metriche
def stretched(m: dict, side: str) -> bool:
    """Titolo troppo esteso nella direzione del trade [RONIN 16/10, Andrea: "veramente tanto estesi, es. LITE"; "è
    l'estensione dalla 9 e basta"]: oltre STRETCH_EMA9_ADR ADR dalla EMA9."""
    adr = m.get("adr") or 0
    if not adr or m.get("ext9") is None:
        return False
    k = 1 if side == "long" else -1
    return k * m["ext9"] / adr >= C.STRETCH_EMA9_ADR


def trend_r2(c: pd.Series, windows=(42, 63, 126)) -> Optional[float]:
    """Linearità del trend [RONIN 16/10]: R² della retta sul log del prezzo, il migliore tra le finestre (così un
    titolo che ha appena girato non viene punito per la svolta)."""
    best = None
    for n in windows:
        y = np.log(c.iloc[-n:].astype(float).values)
        if len(y) < n or not np.isfinite(y).all() or y.std() == 0:
            continue
        r = float(np.corrcoef(np.arange(n), y)[0, 1])
        best = max(best or 0.0, r * r)
    return best
def compute_metrics(df: pd.DataFrame, qqq: Optional[pd.DataFrame] = None, extra_edges: bool = False) -> Optional[dict]:
    """Metriche daily di un titolo sulla sua ultima barra completata.
    [JEFF] `extra_edges`: edge anche per i titoli dell'universo di Jeff che non passano la soglia di Martin."""
    if df is None or len(df) < C.EMA_LONG + 10:
        return None
    c = df.Close
    e9, e21, e50, e150 = (I.ema(c, n) for n in (C.EMA_FAST, C.EMA_MID, C.EMA_SLOW, C.EMA_LONG))
    close = float(c.iloc[-1])
    adr = I.adr_pct(df, C.ADR_LEN)
    w = I.weekly(df)
    ew9, ew21 = I.ema(w.Close, 9), I.ema(w.Close, 21)
    last = df.iloc[-1]
    rng = float(last.High - last.Low)
    ret1 = I.pct(close, float(c.iloc[-2]))
    m = dict(
        close=close, e9=float(e9.iloc[-1]), e21=float(e21.iloc[-1]), e50=float(e50.iloc[-1]), e150=float(e150.iloc[-1]),
        e9_prev=float(e9.iloc[-2]), e21_slope=float(e21.iloc[-1] - e21.iloc[-1 - C.LONG_EMA21_SLOPE_BARS]),
        e50_slope=float(e50.iloc[-1] - e50.iloc[-6]),
        adr=adr, vol10=float(df.Volume.iloc[-10:].mean()), dv5=I.dollar_volume(df, C.DV_DAYS), dv20=I.dollar_volume(df, 20), dv60=I.dollar_volume(df, 60),
        ret1=ret1, ret5=I.pct(close, float(c.iloc[-6])), ret21=I.pct(close, float(c.iloc[-22])),
        ret63=I.pct(close, float(c.iloc[-64])) if len(c) > 64 else None,
        ext9=I.pct(close, float(e9.iloc[-1])), ext50=I.pct(close, float(e50.iloc[-1])),
        close_pos=(float(last.Close - last.Low) / rng) if rng > 0 else 0.5,
        ret1_adr=(ret1 / adr) if (ret1 is not None and adr) else None,
        w_close=float(w.Close.iloc[-1]), ew9=float(ew9.iloc[-1]), ew21=float(ew21.iloc[-1]),
        ew9_slope=float(ew9.iloc[-1] - ew9.iloc[-2]), ew21_slope=float(ew21.iloc[-1] - ew21.iloc[-2]),
        hi=float(last.High), lo=float(last.Low),
        up_52w_low=I.pct(close, float(df.Low.iloc[-252:].min())),
        hi_bo=float(df.High.iloc[-C.BREAKOUT_LOOKBACK:].max()),
    )
    # distanza dalla SMA50 in ATR(14) [RONIN 16/10, Andrea: niente titoli estesi più di 6 ATR dalla 50 SMA]
    pc = c.shift(1)
    tr = pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    sma50 = float(c.rolling(50).mean().iloc[-1])
    m.update(sma50=sma50, atr=atr, ext50_atr=(close - sma50) / atr if atr else None)
    m["trend_r2"] = trend_r2(c)
    # sedute consecutive in rialzo/ribasso, movimento della serie in ADR e ampiezza degli ultimi 15 giorni in ADR
    # (base) [RONIN 20/10, Andrea: "eviterei titoli su 4/5 giorni di fila con una variazione considerevole, se sono
    # ancora in una base non importa"]
    d = c.diff().iloc[::-1]
    up = int((d > 0).cumprod().sum())
    dn = int((d < 0).cumprod().sum())
    n = max(up, dn)
    m["streak_up"], m["streak_dn"] = up, dn
    m["streak_move_adr"] = (abs(I.pct(close, float(c.iloc[-1 - n])) or 0) / adr) if (n and adr) else 0.0
    m["range15_adr"] = ((float(df.High.iloc[-15:].max()) / float(df.Low.iloc[-15:].min()) - 1) * 100 / adr) if adr else None
    m["list"] = I.classify(close, m["e50"], m["e150"])
    if qqq is not None and len(qqq) > 64:
        qc = qqq.Close.reindex(df.index).ffill()
        m["rs21"] = _r((m["ret21"] or 0) - (I.pct(float(qc.iloc[-1]), float(qc.iloc[-22])) or 0))
        m["rs63"] = _r((m["ret63"] or 0) - (I.pct(float(qc.iloc[-1]), float(qc.iloc[-64])) or 0)) if m["ret63"] is not None else None
        m["rs5"] = _r((m["ret5"] or 0) - (I.pct(float(qc.iloc[-1]), float(qc.iloc[-6])) or 0))
    m["supports"] = support_levels(df, m, e9, e21, e50, ew9, ew21)
    m["resistances"] = resistance_levels(df, m, e9, e21, e50, ew9, ew21)
    # multi-edge [RONIN 22/10]: trendline e canali, livelli in più (EMA150, weekly, trendline), segni di momentum e di
    # price action; solo per i titoli che possono essere candidati (50M$ al giorno, prezzo minimo), per non rallentare
    if C.META_EDGES and ((m["dv5"] >= min(C.LONG_DV_MIN, C.SHORT_DV_MIN) and close >= C.PRICE_MIN)
                         or extra_edges):                  # [JEFF] universo di Jeff
        try:
            tl = TL.find_lines(df, adr)
            m["tl"] = tl
            m["levels_x"] = extra_levels(df, m, e150, w, tl)
            m["hz"] = HZ.find_levels(df, adr)                     # orizzontali, linee e aree [RONIN 23/10]
            hx = HZ.as_levels(m["hz"], close)
            m["levels_x"]["long"] += hx["long"]
            m["levels_x"]["short"] += hx["short"]
            k = C.SR_TEST_DAYS + 1
            m["recent"] = {"lows": [float(x) for x in df.Low.iloc[-k:]], "highs": [float(x) for x in df.High.iloc[-k:]],
                           "closes": [float(x) for x in df.Close.iloc[-k:]]}
            m["edge_feat"] = EDG.daily_features(df, e9, e21, e50, adr, tl)
            if C.SR_EXTRA_IN_CONFLUENCE:
                m["supports"] = m["supports"] + m["levels_x"]["long"]
                m["resistances"] = m["resistances"] + m["levels_x"]["short"]
        except Exception:                       # gli edge non devono mai far cadere la lista
            m.pop("edge_feat", None)
    return m


def extra_levels(df, m, e150, w, tl) -> dict:
    """Livelli in più per il multi-edge [RONIN 22/10, Andrea: S&R "anche MTF, con maggiore importanza ai timeframe daily e
    weekly"]: EMA150 daily e EMA50 weekly nel verso giusto, swing weekly (massimi e minimi di 5 settimane nell'ultimo anno),
    trendline del giorno (rialzista sotto per i long, ribassista sopra per gli short). {'long': supporti, 'short': resistenze}."""
    close = m["close"]
    sup: list[dict] = []
    res: list[dict] = []
    if e150.iloc[-1] > e150.iloc[-4] and e150.iloc[-1] < close:
        sup.append({"name": "EMA150", "price": float(e150.iloc[-1])})
    if e150.iloc[-1] < e150.iloc[-4] and e150.iloc[-1] > close:
        res.append({"name": "EMA150", "price": float(e150.iloc[-1])})
    if len(w) >= 60:
        ew50 = I.ema(w.Close, 50)
        if ew50.iloc[-1] > ew50.iloc[-2] and ew50.iloc[-1] < close:
            sup.append({"name": "EMA50w", "price": float(ew50.iloc[-1])})
        if ew50.iloc[-1] < ew50.iloc[-2] and ew50.iloc[-1] > close:
            res.append({"name": "EMA50w", "price": float(ew50.iloc[-1])})
    k, lb = C.SR_WEEKLY_PIVOT_K, C.SR_WEEKLY_LOOKBACK
    for kind, pos in (("high", I.swing_highs(w, k, lb)), ("low", I.swing_lows(w, k, lb))):
        for p in pos:
            v = float(w.High.iloc[p] if kind == "high" else w.Low.iloc[p])
            lv = {"name": f"weekly {kind} {w.index[p].date()}", "price": v}
            if v < close:
                sup.append(lv)
            elif v > close:
                res.append(lv)
    up, dn = (tl or {}).get("up"), (tl or {}).get("down")
    if up and up["value"] < close:
        sup.append({"name": "TL up", "price": float(up["value"])})
    if dn and dn["value"] > close:
        res.append({"name": "TL down", "price": float(dn["value"])})
    return {"long": sup, "short": res}


# ------------------------------------------------------------------ livelli
def support_levels(df, m, e9, e21, e50, ew9, ew21) -> list[dict]:
    """Supporti sotto il close: EMA in salita (daily e weekly), AVWAP da swing low e dal giorno di volume
    massimo, vecchi swing high (retest del breakout), gap non chiusi."""
    close = m["close"]
    out: list[dict] = []

    def add(name, v):
        if v is not None and 0 < v < close:
            out.append({"name": name, "price": float(v)})

    for nm, s in (("EMA9", e9), ("EMA21", e21), ("EMA50", e50)):
        if s.iloc[-1] > s.iloc[-4]:
            add(nm, s.iloc[-1])
    for nm, s in (("EMA9w", ew9), ("EMA21w", ew21)):
        if len(s) > 2 and s.iloc[-1] > s.iloc[-2]:
            add(nm, s.iloc[-1])
    lows = I.swing_lows(df, C.SWING_K, C.SWING_LOOKBACK)
    for p in lows[-2:]:
        add(f"AVWAP swing low {df.index[p].date()}", I.avwap(df, p))
    vol_pos = int(np.argmax(df.Volume.to_numpy()[-60:])) + len(df) - 60
    add(f"AVWAP volume day {df.index[vol_pos].date()}", I.avwap(df, vol_pos))
    for p in I.swing_highs(df, C.SWING_K, C.SWING_LOOKBACK)[-4:]:
        add(f"swing high {df.index[p].date()}", df.High.iloc[p])
    for kind, near, _far in I.unfilled_gaps(df):
        if kind == "up":
            add("gap", near)
    return out


def resistance_levels(df, m, e9, e21, e50, ew9, ew21) -> list[dict]:
    """Resistenze sopra il close: EMA in discesa (daily e weekly), AVWAP da swing high, vecchi swing low,
    gap non chiusi."""
    close = m["close"]
    out: list[dict] = []

    def add(name, v):
        if v is not None and v > close:
            out.append({"name": name, "price": float(v)})

    for nm, s in (("EMA9", e9), ("EMA21", e21), ("EMA50", e50)):
        if s.iloc[-1] < s.iloc[-4]:
            add(nm, s.iloc[-1])
    for nm, s in (("EMA9w", ew9), ("EMA21w", ew21)):
        if len(s) > 2 and s.iloc[-1] < s.iloc[-2]:
            add(nm, s.iloc[-1])
    for p in I.swing_highs(df, C.SWING_K, C.SWING_LOOKBACK)[-2:]:
        add(f"AVWAP swing high {df.index[p].date()}", I.avwap(df, p))
    for p in I.swing_lows(df, C.SWING_K, C.SWING_LOOKBACK)[-4:]:
        add(f"swing low {df.index[p].date()}", df.Low.iloc[p])
    for kind, near, _far in I.unfilled_gaps(df):
        if kind == "down":
            add("gap", near)
    return out


def best_cluster(levels: list[dict], close: float, need=None) -> Optional[dict]:
    """Confluenza: il gruppo di livelli entro LEVEL_CLUSTER_PCT con più membri (a parità, il più vicino).
    `need(nome)`: se dato, valgono solo i gruppi con almeno un livello che lo soddisfa."""
    if not levels:
        return None
    best = None
    for lv in levels:
        mem = [x for x in levels if abs(x["price"] / lv["price"] - 1) * 100 <= C.LEVEL_CLUSTER_PCT]
        if need is not None and not any(need(x["name"]) for x in mem):
            continue
        price = sum(x["price"] for x in mem) / len(mem)
        dist = abs(close / price - 1) * 100
        key = (len({x["name"] for x in mem}), -dist)
        if best is None or key > best["_key"]:
            best = {"price": price, "members": sorted({x["name"] for x in mem}), "count": key[0], "dist_pct": dist, "_key": key}
    if best is None:
        return None
    best.pop("_key")
    return best


def trend_tf_ok(m: dict, side: str) -> bool:
    """Consonanza col timeframe di fondo: dal 17/10i la EMA50 daily e la sua inclinazione al posto della 9 weekly
    [RONIN 17/10, Andrea: "praticamente uguale, ma reagisce senza aspettare la chiusura del timeframe più lungo"].
    Short sotto la EMA50 daily, long sopra; ammesso appena dall'altra parte (entro EMA50D_TOL_ADR ADR) se la 50 va
    già nella direzione del trade (inclinazione su 5 sedute)."""
    if C.TREND_TF != "ema50d":
        return weekly_ema9_ok(m, side)
    tol = C.EMA50D_TOL_ADR * (m.get("adr") or 0) / 100 * m["e50"]
    sl = m.get("e50_slope") or 0
    if side == "short":
        return m["close"] < m["e50"] or (sl < 0 and m["close"] <= m["e50"] + tol)
    return m["close"] > m["e50"] or (sl > 0 and m["close"] >= m["e50"] - tol)


def weekly_ema9_ok(m: dict, side: str) -> bool:
    """Consonanza weekly [RONIN 17/10]: short sotto la EMA9 weekly, long sopra; ammesso anche appena dall'altra parte
    (entro WEEKLY_EMA9_TOL_ADR ADR) se la 9 weekly va già nella direzione del trade."""
    tol = C.WEEKLY_EMA9_TOL_ADR * (m.get("adr") or 0) / 100 * m["ew9"]
    if side == "short":
        return m["w_close"] < m["ew9"] or ((m.get("ew9_slope") or 0) < 0 and m["w_close"] <= m["ew9"] + tol)
    return m["w_close"] > m["ew9"] or ((m.get("ew9_slope") or 0) > 0 and m["w_close"] >= m["ew9"] - tol)


def zone_levels(levels: list[dict], cl: Optional[dict], adr: float) -> int:
    """Livelli diversi nella zona del livello (entro ZONE_ADR_FRAC ADR dal prezzo della confluenza), compresi quelli
    della confluenza: più livelli = supporto/resistenza più solida [RONIN 16/10, Andrea]."""
    if not cl or not adr:
        return 0
    return len({x["name"] for x in levels if abs(x["price"] / cl["price"] - 1) * 100 <= C.ZONE_ADR_FRAC * adr})


def strong_short_level(name: str) -> bool:
    """Livello short forte [ML]: EMA21 o EMA50 daily declinante, AVWAP da swing high, gap (non la sola EMA9)."""
    return any(name == x or name.startswith(x + " ") for x in C.SHORT_STRONG_LEVELS)


def streak_run(m: dict, side: str) -> bool:
    """Corsa di più sedute nel verso del trade [RONIN 20/10, Andrea]: STREAK_DAYS+ chiusure di fila in rialzo (long) o
    in ribasso (short) con un movimento di almeno STREAK_MIN_ADR ADR; non conta se il titolo è ancora in una base
    (ampiezza degli ultimi 15 giorni entro BASE_MAX_ADR ADR)."""
    if not C.STREAK_FILTER:
        return False
    n = m.get("streak_up" if side == "long" else "streak_dn") or 0
    if n < C.STREAK_DAYS or (m.get("streak_move_adr") or 0) < C.STREAK_MIN_ADR:
        return False
    return not (m.get("range15_adr") is not None and m["range15_adr"] <= C.BASE_MAX_ADR)


# ------------------------------------------------------------------ candidati
def long_candidate(t: str, m: dict) -> tuple[bool, dict]:
    """Pullback buy [ML]: Leading, trend 9>21 con 21 in salita, non esteso, confluenza di supporti entro 1 ADR."""
    why = {}
    why["list"] = m["list"] == "Leading"
    why["liquid"] = (m["dv5"] >= C.LONG_DV_MIN and m["close"] >= C.PRICE_MIN          # [RONIN 16/10: 50M$]
                     and (m.get("vol10") or 0) >= C.VOL10_MIN)                        # [RONIN 20/10c: 500k azioni a 10g]
    why["adr"] = m["adr"] >= (C.ADR_MIN_LARGE if m["dv5"] >= C.ADR_LARGE_DV else C.ADR_MIN)   # [RONIN 16/10]
    why["trend"] = (m["e9"] > m["e21"] and m["e21_slope"] > 0) if C.LONG_REQUIRE_EMA9_GT_21 else True
    why["not_extended"] = (m["ext9"] or 0) <= C.LONG_EXT_EMA9_MAX_PCT
    why["not_extended_sma50"] = (m.get("ext50_atr") or 0) <= C.LONG_MAX_EXT_SMA50_ATR  # [RONIN 16/10; 5 ATR dal 20/10a]
    why["no_streak"] = not streak_run(m, "long")                                          # [RONIN 20/10a]
    why["linear_trend"] = m.get("trend_r2") is None or m["trend_r2"] >= C.MIN_TREND_R2   # [RONIN 16/10]
    why["not_stretched"] = not stretched(m, "long")                                      # [RONIN 16/10]
    why["trend_tf"] = trend_tf_ok(m, "long") if C.WEEKLY_EMA9_REQUIRED else True     # [RONIN 17/10; 50 daily dalla 17i]
    # specchio delle regole degli short [RONIN 19/10b, Andrea: "la consonanza dei timeframe dello short vale anche per il
    # long"]: chiusura sopra la EMA9 daily (short: sotto) e weekly sano, close weekly sopra la 21 e 9 sopra 21 (short: non sano)
    why["above_ema9"] = (m["close"] > m["e9"]) if C.LONG_ABOVE_EMA9 else True
    why["weekly_healthy"] = (m["w_close"] > m["ew21"] and m["ew9"] > m["ew21"]) if C.LONG_WEEKLY_HEALTHY else True
    cl = best_cluster(m["supports"], m["close"])
    why["confluence"] = bool(cl and cl["count"] >= C.CONFLUENCE_MIN and cl["dist_pct"] <= C.LEVEL_MAX_DIST_ADR * m["adr"])
    if C.JEFF:          # [JEFF 28/10] dove Martin e Jeff misurano la stessa cosa vale Jeff (universo e gate in jeff.py)
        for k in C.JEFF_REPLACES_LONG_CHECKS:
            why.pop(k, None)
    info = {"level": cl, "checks": why, "zone_levels": zone_levels(m["supports"], cl, m["adr"])}
    return all(why.values()), info


def short_candidate(t: str, m: dict) -> tuple[bool, dict]:
    """Pullback short [ML]: Lagging (o EMA impilate in discesa), sotto la 9 daily, weekly non sano,
    niente candela forte ieri, confluenza di resistenze declinanti entro 1 ADR sopra, con almeno un livello forte
    (EMA21/EMA50 declinante, AVWAP da swing high, gap). Il filtro del tema forte sta in daily.build."""
    why = {}
    stacked_down = m["e9"] < m["e21"] < m["e50"] and m["e50_slope"] < 0
    spread = (max(m["e9"], m["e21"], m["e50"]) - min(m["e9"], m["e21"], m["e50"])) / m["close"] * 100
    tight = spread <= C.SHORT_EMA_TIGHT_ADR * (m["adr"] or 0)
    # trend che gira [ML, thread "Shorting": "9 e 21 in discesa, 9 sotto 21 → in watchlist"; EMA che si stringono]
    early = (C.SHORT_EARLY_DOWNTREND and m["e9"] < m["e21"] and m["e9"] < m["e9_prev"] and m["e21_slope"] < 0 and tight)
    lagging = m["list"] == "Lagging" or stacked_down
    # primo crack di un ex-leader [ML]: grande corsa, prima chiusura sotto la 9 che gira giù, debolezza relativa a 5 giorni
    exl = (C.SHORT_EXLEADER and not lagging and not early and (m.get("up_52w_low") or 0) >= C.EXLEADER_MIN_UP_52W_LOW
           and m["close"] < m["e9"] and m["e9"] < m["e9_prev"]
           and m["close"] < m["e21"]                                      # rottura: chiusura sotto la 21 daily [RONIN 16/10, Andrea]
           and ((m.get("rs5") or 0) < 0 or (m.get("rs21") or 0) <= 0))   # più debole del QQQ a 5 sedute o a 1 mese
    why["list"] = lagging or early or exl
    why["liquid"] = (m["dv5"] >= C.SHORT_DV_MIN and m["close"] >= C.PRICE_MIN         # [RONIN 14/10: 75M$; 16/10: 50M$]
                     and (m.get("vol10") or 0) >= C.VOL10_MIN)                        # [RONIN 20/10c: 500k azioni a 10g]
    why["adr"] = m["adr"] >= (C.ADR_MIN_LARGE if m["dv5"] >= C.ADR_LARGE_DV else C.ADR_MIN)   # [RONIN 16/10]
    why["below_ema9"] = (m["close"] < m["e9"]) if C.SHORT_NO_ABOVE_EMA9 else True
    why["not_extended_sma50"] = (m.get("ext50_atr") or 0) >= -C.MAX_EXT_SMA50_ATR      # [RONIN 16/10]
    why["no_streak"] = not streak_run(m, "short")                                         # [RONIN 20/10a]
    why["linear_trend"] = m.get("trend_r2") is None or m["trend_r2"] >= C.MIN_TREND_R2   # [RONIN 16/10]
    why["not_stretched"] = not stretched(m, "short")                                     # [RONIN 16/10]
    why["trend_tf"] = (trend_tf_ok(m, "short") or (exl and not lagging and C.EXLEADER_SKIPS_TREND_TF)) \
        if C.WEEKLY_EMA9_REQUIRED else True    # [RONIN 17/10; 50 daily dalla 17i; ex-leader esenti dalla 17p: al primo
    #                                            crack stanno per forza ancora sopra la 50 (SNDK 7-8/10)]
    healthy_w = m["w_close"] > m["ew21"] and m["ew9"] > m["ew21"]
    why["weekly_not_healthy"] = (not healthy_w or ((early or exl) and not lagging and C.SHORT_EARLY_IGNORES_WEEKLY)) \
        if C.SHORT_WEEKLY_HEALTHY_BLOCK else True
    strong = (m["close_pos"] >= C.SHORT_STRONG_CANDLE_CLOSE_POS and (m["ret1_adr"] or 0) >= C.SHORT_STRONG_CANDLE_RET_ADR)
    why["no_strong_candle"] = not strong
    near = lambda c: bool(c and c["count"] >= C.CONFLUENCE_MIN and c["dist_pct"] <= C.LEVEL_MAX_DIST_ADR * m["adr"])
    cl_any = best_cluster(m["resistances"], m["close"])
    why["confluence"] = near(cl_any)
    cl = best_cluster(m["resistances"], m["close"], need=strong_short_level) if C.SHORT_STRONG_LEVELS else cl_any
    if exl and not near(cl):
        # ex-leader: basta la EMA9 declinante o l'AVWAP da swing high entro 1 ADR (il rimbalzo nella 9 è l'ingresso) [ML]
        lv9 = best_cluster(m["resistances"], m["close"], need=lambda n: n == "EMA9" or n.startswith("AVWAP swing high"))
        if lv9 and lv9["dist_pct"] <= C.LEVEL_MAX_DIST_ADR * m["adr"]:
            cl = cl_any = dict(lv9, count=max(lv9["count"], C.CONFLUENCE_MIN))
            why["confluence"] = True
    why["strong_level"] = near(cl)          # [ML: la confluenza contiene EMA21/EMA50 declinante, AVWAP da swing high o gap]
    info = {"level": cl if near(cl) else cl_any, "checks": why, "ema_spread_adr": spread / m["adr"] if m["adr"] else None,
            "short_type": "Lagging" if lagging else ("trend che gira" if early else ("top ex-leader" if exl else None)),
            "weekly_healthy": healthy_w}
    info["zone_levels"] = zone_levels(m["resistances"], info["level"], m["adr"])
    return all(why.values()), info


def open_checks(info: dict) -> list[str]:
    return [k for k, v in info["checks"].items() if not v]


# ------------------------------------------------------------------ indici e regime
def index_state(m: Optional[dict]) -> dict:
    if not m:
        return {}
    trend = 1 if (m["close"] > m["e21"] and m["e9"] > m["e21"]) else (-1 if (m["close"] < m["e21"] and m["e9"] < m["e21"]) else 0)
    return dict(close=_r(m["close"]), above9=m["close"] > m["e9"], above21=m["close"] > m["e21"], above50=m["close"] > m["e50"],
                e9_gt_21=m["e9"] > m["e21"], trend=trend, ext9=_r(m["ext9"]), ret21=_r(m["ret21"]))


def mm_state(row: dict) -> Optional[str]:
    """Lettura del Market Monitor come nel briefing di NEL: Expansion, Defensive o Mixed."""
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


def regime(indices: dict[str, dict], breadth_share: Optional[float], breadth_share_prev: Optional[float],
           feedback: dict, mm: Optional[dict] = None) -> dict:
    """Bias del giorno: LONG, SHORT o FERMO, con i motivi [ML: una direzione alla volta].
    La breadth viene dal Market Monitor (NEL/Stockbee) quando c'è la riga del giorno, altrimenti dalla quota Leading."""
    score, why = 0, []
    q, iwm = indices.get("QQQ") or {}, indices.get("IWM") or {}
    if q:
        score += q["trend"]
        why.append(f"QQQ trend {q['trend']:+d}")
        score += 1 if q["above50"] else -1
        why.append("QQQ above EMA50" if q["above50"] else "QQQ below EMA50")
    if iwm:
        score += iwm["trend"]
        why.append(f"IWM trend {iwm['trend']:+d}")
        if C.IWM_LAG_WARNING and q and iwm.get("ret21") is not None and q.get("ret21") is not None and iwm["ret21"] < q["ret21"] - 3:
            why.append("IWM lagging QQQ (caution)")
    if mm is not None:
        score += {"Expansion": 1, "Defensive": -1}.get(mm["state"], 0)
        if mm.get("mm_why"):
            why.append("Market Monitor: " + ", ".join(mm["mm_why"]))   # senza Breakouts work/fail [RONIN 16/10]
        # i numeri del Market Monitor sono nella riga dedicata della card: qui solo stato e variazione
        if mm.get("t2108_d5") is not None:
            if mm["t2108_d5"] >= C.MM_T2108_DELTA:
                score += 1
            elif mm["t2108_d5"] <= -C.MM_T2108_DELTA:
                score -= 1
            why.append(f"T2108 5d {mm['t2108_d5']:+.1f}pp")
    elif breadth_share is not None:
        why.append("Market Monitor unavailable: Leading-list breadth")
        if breadth_share >= C.BREADTH_LEAD_GOOD:
            score += 1
        elif breadth_share <= C.BREADTH_LEAD_BAD:
            score -= 1
        why.append(f"breadth Leading {breadth_share:.0%}")
        if breadth_share_prev is not None:
            d = breadth_share - breadth_share_prev
            if d >= 0.05:
                score += 1
            elif d <= -0.05:
                score -= 1
            why.append(f"breadth 5d {d:+.0%}")
    fl, fs = (None, None) if C.ALERTS_ONLY else (feedback.get("long_r"), feedback.get("short_r"))   # [16/10p]
    if fl is not None:
        if fl >= C.FEEDBACK_GOOD_R:
            score += 1
        elif fl <= C.FEEDBACK_BAD_R:
            score -= 1
        why.append(f"feedback long {fl:+.1f}R")
    if fs is not None:
        if fs >= C.FEEDBACK_GOOD_R:
            score -= 1
        elif fs <= C.FEEDBACK_BAD_R:
            score += 1
        why.append(f"feedback short {fs:+.1f}R")
    score_bias = "LONG" if score >= C.BIAS_LONG_MIN else ("SHORT" if score <= C.BIAS_SHORT_MAX else "FERMO")
    if mm is not None:                    # il Market Monitor decide; il punteggio resta come contesto [RONIN 13/10]
        bias = C.MM_BIAS[mm["state"]]
        if mm["state"] == "Mixed" and C.MM_MIXED_MODE == "fermo":
            bias = "FERMO"
        elif mm["state"] == "Mixed" and C.MM_MIXED_MODE == "score":
            bias = score_bias
        why.insert(0, f"Market Monitor {mm['state']} → {C.BIAS_EN.get(bias, bias)}; index score {score:+d} ({C.BIAS_EN.get(score_bias, score_bias)})")
    else:
        bias = score_bias
    if C.BIAS_SOURCE == "qqq" and q:      # [17/10h, prova] il lato lo decide il QQQ sulle EMA daily
        bias = "LONG" if (q["above9"] and q["above21"]) else ("SHORT" if not (q["above9"] or q["above21"]) else "MISTO")
        why.insert(0, f"bias from QQQ vs daily 9/21 → {C.BIAS_EN.get(bias, bias)}")
    risk = C.RISK_PCT_MIXED if bias == "MISTO" else C.RISK_PCT
    return {"bias": bias, "score": score, "score_bias": score_bias, "risk_pct": risk, "why": why}


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


def weekly_align(m: dict, side: str) -> int:
    """Weekly rispetto al lato: +1 concorde (sopra la 9 weekly in salita per i long, sotto e in discesa per gli short),
    -1 contrario (weekly sano per gli short, sotto la 21 weekly con 9 < 21 per i long), 0 neutro.
    Con TREND_TF "ema50d" (dal 17/10i) lo stesso sulla EMA50 daily: concorde = dalla parte giusta della 50 con la 50
    inclinata nel verso del trade; contrario = dall'altra parte con la 50 inclinata contro."""
    if C.TREND_TF == "ema50d":
        sl = m.get("e50_slope") or 0
        above, below = m["close"] > m["e50"], m["close"] < m["e50"]
        if side == "long":
            return 1 if (above and sl > 0) else (-1 if (below and sl < 0) else 0)
        return 1 if (below and sl < 0) else (-1 if (above and sl > 0) else 0)
    up = m["w_close"] > m["ew9"] and m["ew9_slope"] > 0
    down = m["w_close"] < m["ew9"] and m["ew9_slope"] < 0
    healthy = m["w_close"] > m["ew21"] and m["ew9"] > m["ew21"]
    broken = m["w_close"] < m["ew21"] and m["ew9"] < m["ew21"]
    if side == "long":
        return 1 if up else (-1 if broken else 0)
    return 1 if down else (-1 if healthy else 0)


def hourly_align(h: Optional[pd.DataFrame], side: str) -> Optional[int]:
    """60m rispetto al lato, sulle barre orarie chiuse: +1 concorde (close e EMA9 sotto la EMA21 oraria per gli short,
    sopra per i long), -1 contrario, 0 misto; None senza dati."""
    if h is None or len(h) < 30:
        return None
    c = h["Close"].astype(float)
    e9, e21 = float(I.ema(c, 9).iloc[-1]), float(I.ema(c, 21).iloc[-1])
    last = float(c.iloc[-1])
    bull = last > e21 and e9 > e21
    bear = last < e21 and e9 < e21
    if side == "long":
        return 1 if bull else (-1 if bear else 0)
    return 1 if bear else (-1 if bull else 0)


def martin_breadth(M: dict, liquid: dict, lists: dict, old_lists: Optional[dict], potent_raw: list[str],
                   t_of: dict, hist_lists: Optional[list[dict]] = None) -> dict:
    """Breadth letta come Martin [RONIN 17/10; ML: "solo i titoli degli scan e delle watchlist", EP99]: liste e
    passaggi a 5 sedute, IWM contro QQQ, mega cap sopra la 9, ampiezza dello scan e temi che vi compaiono insieme,
    tenuta dei leader (i 20 più forti a 3 mesi) su 9 e 21, quota dell'universo sopra la 21."""
    cnt = lambda d: {k: sum(v == k for v in d.values()) for k in ("Leading", "Mediocre", "Lagging")}
    now = cnt(lists)
    old = cnt(old_lists) if old_lists else None
    # serie della quota Leading su Leading+Lagging nelle sedute precedenti e oggi: la tendenza delle variazioni
    # [RONIN 17/10k, Andrea: "la variazione nel corso dei giorni dei numeri nelle liste e la tendenza delle variazioni"]
    shr = lambda c: round(c["Leading"] / max(1, c["Leading"] + c["Lagging"]) * 100, 1)
    series = [shr(cnt(h)) for h in (hist_lists or []) if h] + [shr(now)]
    # Mediocre sul totale e da dove arrivano i nuovi Mediocre [RONIN 17/10l, Andrea; ML 13/07: "Mediocre raddoppiata in
    # una settimana, quasi tutti declassati dalla Leading"]: passaggi rispetto a 5 sedute fa
    tot = lambda c: max(1, c["Leading"] + c["Mediocre"] + c["Lagging"])
    med = dict(share=round(now["Mediocre"] / tot(now) * 100, 1),
               share_5d=round(old["Mediocre"] / tot(old) * 100, 1) if old else None,
               growth_pct=round((now["Mediocre"] / max(1, old["Mediocre"]) - 1) * 100, 1) if old else None,
               from_leading=sum(1 for t, v in lists.items() if v == "Mediocre" and old_lists.get(t) == "Leading") if old_lists else None,
               from_lagging=sum(1 for t, v in lists.items() if v == "Mediocre" and old_lists.get(t) == "Lagging") if old_lists else None,
               to_leading=sum(1 for t, v in lists.items() if v == "Leading" and old_lists.get(t) == "Mediocre") if old_lists else None,
               to_lagging=sum(1 for t, v in lists.items() if v == "Lagging" and old_lists.get(t) == "Mediocre") if old_lists else None)
    q, iwm = M.get("QQQ"), M.get("IWM")
    iwm_q = _r((iwm["ret21"] or 0) - (q["ret21"] or 0), 1) if q and iwm else None
    mega = [s for s in C.MEGA_CAPS if s in M]
    lead = sorted((s for s in liquid if liquid[s].get("rs63") is not None), key=lambda s: -liquid[s]["rs63"])[:C.BREADTH_LEADERS_N]
    themes: dict[str, int] = {}
    for s in potent_raw:
        th = t_of.get(s)
        if th:
            themes[th] = themes.get(th, 0) + 1
    # flusso tra le liste [RONIN 17/10m, Andrea]: ogni titolo che scende di una lista (Leading→Mediocre, Mediocre→Lagging)
    # vale -1 per il long e +1 per lo short, due liste (Leading→Lagging) 2 punti; il contrario per chi sale.
    # Netto in % dei titoli presenti nelle due date: a 5 sedute e giorno per giorno (per la tendenza)
    flow5 = list_flow(old_lists, lists) if old_lists else None
    seq = [h for h in (hist_lists or []) if h] + [lists]
    flow_daily = [list_flow(a, b)["pct"] for a, b in zip(seq[:-1], seq[1:])]
    prev = [h for h in (hist_lists or []) if h]
    return dict(lists=now, lists_5d=old, lists_1d=cnt(prev[-1]) if prev else None, lead_share_series=series, mediocre=med, flow5=flow5, flow_daily=flow_daily,
                iwm_vs_qqq_21d=iwm_q, iwm_above21=bool(iwm and iwm["close"] > iwm["e21"]),
                iwm_above9=bool(iwm and iwm["close"] > iwm["e9"]),
                mega_above9=sum(M[s]["close"] > M[s]["e9"] for s in mega), mega_n=len(mega),
                scan_n=len(potent_raw), scan_themes=sorted(((t, n) for t, n in themes.items() if n >= 3), key=lambda x: -x[1])[:4],
                leaders_below9=sum(liquid[s]["close"] < liquid[s]["e9"] for s in lead),
                leaders_below21=sum(liquid[s]["close"] < liquid[s]["e21"] for s in lead), leaders_n=len(lead),
                above21_pct=_r(100 * sum(m["close"] > m["e21"] for m in liquid.values()) / max(1, len(liquid)), 0),
                **_leading_health(liquid, lists))


_RANK = {"Leading": 2, "Mediocre": 1, "Lagging": 0}


def list_flow(a: dict, b: dict) -> dict:
    """Passaggi tra le liste dalla data `a` alla data `b` (dizionari titolo → lista): punti netti (+1 per lista salita,
    -1 per lista scesa), in % dei titoli presenti in entrambe, e quanti salgono e scendono."""
    com = [t for t in b if t in a and a[t] in _RANK and b[t] in _RANK]
    d = [_RANK[b[t]] - _RANK[a[t]] for t in com]
    net = sum(d)
    return dict(net=net, pct=round(net / max(1, len(com)) * 100, 2), n=len(com),
                up=sum(x > 0 for x in d), down=sum(x < 0 for x in d), two=sum(abs(x) == 2 for x in d))


def _leading_health(liquid: dict, lists: dict) -> dict:
    """Salute della lista Leading [ML 01/09: "più titoli sotto la 9 che sopra"]: quota dei titoli Leading liquidi sopra
    la EMA9 e la EMA21 daily."""
    L = [m for s, m in liquid.items() if lists.get(s) == "Leading"]
    if not L:
        return dict(lead_n=0, lead_above9_pct=None, lead_above21_pct=None)
    return dict(lead_n=len(L), lead_above9_pct=_r(100 * sum(m["close"] > m["e9"] for m in L) / len(L), 0),
                lead_above21_pct=_r(100 * sum(m["close"] > m["e21"] for m in L) / len(L), 0))


def regime_martin(mb: Optional[dict], sfb: Optional[dict]) -> dict:
    """Bias alla Martin [RONIN 17/10j, Andrea: "usa come fa Martin le sue liste e il feedback sui trade"]:
      - feedback dei segnali (peso 2) [ML: "il feedback dei trade è il miglior indicatore"; "se 8 dei tuoi ultimi 10
        ingressi falliscono..." 31/01]: long che falliscono spingono verso SHORT, short che falliscono verso LONG;
      - liste: quota Leading su Leading+Lagging e sua variazione a 5 sedute [ML 12/02, 13/07];
      - salute della lista Leading: quota sopra la 9 daily [ML 01/09];
      - leader (i 20 più forti a 3 mesi) sotto la 9 [ML 15/07: le àncore];
      - pillars: mega cap sopra la 9 [ML 24/06].
    Somma >= BIAS_LONG_MIN = LONG, <= BIAS_SHORT_MAX = SHORT, altrimenti MISTO."""
    score, why = 0, []
    mb, sfb = mb or {}, sfb or {}

    def fb_side(f: dict) -> int:
        if not f or f.get("n", 0) < C.MB_FB_MIN_N:
            return 0
        n = f["n"]
        if f["fast_stop"] / n >= C.MB_FB_FAIL_SHARE or f["sum_r"] <= C.FEEDBACK_BAD_R:
            return -1
        if f["sum_r"] >= C.FEEDBACK_GOOD_R and f["hit1r"] / n >= C.MB_FB_HIT_SHARE:
            return 1
        return 0
    fl, fs = fb_side(sfb.get("long")), fb_side(sfb.get("short"))
    score += C.MB_FB_WEIGHT * (fl - fs)
    for side, v in (("long", fl), ("short", fs)):
        f = sfb.get(side) or {}
        if f.get("n"):
            why.append(f"{side} feedback {['negative', 'neutral', 'positive'][v + 1]} "
                       f"({f['hit1r']}/{f['n']} hit +1R, {f['fast_stop']} fast stops, {f['sum_r']:+.1f}R)")
    ls = mb.get("lists") or {}
    sh = ls["Leading"] / max(1, ls["Leading"] + ls["Lagging"]) * 100 if ls else None
    if sh is not None:                              # livello: quota Leading su Leading+Lagging
        score += 1 if sh >= C.MB_LEAD_SHARE_GOOD else (-1 if sh <= C.MB_LEAD_SHARE_BAD else 0)
        why.append(f"lists: Leading {sh:.0f}% of Leading+Lagging")
    f5 = mb.get("flow5")
    if f5:                                          # flusso a 5 sedute: ±1, forte ±2 [17/10m]
        p = f5["pct"]
        pt = 2 if p >= C.MB_FLOW_STRONG else (1 if p >= C.MB_FLOW_MIN else
              (-2 if p <= -C.MB_FLOW_STRONG else (-1 if p <= -C.MB_FLOW_MIN else 0)))
        score += pt
        why.append(f"list flow 5d {f5['net']:+d} pts ({p:+.1f}% of {f5['n']}; {f5['up']} up, {f5['down']} down, "
                   f"{f5['two']} two lists)")
    fd = mb.get("flow_daily") or []
    if len(fd) >= C.MB_TREND_DAYS:                  # tendenza: verso dei flussi giornalieri
        ch = fd[-C.MB_TREND_DAYS:]
        up = sum(c >= C.MB_FLOW_DAY_MIN for c in ch)
        dn = sum(c <= -C.MB_FLOW_DAY_MIN for c in ch)
        tr = 1 if up >= C.MB_TREND_MIN else (-1 if dn >= C.MB_TREND_MIN else 0)
        score += tr
        why.append(f"list flow trend {'up' if tr > 0 else 'down' if tr < 0 else 'mixed'} "
                   f"(last {len(ch)} sessions: " + " ".join(f"{c:+.1f}%" for c in ch) + ")")
    a9 = mb.get("lead_above9_pct")
    if a9 is not None:
        score += 1 if a9 >= C.MB_LEAD_ABOVE9_GOOD else (-1 if a9 <= C.MB_LEAD_ABOVE9_BAD else 0)
        why.append(f"Leading list above the 9: {a9:.0f}%")
    if mb.get("leaders_n"):
        b9 = mb["leaders_below9"] / mb["leaders_n"]
        score += -1 if b9 >= C.MB_LEADERS_BELOW9_BAD else (1 if b9 <= C.MB_LEADERS_BELOW9_GOOD else 0)
        why.append(f"leaders below the 9: {mb['leaders_below9']}/{mb['leaders_n']}")
    if mb.get("mega_n"):
        a = mb["mega_above9"] / mb["mega_n"]
        score += 1 if a >= 0.7 else (-1 if a <= 0.3 else 0)
        why.append(f"pillars above the 9: {mb['mega_above9']}/{mb['mega_n']}")
    bias = "LONG" if score >= C.BIAS_LONG_MIN else ("SHORT" if score <= C.BIAS_SHORT_MAX else "MISTO")
    why.insert(0, f"Martin bias (lists + trade feedback): score {score:+d} → {C.BIAS_EN.get(bias, bias)}")
    risk = C.RISK_PCT_MIXED if bias == "MISTO" else C.RISK_PCT
    return {"bias": bias, "score": score, "score_bias": bias, "risk_pct": risk, "why": why}


def regime_pool(pb: Optional[dict], sfb: Optional[dict]) -> dict:
    """Bias dal pool di Martin [RONIN 17/10o, Andrea]: liste e flusso dei ~130 titoli che Martin avrebbe in watchlist
    (jeffcoach/pool.py), più il feedback dei segnali. Studio 2016-2026 (studi/pool_martin.py): primo SHORT a una
    mediana di 5 sedute dal massimo nelle 14 correzioni del QQQ oltre l'8% (giugno 2026: 6 sedute, universo 57), meno
    falsi SHORT dell'universo e del QQQ sulle 9/21, accordo col lato di Martin 72%.
      - feedback dei segnali (peso MB_FB_WEIGHT): long che falliscono verso SHORT, short che falliscono verso LONG;
      - livello: Leading / (Leading+Lagging) del pool;
      - flusso a 5 sedute (-1 per lista scesa, -2 per due, + per chi sale), in % del pool;
      - tendenza: verso dei flussi giornalieri delle ultime 4 sedute."""
    score, why = 0, []
    pb, sfb = pb or {}, sfb or {}

    def fb_side(f: dict) -> int:
        if not f or f.get("n", 0) < C.MB_FB_MIN_N:
            return 0
        n = f["n"]
        if f["fast_stop"] / n >= C.MB_FB_FAIL_SHARE or f["sum_r"] <= C.FEEDBACK_BAD_R:
            return -1
        if f["sum_r"] >= C.FEEDBACK_GOOD_R and f["hit1r"] / n >= C.MB_FB_HIT_SHARE:
            return 1
        return 0
    fl, fs = fb_side(sfb.get("long")), fb_side(sfb.get("short"))
    score += C.POOL_FB_WEIGHT * (fl - fs)
    for side, v in (("long", fl), ("short", fs)):
        f = sfb.get(side) or {}
        if f.get("n") and C.POOL_FB_WEIGHT:      # col peso 0 il feedback non compare [19/10b]
            why.append(f"{side} feedback {['negative', 'neutral', 'positive'][v + 1]} "
                       f"({f['hit1r']}/{f['n']} hit +1R, {f['fast_stop']} fast stops, {f['sum_r']:+.1f}R)")
    if pb.get("lists"):
        # con il pool a +100% dal minimo i Lagging sono quasi zero: il livello è la quota Leading sul totale [19/10]
        # livello: Leading/(Leading+Lagging); col pool a +100% dal minimo (19/10a) i Lagging erano quasi zero e si usava
        # la quota sul totale
        sh = pb["share"] if C.POOL_MIN_UP_LOW is None else pb.get("lead_pct", pb["share"])
        score += 1 if sh >= C.POOL_SHARE_GOOD else (-1 if sh <= C.POOL_SHARE_BAD else 0)
        why.append(f"Martin pool ({pb['n']}): Leading {sh:.0f}% of " + ("Leading+Lagging" if C.POOL_MIN_UP_LOW is None else "all"))
    f5 = pb.get("flow5")
    if f5 is not None:
        pt = 2 if f5 >= C.POOL_FLOW_STRONG else (1 if f5 >= C.POOL_FLOW_MIN else
              (-2 if f5 <= -C.POOL_FLOW_STRONG else (-1 if f5 <= -C.POOL_FLOW_MIN else 0)))
        score += pt
        why.append(f"pool flow 5d {f5:+.1f}% ({pb.get('up_5d', 0)} up, {pb.get('down_5d', 0)} down)")
    fd = pb.get("flow_daily") or []
    if len(fd) >= C.MB_TREND_DAYS:
        ch = fd[-C.MB_TREND_DAYS:]
        up = sum(x >= C.POOL_FLOW_DAY_MIN for x in ch)
        dn = sum(x <= -C.POOL_FLOW_DAY_MIN for x in ch)
        tr = 1 if up >= C.MB_TREND_MIN else (-1 if dn >= C.MB_TREND_MIN else 0)
        score += tr
        why.append(f"pool flow trend {'up' if tr > 0 else 'down' if tr < 0 else 'mixed'} ("
                   + " ".join(f"{x:+.1f}%" for x in ch) + ")")
    score = round(score, 1) if score != int(score) else int(score)
    bias = "LONG" if score >= C.BIAS_LONG_MIN else ("SHORT" if score <= C.BIAS_SHORT_MAX else "MISTO")
    why.insert(0, f"Martin bias (pool lists" + (" + trade feedback" if C.POOL_FB_WEIGHT else "") + f"): score {score:+} → {C.BIAS_EN.get(bias, bias)}")
    risk = C.RISK_PCT_MIXED if bias == "MISTO" else C.RISK_PCT
    return {"bias": bias, "score": score, "score_bias": bias, "risk_pct": risk, "why": why}


def qqq_context(m: Optional[dict]) -> Optional[dict]:
    """Il QQQ per la conferma degli ingressi [RONIN 20/10c, Andrea: "nei giorni long si compra solo se c'è consonanza dei
    timeframe anche sul QQQ e il QQQ è su un supporto; il contrario per gli short"]: consonanza daily (EMA50 daily e
    inclinazione, weekly sano/non sano) e i suoi supporti e resistenze daily (livelli singoli e confluenze)."""
    if not m:
        return None
    healthy_w = m["w_close"] > m["ew21"] and m["ew9"] > m["ew21"]
    return dict(adr=_r(m["adr"]), close=_r(m["close"]),
                tf_long=bool(trend_tf_ok(m, "long") and healthy_w),
                tf_short=bool(trend_tf_ok(m, "short") and not healthy_w),
                supports=sorted({_r(x["price"]) for x in m.get("supports") or []}),
                resistances=sorted({_r(x["price"]) for x in m.get("resistances") or []}))
