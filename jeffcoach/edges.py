"""Multi-edge alla J Law (METS) sul metodo di Martin [RONIN 22/10, Andrea].

Idea (J Law, serie METS EP1-EP3): si entra in una zona dove più "edge" indipendenti sono d'accordo (META); almeno 2-3
edge, e più ce ne sono meno trade si fanno ma con più probabilità. Per ogni candidato del bot (che ha già passato le
regole di Martin) si misurano cinque edge, ciascuno vero o falso con un punteggio 0-1:

1. M&T  momentum e trend. Trend (EP2): struttura a swing (massimi e minimi crescenti, o decrescenti per gli short),
        medie 9/21/50 impilate e inclinate, trendline e canale parallelo nel verso del trade (trendlines.py).
        Momentum (EP3): candele verdi più delle rosse, gap non chiusi (follow-through), candele grandi con volume
        pesante, volume nei rialzi più che nei ribassi, pullback che tengono la EMA21.
2. S&R  supporti e resistenze multi-timeframe: livelli nella zona del livello d'ingresso pesati per timeframe
        (weekly 1,5, daily 1, 60m 0,5), con almeno un livello weekly, e niente edge per un livello già testato troppe
        volte nelle ultime sedute (EP3: "più un livello viene testato in poco tempo, più è probabile che ceda").
3. CSP/PA/VOL  candele, price action e volume del pullback (EP3, "setup" contro "correzione"): volume che si asciuga,
        candele che si stringono, nessuna giornata di distribuzione (accumulo per gli short), candela d'inversione sul
        livello (pin bar, engulfing, inside day, undercut & reclaim / upthrust).
4. MTF  1h, 1d e 1w: long con 60m e daily concordi, short con il daily (MTF_REQUIRE) [Andrea 22/10e, 23/10a].
5. RS   forza (debolezza per gli short) contro il QQQ a 1 settimana e 1 mese [RONIN 22/10, Andrea], oppure rotazione:
        titolo che si muove questa settimana con il gruppo nel quadrante giusto del grafico settimana/mese dei basket.

Le soglie sono in config.py (prefissi MT_, SR_, PV_, RS_EDGE_, META_); le funzioni sono pure.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from . import config as C
from . import indicators as I
from . import orizzontali as HZ

EDGE_KEYS = ("MT", "SR", "PV", "MTF", "RS")
EDGE_LABEL = {"MT": "M&T", "SR": "S&R", "PV": "PA/VOL", "MTF": "MTF", "RS": "RS"}


# ------------------------------------------------------------------ livelli: timeframe e peso
def level_tf(name: str) -> str:
    """'W' weekly, 'H' 60m, 'D' daily (tutto il resto: EMA daily, AVWAP, swing, gap, trendline)."""
    if name.startswith("weekly ") or name in ("EMA9w", "EMA21w", "EMA50w"):
        return "W"
    if name.startswith(("HZW ", "HLW ")) or HZ.touches_of(name) >= C.HZ_STRONG_TOUCHES:   # orizzontale weekly o con
        return "W"                                                                     # 3+ tocchi: pesa come weekly
    if name.startswith("EMA") and name.endswith("h"):
        return "H"
    return "D"


def level_weight(name: str) -> float:
    return C.SR_TF_WEIGHT.get(level_tf(name), 1.0)


def weighted_count(names) -> float:
    return float(sum(level_weight(n) for n in set(names)))


# ------------------------------------------------------------------ caratteristiche daily (una volta per titolo)
def _side_signs(o, h, lo, c, v, e9, e21, e50, adr, vol50, side: str, gaps: list, swings: dict, tl: dict) -> dict:
    k = 1 if side == "long" else -1
    n = len(c)
    w = min(C.MT_WINDOW, n - 1)
    rets = np.diff(c[-w - 1:])
    up_share = float((k * rets > 0).mean()) if w else 0.0
    rng = (h[-w:] / lo[-w:] - 1) * 100
    cpos = np.where(h[-w:] > lo[-w:], (c[-w:] - lo[-w:]) / np.maximum(h[-w:] - lo[-w:], 1e-12), 0.5)
    big = (k * rets > 0) & (rng >= C.MT_BIG_RANGE_ADR * adr) & (v[-w:] >= C.MT_BIG_VOL * vol50) & \
          ((cpos >= C.MT_BIG_CLOSE_POS) if k == 1 else (cpos <= 1 - C.MT_BIG_CLOSE_POS))
    w50 = min(50, n - 1)
    r50 = np.diff(c[-w50 - 1:])
    vu, vd = float(v[-w50:][r50 > 0].sum()), float(v[-w50:][r50 < 0].sum())
    udv = (vu / vd if vd > 0 else 9.9) if k == 1 else (vd / vu if vu > 0 else 9.9)
    w21 = min(C.MT_EMA21_DAYS, n)
    wrong21 = int((k * (c[-w21:] - e21[-w21:]) < 0).sum())
    hs, ls = swings["hs"], swings["ls"]
    if k == 1:
        # massimi e minimi crescenti, e il pullback non ha rotto l'ultimo minimo crescente
        struct = len(hs) >= 2 and len(ls) >= 2 and h[hs[-1]] > h[hs[-2]] and lo[ls[-1]] > lo[ls[-2]] \
            and c[-1] > lo[ls[-1]]
        mas = e9[-1] > e21[-1] > e50[-1] and e21[-1] > e21[-6] and e50[-1] > e50[-6]
        line = tl.get("up")
    else:
        struct = len(hs) >= 2 and len(ls) >= 2 and h[hs[-1]] < h[hs[-2]] and lo[ls[-1]] < lo[ls[-2]] \
            and c[-1] < h[hs[-1]]
        mas = e9[-1] < e21[-1] < e50[-1] and e21[-1] < e21[-6] and e50[-1] < e50[-6]
        line = tl.get("down")
    # trendline confermata: almeno TL_CONFIRMED_TOUCHES swing (J Law EP2: due punti tracciano la linea, il terzo la
    # conferma); quasi ogni titolo in trend ha una linea per due minimi, quindi due tocchi non distinguono niente
    trend = dict(structure=bool(struct), mas=bool(mas),
                 trendline=bool(line and line["touches"] >= C.TL_CONFIRMED_TOUCHES),
                 channel=bool(line and line.get("channel")))
    mom = dict(
        candles=up_share >= C.MT_UP_SHARE,                                       # verdi più delle rosse (o viceversa)
        gaps=any(g[0] == ("up" if k == 1 else "down") for g in gaps),           # gap non chiusi nel verso del trade
        big_volume=int(big.sum()) >= C.MT_BIG_MIN,                               # candele grandi con volume pesante
        volume_contrast=udv >= C.MT_UDV_MIN,                                     # volume nei rialzi > nei ribassi
        holds_21=wrong21 <= C.MT_EMA21_WRONG_MAX,                                # pullback che tengono la 21
    )
    # ------------------------------------------------ pullback (long) / rimbalzo (short): CSP / PA / VOL
    pb = min(C.PV_LOOKBACK, n - 11)
    top = int(np.argmax(h[-pb:]) if k == 1 else np.argmin(lo[-pb:])) + n - pb      # estremo prima del pullback
    npb = n - 1 - top
    adv = v[max(0, top - 9):top + 1].mean()
    pbv = v[top + 1:].mean() if npb >= 1 else np.nan
    dry = bool(npb >= 1 and pbv <= C.PV_DRY_RATIO * adv)                    # volume che si asciuga nel pullback
    rng3 = float(((h[-3:] / lo[-3:] - 1) * 100).mean())
    inside = bool(h[-1] <= h[-2] and lo[-1] >= lo[-2])
    tight = bool(rng3 <= C.PV_TIGHT_ADR * adr or inside)
    seg = slice(max(top + 1, n - C.PV_DIST_DAYS), n) if npb >= 1 else slice(n, n)
    cp = (c[seg] - lo[seg]) / np.maximum(h[seg] - lo[seg], 1e-12)
    dr = np.diff(c[seg.start - 1:seg.stop]) if npb >= 1 else np.array([])
    heavy = v[seg] >= C.PV_DIST_VOL * vol50
    if k == 1:   # distribuzione nel pullback: ribasso con volume pesante e chiusura nella parte bassa
        bad = bool(len(dr) and ((dr < 0) & heavy & (cp <= C.PV_DIST_CLOSE_POS)).any())
    else:        # accumulo nel rimbalzo: rialzo con volume pesante e chiusura nella parte alta
        bad = bool(len(dr) and ((dr > 0) & heavy & (cp >= 1 - C.PV_DIST_CLOSE_POS)).any())
    body = abs(c[-1] - o[-1])
    rngl = max(h[-1] - lo[-1], 1e-12)
    up_w, dn_w = h[-1] - max(c[-1], o[-1]), min(c[-1], o[-1]) - lo[-1]
    cpos1 = (c[-1] - lo[-1]) / rngl
    if k == 1:
        pin = dn_w >= C.PV_WICK_BODY * body and dn_w >= C.PV_WICK_RANGE * rngl and cpos1 >= C.PV_PIN_CLOSE_POS
        engulf = c[-1] > o[-1] and c[-2] < o[-2] and c[-1] >= o[-2] and o[-1] <= c[-2]
        prev = lo[-4:-1].min()
        reclaim = (lo[-1] < prev and c[-1] > prev and cpos1 >= 0.5) or (lo[-1] < e21[-1] < c[-1])
    else:
        pin = up_w >= C.PV_WICK_BODY * body and up_w >= C.PV_WICK_RANGE * rngl and cpos1 <= 1 - C.PV_PIN_CLOSE_POS
        engulf = c[-1] < o[-1] and c[-2] > o[-2] and c[-1] <= o[-2] and o[-1] >= c[-2]
        prev = h[-4:-1].max()
        reclaim = (h[-1] > prev and c[-1] < prev and cpos1 <= 0.5) or (h[-1] > e21[-1] > c[-1])
    candle = ("pin bar" if pin else "engulfing" if engulf else "undercut & reclaim" if (reclaim and k == 1)
              else "upthrust" if reclaim else "inside day" if inside else None)
    pv = dict(volume_dry=dry, tight=tight, no_distribution=not bad, candle=candle)
    return dict(trend=trend, momentum=mom, pv=pv, up_share=round(up_share, 2), udv=round(udv, 2),
                pullback_days=int(npb))


def daily_features(df: pd.DataFrame, e9: pd.Series, e21: pd.Series, e50: pd.Series, adr: float, tl: dict) -> dict:
    """Caratteristiche per i due lati, sull'ultima barra completa di `df`."""
    o, h, lo, c = (df[x].to_numpy(dtype=float) for x in ("Open", "High", "Low", "Close"))
    v = df.Volume.to_numpy(dtype=float)
    vol50 = float(v[-50:].mean()) if len(v) >= 50 else float(v.mean())
    gaps = I.unfilled_gaps(df)
    swings = dict(hs=I.swing_highs(df, C.SWING_K, C.SWING_LOOKBACK), ls=I.swing_lows(df, C.SWING_K, C.SWING_LOOKBACK))
    ea, eb, ec = e9.to_numpy(dtype=float), e21.to_numpy(dtype=float), e50.to_numpy(dtype=float)
    return {side: _side_signs(o, h, lo, c, v, ea, eb, ec, adr, vol50, side, gaps, swings, tl) for side in ("long", "short")}


# ------------------------------------------------------------------ valutazione dei cinque edge
def mt_edge(f: dict) -> tuple[bool, float, list[str]]:
    tr, mo = f["trend"], f["momentum"]
    nt, nm = sum(bool(x) for x in tr.values()), sum(bool(x) for x in mo.values())
    ok = nt >= C.MT_TREND_MIN and nm >= C.MT_MOM_MIN
    why = [k for k, x in tr.items() if x] + [k for k, x in mo.items() if x]
    return ok, round((nt / len(tr) + nm / len(mo)) / 2, 2), why


def level_tests(level: float, side: str, recent: dict, adr: float) -> int:
    """Test del livello nelle ultime SR_TEST_DAYS sedute [J Law EP3]: barre che entrano nella fascia del livello (±
    SR_TEST_TOL_ADR ADR) arrivando dalla parte giusta (dall'alto per un supporto, dal basso per una resistenza) e chiudono
    senza romperla. Le barre lontane dalla fascia non contano (per una media che sale i minimi di settimane fa stanno
    sotto il suo valore di oggi, ma non erano test)."""
    lows, highs, closes = (np.array(recent.get(k) or [], dtype=float) for k in ("lows", "highs", "closes"))
    n = min(len(lows), len(highs), len(closes))
    if n < 2 or not level or not adr:
        return 0
    tol = C.SR_TEST_TOL_ADR * adr / 100
    top, bot = level * (1 + tol), level * (1 - tol)
    tests = 0
    for i in range(1, n):
        if side == "long":
            if lows[i] <= top and lows[i - 1] > top and closes[i] >= bot:
                tests += 1
        elif highs[i] >= bot and highs[i - 1] < bot and closes[i] <= top:
            tests += 1
    return tests


def _dist_pct(x: dict, level: float) -> float:
    """Distanza in % del livello `x` da `level`; per un'area (lo/hi) dal bordo più vicino, 0 se `level` è dentro."""
    lo, hi = x.get("lo", x["price"]), x.get("hi", x["price"])
    if lo <= level <= hi:
        return 0.0
    return min(abs(lo / level - 1), abs(hi / level - 1)) * 100


def sr_edge(level: Optional[float], levels: list[dict], adr: float, side: str, recent: dict,
            extra: Optional[list[dict]] = None) -> tuple[bool, float, dict]:
    """Livelli nella zona (entro ZONE_ADR_FRAC ADR dal livello) pesati per timeframe (SR_TF_WEIGHT), più i test recenti
    del livello: edge con peso di almeno SR_EDGE_MIN_W e meno di SR_MAX_TESTS test."""
    if not level or not adr:
        return False, 0.0, {}
    tol_zone = C.ZONE_ADR_FRAC * adr
    names = {x["name"] for x in (levels or []) + (extra or []) if _dist_pct(x, level) <= tol_zone}
    wsum = weighted_count(names)
    tests = level_tests(level, side, recent or {}, adr)
    tfs = "".join(t for t in ("W", "D", "H") if any(level_tf(n) == t for n in names))
    # zona multi-timeframe: anche un livello weekly [Andrea: "maggiore importanza ai timeframe daily e weekly"]
    ok = wsum >= C.SR_EDGE_MIN_W and tests < C.SR_MAX_TESTS and ("W" in tfs or not C.SR_REQUIRE_WEEKLY)
    return ok, round(min(1.0, wsum / (2 * C.SR_EDGE_MIN_W)), 2), dict(wsum=round(wsum, 1), tests=tests, tfs=tfs,
                                                                         levels=sorted(names))


def pv_edge(f: dict) -> tuple[bool, float, list[str]]:
    p = f["pv"]
    n = int(p["volume_dry"]) + int(p["tight"]) + int(bool(p["candle"]))
    ok = p["no_distribution"] and n >= C.PV_MIN_SIGNS
    why = [k for k in ("volume_dry", "tight") if p[k]] + ([p["candle"]] if p["candle"] else []) + \
          ([] if p["no_distribution"] else ["distribution"])
    return ok, round((n + int(p["no_distribution"])) / 4, 2), why


def mtf_edge(m: dict, side: str, tf_h: Optional[int]) -> tuple[bool, float, dict]:
    """1h, 1d e 1w nel verso del trade, con i timeframe obbligatori per lato in MTF_REQUIRE [RONIN 22/10e: long almeno
    1h e 1d; 23/10a: short solo 1d, Andrea]. 60m = close e EMA9 dalla parte giusta della EMA21 oraria (ultima barra
    chiusa); daily = close oltre la EMA21, 9 oltre 21, 21 inclinata; weekly = close oltre la EMA9 weekly, 9 oltre 21, 9
    inclinata. Quello che non è obbligatorio alza solo il punteggio; senza barre orarie al posto del 60m vale il weekly."""
    k = 1 if side == "long" else -1
    w = bool(k * (m["w_close"] - m["ew9"]) > 0 and k * (m["ew9"] - m["ew21"]) > 0 and k * (m.get("ew9_slope") or 0) > 0)
    d = bool(k * (m["close"] - m["e21"]) > 0 and k * (m["e9"] - m["e21"]) > 0 and k * (m.get("e21_slope") or 0) > 0)
    h = None if tf_h is None else tf_h == 1
    got = {"W": w, "D": d, "H": h if h is not None else w}
    ok = all(got[t] for t in C.MTF_REQUIRE.get(side, ("H", "D")))
    return ok, round((int(w) + int(d) + int(bool(h))) / 3, 2), dict(W=w, D=d, H=h)


def rs_edge(m: dict, side: str, quad: Optional[str]) -> tuple[bool, float, dict]:
    rs5, rs21 = m.get("rs5"), m.get("rs21")
    if rs5 is None or rs21 is None:
        return False, 0.0, {}
    if side == "long":
        strong = rs5 > 0 and rs21 > 0 and rs21 <= C.RS_EDGE_RS21_LONG_MAX
        rot = rs5 >= C.RS_EDGE_ROT_RS5 and rs21 <= C.RS_EDGE_RS21_LONG_MAX and quad in C.RS_EDGE_QUAD_LONG
        score = max(0.0, min(1.0, 0.5 + rs5 / 20 + rs21 / 40))
    else:
        strong = rs5 < 0 and rs21 < 0
        rot = rs5 <= -C.RS_EDGE_ROT_RS5 and quad in C.RS_EDGE_QUAD_SHORT
        score = max(0.0, min(1.0, 0.5 - rs5 / 20 - rs21 / 40))
    return bool(strong or rot), round(score, 2), dict(rs5=rs5, rs21=rs21, quad=quad, rotation=bool(rot and not strong))


def evaluate(row: dict, m: dict, quad: Optional[str] = None, extra: Optional[list[dict]] = None) -> dict:
    """I cinque edge di un candidato: `row` riga della lista (lato, livello, tf_h), `m` metriche daily del titolo,
    `quad` quadrante RS del suo gruppo, `extra` livelli a 60m. Restituisce n_edges, edges (chiavi vere), edge_score
    (somma dei punteggi 0-1) ed edge_detail (per lo studio e il giornale)."""
    side = row["side"]
    f = (m.get("edge_feat") or {}).get(side)
    res: dict = {}
    res["MT"] = mt_edge(f) if f else (False, 0.0, [])
    res["PV"] = pv_edge(f) if f else (False, 0.0, [])
    levels = m["supports"] if side == "long" else m["resistances"]
    more = ((m.get("levels_x") or {}).get(side) or []) + (extra or [])
    res["SR"] = sr_edge(row.get("level"), levels, m.get("adr") or 0, side, m.get("recent") or {}, more)
    res["MTF"] = mtf_edge(m, side, row.get("tf_h"))
    res["RS"] = rs_edge(m, side, quad)
    on = [k for k in EDGE_KEYS if res[k][0]]
    return dict(
        n_edges=len(on), edges=on, edge_score=round(sum(res[k][1] for k in EDGE_KEYS), 2),
        edge_detail={k: {"ok": bool(res[k][0]), "score": res[k][1], "why": res[k][2]} for k in EDGE_KEYS},
    )


def edges_text(r: dict, compact: bool = False) -> str:
    """Edge in inglese per card ('edges 4/5 (M&T S&R MTF RS)') e alert ('Edges `4/5`: M&T, S&R, MTF, RS')."""
    if r.get("n_edges") is None:
        return ""
    on = [EDGE_LABEL[k] for k in (r.get("edges") or [])]
    if compact:
        return f"edges {r['n_edges']}/{len(EDGE_KEYS)}" + (f" ({' '.join(on)})" if on else "")
    return f"Edges `{r['n_edges']}/{len(EDGE_KEYS)}`" + (f": {', '.join(on)}" if on else "")


def tl_text(r: dict) -> str:
    """Trendline nel verso del trade per gli alert: 'Trendline up `212.21` (3 touches, channel)'."""
    t = r.get("tl")
    if not t or t.get("value") is None:
        return ""
    extra = f"{t['touches']} touches" + (", channel" if t.get("channel") else "")
    return f"Trendline {'up' if r.get('side') == 'long' else 'down'} `{t['value']:.2f}` ({extra})"


def hz_text(r: dict) -> str:
    """Livello orizzontale vicino al livello d'ingresso per gli alert: 'Horizontal zone `164.60-169.81` (7 touches)'."""
    z = r.get("hz")
    if not z:
        return ""
    if z.get("kind") == "zone":
        return f"Horizontal zone `{z['lo']:.2f}-{z['hi']:.2f}` ({z['touches']} touches)"
    return f"Horizontal level `{z['price']:.2f}` ({z['touches']} touches)"


def hourly_levels(h: Optional[pd.DataFrame], side: str, close: float) -> list[dict]:
    """Livelli a 60m per la zona (peso basso): EMA21 ed EMA50 orarie nel verso del trade, in salita sotto il prezzo per i
    long, in discesa sopra per gli short [ML: "rimbalzo nella 21/50 oraria" (AOI), la 50 oraria in 14 live]."""
    if h is None or len(h) < 60:
        return []
    c = h["Close"].astype(float)
    out = []
    for n in (21, 50):
        e = I.ema(c, n)
        v = float(e.iloc[-1])
        rising = v > float(e.iloc[-1 - C.H60_SLOPE_BARS])
        if side == "long" and rising and v < close:
            out.append({"name": f"EMA{n}h", "price": v})
        if side == "short" and not rising and v > close:
            out.append({"name": f"EMA{n}h", "price": v})
    return out
