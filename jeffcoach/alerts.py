"""Alert intraday + gestione intraday dei trade simulati (gira sul server, sempre acceso).

Per ogni Focus della lista del giorno:
  1. "livello raggiunto": il prezzo arriva entro LEVEL_TOUCH_PCT dal livello di confluenza (una volta);
  2. "trigger": dopo il tocco, rottura del massimo (long) / minimo (short) della barra precedente,
     su 5m per tutta la seduta [RONIN 27/10d-e; prima 1m, 5m, 15m]; attesa d'apertura EARLY_MIN. Stop = LOD/HOD, oppure estremo della barra
     se il LOD/HOD è troppo lontano; scartato se lo stop supera min(2%, 0,5 ADR).
     Un trigger che passa tutti i filtri apre un trade simulato e manda l'alert; se un filtro lo blocca
     (gap degli indici, freno giornaliero, pausa, inseguimento, stop largo, esposizione) diventa un trade
     ombra: niente alert, solo giornale.
Per ogni posizione aperta: gap oltre lo stop all'apertura, stop, trim a R, (short) barra oraria sopra la EMA50.

Uso:
  python -m jeffcoach.alerts --service           (systemd: sempre acceso, lavora solo in seduta)
  python -m jeffcoach.alerts --once --dry-run --force-window
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from . import config as C
from . import gruppo as GR
from . import data as D
from . import indicators as I
from . import journal as J
from .calendar_us import ET, close_et, is_session, now_et, open_et
from .chart import alert_chart
from .discord import send_alert
from .edges import edges_text, hz_text, tl_text
from .output import write_atomic

log = logging.getLogger("jeffcoach.alerts")
_hourly_cache: dict = {"ts": None, "bars": {}}


# ------------------------------------------------------------------ finestra e stato
def minutes_from_open(now: datetime) -> Optional[float]:
    n = now.astimezone(ET)
    if not is_session(n.date()):
        return None
    return (n - open_et(n.date())).total_seconds() / 60.0


def in_window(now: datetime) -> bool:
    n = now.astimezone(ET)
    return is_session(n.date()) and open_et(n.date()) <= n <= close_et(n.date()) + timedelta(minutes=2)


def load_list(today: date) -> Optional[dict]:
    p = C.LISTS / "today.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return d if d.get("session_date") == today.isoformat() else None


def state_path(today: date):
    return C.ALERTS_STATE / f"{today}.json"


def load_state(today: date) -> dict:
    p = state_path(today)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"fired": {}, "touched": {}, "new_trades": 0}


# ------------------------------------------------------------------ barre
def today_bars(b: pd.DataFrame, today: date) -> pd.DataFrame:
    o, c = open_et(today), close_et(today)
    return b[(b.index >= o) & (b.index < c)]


def resample(b: pd.DataFrame, tf: int, today: date) -> pd.DataFrame:
    """Barre da tf minuti allineate all'apertura; l'ultima è quella in corso."""
    if tf == 1:
        return b.copy()
    return b.resample(f"{tf}min", origin=open_et(today), label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna(subset=["Close"])


def trigger_tf(mins: float) -> int:
    return 1 if mins < C.TRIGGER_1M_UNTIL_MIN else (5 if mins < C.TRIGGER_5M_UNTIL_MIN else 15)


def early_reason(side: str, mins: float, b: pd.DataFrame, qqq_gap: Optional[float], lvl: Optional[float] = None,
                 adr: Optional[float] = None) -> Optional[str]:
    """Regole d'apertura [ML: "devo stare fermo nei primi 15 minuti", 23/04, EP103; RONIN 17/10]: nei primi EARLY_MIN
    minuti niente trigger, salvo apertura già sul livello giusto (entro EARLY_OPEN_NEAR_ADR ADR: gap dentro la
    resistenza per lo short, gap down sul supporto per il long [ML 14/07, 13/08]); in quel caso i long vogliono anche
    la prima candela 1m stretta (< 1,5%). Con il QQQ in gap up i long aspettano INDEX_GAP_UP_LONG_WAIT_MIN minuti, in
    gap down gli short INDEX_GAP_DOWN_SHORT_WAIT_MIN. None = si può entrare."""
    if side == "short" and qqq_gap is not None and qqq_gap <= -C.INDEX_GAP_BLOCK_PCT and mins < C.INDEX_GAP_DOWN_SHORT_WAIT_MIN:
        return f"QQQ in gap {qqq_gap:+.2f}%: short dopo {C.INDEX_GAP_DOWN_SHORT_WAIT_MIN} minuti"
    if side == "long" and qqq_gap is not None and qqq_gap >= C.INDEX_GAP_BLOCK_PCT and mins < C.INDEX_GAP_UP_LONG_WAIT_MIN:
        return f"QQQ in gap {qqq_gap:+.2f}%: long dopo {C.INDEX_GAP_UP_LONG_WAIT_MIN} minuti"
    if mins >= C.EARLY_MIN or not len(b):
        return None
    f = b.iloc[0]
    o = float(f.Open)
    near = False
    if lvl and adr and o:
        dist = (o / lvl - 1) * 100
        near = (dist >= -C.EARLY_OPEN_NEAR_ADR * adr) if side == "short" else (dist <= C.EARLY_OPEN_NEAR_ADR * adr)
    if not near:
        return f"primi {C.EARLY_MIN} minuti: apertura lontana dal livello"
    if side == "long":
        rng = (float(f.High) - float(f.Low)) / o * 100 if o else 0.0
        if rng >= C.EARLY_LONG_FIRST_BAR_MAX_PCT:
            return f"primi {C.EARLY_MIN} minuti: prima candela 1m ampia {rng:.1f}%"
    return None


def hourly_bars(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Barre orarie (per la regola EMA50 oraria degli short), aggiornate ogni 15 minuti."""
    now = time.time()
    if _hourly_cache["ts"] and now - _hourly_cache["ts"] < 900 and set(tickers) <= set(_hourly_cache["bars"]):
        return _hourly_cache["bars"]
    bars = D.download_intraday(tickers, period="1mo", interval="60m") if tickers else {}
    _hourly_cache.update(ts=now, bars=bars)
    return bars


def trend_60m(qh: Optional[pd.DataFrame], price: float, side: str) -> Optional[bool]:
    """Trend a 60m [RONIN 20/10d, Andrea]: prezzo dalla parte giusta della EMA50 oraria ed EMA50 inclinata nel verso
    del trade (H60_SLOPE_BARS barre). Con QQQ_TREND_SWINGS anche la struttura: ultimi due massimi e minimi di swing
    crescenti (long) o decrescenti (short), tolta il 20/10g [Andrea]. None se mancano le barre."""
    if qh is None or len(qh) < 60:
        return None
    ch = qh.Close.astype(float).copy()
    ch.iloc[-1] = price
    kind, n = C.QQQ_TREND_MA                     # ("ema", 50) dal 20/10d; ("sma", 30) in prova [Andrea 20/10]
    e50 = I.ema(ch, n) if kind == "ema" else ch.rolling(n).mean()
    d50 = float(e50.iloc[-1] - e50.iloc[-1 - C.H60_SLOPE_BARS])
    h, l = qh.High.astype(float).values, qh.Low.astype(float).values
    k = C.SWING_60M_K
    sh = [h[i] for i in range(k, len(h) - k) if h[i] == max(h[i - k:i + k + 1])]
    sl = [l[i] for i in range(k, len(l) - k) if l[i] == min(l[i - k:i + k + 1])]
    if len(sh) < 2 or len(sl) < 2:
        return False
    if side == "long":
        return bool(price > float(e50.iloc[-1]) and d50 > 0 and (not C.QQQ_TREND_SWINGS or (sh[-1] > sh[-2] and sl[-1] > sl[-2])))
    return bool(price < float(e50.iloc[-1]) and d50 < 0 and (not C.QQQ_TREND_SWINGS or (sh[-1] < sh[-2] and sl[-1] < sl[-2])))


def qqq_gate(side: str, ctx: Optional[dict], qb: Optional[pd.DataFrame], qh: Optional[pd.DataFrame]) -> Optional[str]:
    """Conferma del QQQ all'ingresso [RONIN 20/10c-d, Andrea]. Long: QQQ in trend a 60m (sopra la EMA50 oraria in
    salita, massimi e minimi crescenti) e su un suo supporto daily (toccato oggi entro QQQ_LEVEL_ADR ADR, prezzo ancora
    entro QQQ_LEVEL_NEAR_ADR ADR). Short: il contrario, su una resistenza. Ritorna il motivo dello scarto o None."""
    if not C.QQQ_GATE or not ctx or qb is None or not len(qb):
        return None
    px = float(qb.Close.iloc[-1])
    tr = trend_60m(qh, px, side) if C.QQQ_GATE_TREND else None
    if tr is False:
        return "QQQ 60m not trending " + ("up" if side == "long" else "down")
    if not C.QQQ_GATE_LEVEL:
        return None
    adr = (ctx.get("adr") or 1.5) / 100
    for lv in ctx.get("supports" if side == "long" else "resistances") or []:
        tol, near = lv * adr * C.QQQ_LEVEL_ADR, lv * adr * C.QQQ_LEVEL_NEAR_ADR
        hit = (float(qb.Low.min()) <= lv + tol) if side == "long" else (float(qb.High.max()) >= lv - tol)
        if hit and abs(px - lv) <= near:
            return None
    return "QQQ not at a daily " + ("support" if side == "long" else "resistance")


# ------------------------------------------------------------------ messaggi
def _members(r: dict) -> str:
    from .output import members_text
    return members_text(r.get("level_members") or [], 4)


_SYNC: dict = {}


def _sync(r: dict) -> str:
    """Sincronia [RONIN 17/10]: QQQ ed ETF del tema rispetto a 9/21/50 daily al prezzo di adesso."""
    out = []
    for k in ("QQQ", r.get("sync_etf")):
        lv, px = (_SYNC.get("levels") or {}).get(k), (_SYNC.get("px") or {}).get(k)
        if not k or not lv or px is None:
            continue
        out.append(f"{k} `{px:.2f}` " + " ".join((">" if px > lv[n] else "<") + n[1:] for n in ("e9", "e21", "e50") if lv.get(n)))
    return ("Sync: " + " · ".join(out)) if out else ""


def _context(r: dict) -> str:
    rs = r.get("rs21")
    parts = [r.get("list") or "", f"RS `{rs:+.1f}`" if rs is not None else "",
             f"ADR `{r['adr']:.1f}%`" if r.get("adr") is not None else ""]
    if r.get("theme"):
        ph = r.get("theme_phase")
        parts.append(r["theme"] + (f" ({C.PHASE_EN.get(ph, ph)})" if ph else ""))
    if r.get("grade"):
        parts.append(f"review **{r['grade']}**")
    sy = _sync(r)
    # multi-edge e trendline del giorno [RONIN 22/10]
    ed = " · ".join(x for x in (edges_text(r), tl_text(r), hz_text(r)) if x)
    return " · ".join(p for p in parts if p) + (f"\n{ed}" if ed else "") + (f"\n{sy}" if sy else "")


def plan_entry_sl(r: dict, b: pd.DataFrame, tf: int, today: date) -> Optional[tuple[float, float, str]]:
    """Entry e SL pianificati per l'avviso al livello: rottura dell'ultima barra chiusa del timeframe del trigger;
    SL a LOD/HOD, o all'estremo di quella barra se il LOD/HOD supera min(2%, 0,5 ADR) [ML]."""
    rb = resample(b, tf, today)
    if len(rb) < 2:
        return None
    bar = rb.iloc[-2]
    max_stop = min(C.STOP_MAX_PCT, C.STOP_MAX_ADR_FRAC * (r.get("adr") or 99))
    if r["side"] == "long":
        entry, sl, src = float(bar.High), float(b.Low.min()), "LOD"
        if (entry - sl) / entry * 100 > max_stop:
            sl, src = float(bar.Low), f"{tf}m bar low"
    else:
        entry, sl, src = float(bar.Low), float(b.High.max()), "HOD"
        if (sl - entry) / entry * 100 > max_stop:
            sl, src = float(bar.High), f"{tf}m bar high"
    return entry, sl, src


def fmt_level(r: dict, price: float, tf: int, failed: bool = False,
              plan: Optional[tuple[float, float, str]] = None) -> tuple[str, str]:
    """Come gli alert di Sydney: titolo 'TICKER · setup', una misura per riga con il valore evidenziato,
    contenuti del metodo Martin [RONIN 13/10]."""
    long = r["side"] == "long"
    dist = (price / r["level"] - 1) * 100
    lines = [f"Confluence {'support' if long else 'resistance'} `{r['level']:.2f}`" + (f" · {_members(r)}" if _members(r) else ""),
             f"Price: `{price:.2f}` · `{dist:+.1f}%` from the level",
             (f"**Failed {'breakdown' if long else 'breakout'}**: crossed the level and came back — best setup" if failed
              else f"Turning at the level ({'green' if long else 'red'} 5m bar)"),
             f"Plan: {r['side'].upper()} on the break of the prior {tf}m bar {'high' if long else 'low'}",
             (f"Entry `{plan[0]:.2f}` · SL `{plan[1]:.2f}` (`{abs(plan[0] - plan[1]) / plan[0] * 100:.2f}%`, {plan[2]})"
              if plan else ""),
             _context(r)]
    if r.get("note"):
        lines.append(r["note"])
    title = f"{r['ticker']} · " + ((f"Failed {'breakdown' if long else 'breakout'} at {'support' if long else 'resistance'}") if failed
                                   else f"At {'support' if long else 'resistance'}")
    return title, "\n".join(x for x in lines if x)


def fmt_trigger(p: dict, tf: int, stop_src: str, r: dict) -> tuple[str, str]:
    long = p["side"] == "long"
    per = abs(p["entry"] - p["stop"])
    trim_r = C.LONG_TRIM_R if long else C.SHORT_TRIM_R
    tgt = p["entry"] + trim_r * per if long else p["entry"] - trim_r * per
    lines = [f"Entry `{p['entry']:.2f}` · SL `{p['stop']:.2f}` (`{p['stop_pct']:.2f}%`, {stop_src})",
             f"Size `{p['size_pct']:.1f}%` · Risk `{p['risk_pct']:.2f}%` (sim. 100k)",
             f"Level `{p['level']:.2f}`" + (f" · {_members(r)}" if _members(r) else ""),
             f"1R `{per:.2f}` · first trim `{tgt:.2f}` ({trim_r:g}R)",
             f"Minute `{p['minutes_from_open']}` from the open · {_context(r)}"]
    # falso breakout/breakdown da un nome dei tracking [16/10]: "Failed breakdown" per i long, "Failed breakout" per gli
    # short [RONIN 17/10, Andrea]
    kind = ("Failed breakdown" if p["side"] == "long" else "Failed breakout") if r.get("fakeout") else "Pullback"
    return f"{p['ticker']} · {kind} {p['side']} · {tf}m trigger", "\n".join(lines)


def fmt_exit(p: dict, kind: str, price: float, reason: str) -> tuple[str, str]:
    r = J.r_of(p, price)
    return f"{p['ticker']} · {kind} ({p['side']})", "\n".join([
        f"Price: `{price:.2f}` · `{r:+.1f}R`", reason[:1].upper() + reason[1:],
        f"Entry `{p['entry']:.2f}` · Stop `{p['stop']:.2f}` · opened {p['date_open']}"])


def _exit_msg(p: dict, kind: str, price: float, reason: str) -> tuple:
    """(lato, titolo, testo, grafico): bordo del lato della posizione, grafico con entrata, stop e uscita."""
    t, b = fmt_exit(p, kind, price, reason)
    return (p["side"], t, b, dict(ticker=p["ticker"], side=p["side"], level=p.get("level"), entry=p["entry"],
                                  stop=p["stop"], exit_px=price, tf=5, title=kind.lower()))


# ------------------------------------------------------------------ gestione posizioni
def _ext_trims(p: dict, bar) -> list[tuple[float, int, str]]:
    """Parziali nelle estensioni dalla EMA9 daily (modo ext_h50): [(prezzo, azioni, etichetta)] toccati da questa barra."""
    e9, atr = p.get("e9d"), p.get("atr_d")
    if not e9 or not atr:
        return []
    k = 1 if p["side"] == "long" else -1
    out = []
    for mult, q in (C.LONG_EXT_TRIMS if p["side"] == "long" else C.SHORT_EXT_TRIMS):
        if mult in p.setdefault("ext_trims", []):
            continue
        px = e9 + k * mult * atr
        beyond_entry = (px > p["entry"]) if k == 1 else (px < p["entry"])
        hit = (bar.High >= px) if k == 1 else (bar.Low <= px)
        if beyond_entry and hit:
            p["ext_trims"].append(mult)
            out.append((px, max(1, int(round(p["shares"] * q))), f"{'+' if k == 1 else '-'}{mult:g} ATR dalla EMA9 daily"))
    return out


def manage_positions(ps: list[dict], bars: dict[str, pd.DataFrame], today: date, dry_run: bool) -> list[str]:
    msgs = []
    ext = C.MGMT_MODE == "ext_h50"
    need_h = sorted({p["ticker"] for p in ps if p["shares_open"] > 0 and (ext or p["side"] == "short")})
    hb = hourly_bars(need_h) if need_h else {}
    for p in ps:
        b = bars.get(p["ticker"])
        if b is None or not len(b) or p["shares_open"] <= 0:
            continue
        seen = p.get("seen_ts")
        new = b[b.index > pd.Timestamp(seen)] if seen else b
        if p["date_open"] == today.isoformat() and not seen:
            new = b[b.index >= pd.Timestamp(p["time_open_rome"]).tz_convert(ET).floor("min")]
        if not len(new):
            continue
        tk = f"open_checked_{today}"
        if p["date_open"] != today.isoformat() and not p.get(tk):
            o = float(b.Open.iloc[0])
            p[tk] = True
            if (p["side"] == "long" and o <= p["stop"]) or (p["side"] == "short" and o >= p["stop"]):
                p["gap_through_stop"] = True
                J.fill(p, p["shares_open"], o, "exit", "gap oltre lo stop all'apertura")
                if not p["shadow"]:
                    msgs.append((_exit_msg(p, "Stop (gap)", o, "gap through stop at the open")))
                continue
        long_ = p["side"] == "long"
        per = abs(p["entry"] - p["stop"])
        for ix, bar in new.iterrows():
            J.update_extremes(p, float(bar.High), float(bar.Low))
            if (long_ and bar.Low <= p["stop"]) or (not long_ and bar.High >= p["stop"]):
                J.fill(p, p["shares_open"], p["stop"], "exit", "stop")
                if not p["shadow"]:
                    msgs.append((_exit_msg(p, "Stop", p["stop"], "stop hit")))
                break
            if ext:
                for px, sh, why in _ext_trims(p, bar):
                    J.fill(p, sh, px, "trim", f"parziale {why}")
                    if not p["shadow"]:
                        msgs.append((_exit_msg(p, "Trim" if long_ else "Cover part", px,
                                               f"{'sell' if long_ else 'cover'} part: {why.replace('ATR dalla EMA9 daily', 'ATR from the daily 9 EMA')}")))
                fav = (bar.High - p["entry"]) if long_ else (p["entry"] - bar.Low)
                if per and fav >= C.TRAIL_H50_AFTER_R * per:
                    p["trail_on"] = True
                if p["shares_open"] <= 0:
                    break
                continue
            if long_:
                tgt = p["entry"] + C.LONG_TRIM_R * per
                if not p["trimmed"] and bar.High >= tgt:
                    p["trimmed"] = True
                    J.fill(p, max(1, int(p["shares"] * C.LONG_TRIM_FRAC)), tgt, "trim", f"trim {C.LONG_TRIM_R:g}R")
                    if not p["shadow"]:
                        msgs.append((_exit_msg(p, "Trim", tgt, f"sell {C.LONG_TRIM_FRAC:.0%} into strength")))
            else:
                tgt = p["entry"] - C.SHORT_TRIM_R * per
                if not p["trimmed"] and bar.Low <= tgt:
                    p["trimmed"] = True
                    J.fill(p, max(1, int(p["shares"] * C.SHORT_TRIM_FRAC)), tgt, "trim", f"copertura {C.SHORT_TRIM_R:g}R")
                    if not p["shadow"]:
                        msgs.append((_exit_msg(p, "Cover part", tgt, f"cover {C.SHORT_TRIM_FRAC:.0%} into weakness")))
        p["seen_ts"] = str(new.index[-1])
        # EMA50 oraria: trailing di entrambi i lati dopo +1R (ext_h50) oppure uscita degli short (classic)
        use_h = p["shares_open"] > 0 and p["ticker"] in hb and (p.get("trail_on") if ext else not long_)
        if use_h:
            n = C.TRAIL_H50_EMA if ext else C.SHORT_EXIT_HOURLY_EMA
            h = hb[p["ticker"]]
            h = h[h.index + timedelta(hours=1) <= b.index[-1] + timedelta(minutes=1)]      # solo barre orarie chiuse
            if len(h) > n:
                e = I.ema(h.Close, n)
                opened = pd.Timestamp(p["time_open_rome"]).tz_convert(ET)
                crossed = (h.Close.iloc[-1] < e.iloc[-1]) if long_ else (h.Close.iloc[-1] > e.iloc[-1])
                if h.index[-1] + timedelta(hours=1) > opened and crossed:
                    px = float(b.Close.iloc[-1])
                    J.fill(p, p["shares_open"], px, "exit", f"barra oraria {'sotto' if long_ else 'sopra'} la EMA50 oraria")
                    if not p["shadow"]:
                        msgs.append((_exit_msg(p, "Exit", px, f"hourly close {'below' if long_ else 'above'} the hourly 50 EMA")))
    return msgs


# ------------------------------------------------------------------ ciclo
def run_once(dry_run: bool = False, now: Optional[datetime] = None) -> dict:
    now = now or now_et()
    today = now.astimezone(ET).date()
    mins = minutes_from_open(now)
    lst = load_list(today)
    with J.lock():
        ps = J.positions()
        st = load_state(today)
        focus = ((lst or {}).get("focus") or []) + ((lst or {}).get("counter_focus") or [])   # + lato opposto [RONIN 13/10]
        focus = focus + ((lst or {}).get("fakeout_watch") or [])     # + tracking, solo falso breakout [RONIN 16/10]
        tickers = sorted({r["ticker"] for r in focus} | {p["ticker"] for p in ps} | {"QQQ"}
                         | {r["sync_etf"] for r in focus if r.get("sync_etf")}           # ETF per la sincronia [17/10]
                         | {r["group_etf"] for r in focus if r.get("group_etf")})        # ETF del gruppo [28/10a]
        raw = D.download_intraday(tickers, period="1d", interval="1m")
        bars = {t: today_bars(b, today) for t, b in raw.items()}
        bars = {t: b for t, b in bars.items() if len(b)}
        _SYNC.update(levels=(lst or {}).get("sync_levels") or {}, px={t: float(b.Close.iloc[-1]) for t, b in bars.items()})
        msgs = manage_positions(ps, bars, today, dry_run)
        ps = J.commit(ps, today)              # salva subito: open_trade rilegge le posizioni dal file

        # gap degli indici all'apertura
        q = bars.get("QQQ")
        if q is not None and lst and lst.get("qqq_prev_close") and "qqq_gap" not in st:
            st["qqq_gap"] = round((float(q.Open.iloc[0]) / lst["qqq_prev_close"] - 1) * 100, 2)
        gap = st.get("qqq_gap")
        js = J.state()
        paused = (not C.ALERTS_ONLY) and js.get("pause_until") and today.isoformat() <= js["pause_until"]

        for r in focus if (lst and mins is not None and mins >= 1) else []:
            t, side = r["ticker"], r["side"]
            b = bars.get(t)
            if b is None or r.get("level") is None:
                continue
            price = float(b.Close.iloc[-1])
            lvl = r["level"]
            fk = bool(r.get("fakeout"))
            # avvicinamento al livello (prima del tocco) e, con mercato forte, alla resistenza per il breakout [RONIN 14/10]
            appr_pct = min(C.APPROACH_PCT, C.APPROACH_ADR_FRAC * (r.get("adr") or 99))
            ap = st.setdefault("approach", {})
            if not fk and t not in ap and ((side == "short" and lvl * (1 - appr_pct / 100) <= price < lvl)
                                or (side == "long" and lvl < price <= lvl * (1 + appr_pct / 100))):
                ap[t] = now.isoformat()
                where = "resistance" if side == "short" else "support"
                msgs.append(("info", f"{t} · Approaching {where}",
                             f"Confluence {where} `{lvl:.2f}`" + (f" · {_members(r)}" if _members(r) else "")
                             + f"\nPrice: `{price:.2f}` · `{(price / lvl - 1) * 100:+.1f}%` from the level"
                             + f"\nWatch for the turn at the level ({'red' if side == 'short' else 'green'} 5m bar or failed "
                             + f"{'breakout' if side == 'short' else 'breakdown'})\n{_context(r)}",
                             dict(ticker=t, side=side, level=lvl, tf=5, title=f"approaching {where}")))
            bo = r.get("breakout_level")
            if not fk and side == "long" and bo and lst.get("bias") in C.BREAKOUT_ALERT_BIASES:
                bk = st.setdefault("breakout", {})
                if f"{t}|near" not in bk and bo * (1 - appr_pct / 100) <= price < bo:
                    bk[f"{t}|near"] = now.isoformat()
                    msgs.append(("long", f"{t} · Approaching breakout level",
                                 f"Resistance `{bo:.2f}` (10-day high) · strong market\nPrice: `{price:.2f}` · "
                                 f"`{(price / bo - 1) * 100:+.1f}%` from the level\nPlan: LONG on the break of `{bo:.2f}`\n{_context(r)}",
                                 dict(ticker=t, side="long", level=bo, tf=5, title="approaching breakout")))
                if f"{t}|break" not in bk and price > bo:
                    bk[f"{t}|break"] = now.isoformat()
                    msgs.append(("long", f"{t} · Breaking out",
                                 f"Above the 10-day high `{bo:.2f}` · price `{price:.2f}`\nStrong market: check volume and the hold "
                                 f"of the level on the 5m\n{_context(r)}",
                                 dict(ticker=t, side="long", level=bo, tf=5, title="breakout")))
            # tocco RECENTE del livello, prezzo ancora vicino e inversione [RONIN 14/10]
            rec = b[b.index >= b.index[-1] - timedelta(minutes=C.TOUCH_LOOKBACK_MIN)]
            touched = (float(rec.Low.min()) <= lvl * (1 + C.LEVEL_TOUCH_PCT / 100)) if side == "long" \
                else (float(rec.High.max()) >= lvl * (1 - C.LEVEL_TOUCH_PCT / 100))
            near_pct = min(C.LEVEL_NEAR_PCT, C.LEVEL_NEAR_ADR_FRAC * (r.get("adr") or 99))
            near = abs(price / lvl - 1) * 100 <= near_pct
            # failed breakdown (long) / failed breakout (short): ha passato il livello ed è tornato dall'altra parte
            failed = (float(rec.Low.min()) < lvl and price > lvl) if side == "long" else (float(rec.High.max()) > lvl and price < lvl)
            last5 = resample(b, 5, today)
            turning = len(last5) and ((float(last5.Close.iloc[-1]) > float(last5.Open.iloc[-1])) if side == "long"
                                      else (float(last5.Close.iloc[-1]) < float(last5.Open.iloc[-1])))
            if not fk and touched and near and (failed or turning) and t not in st["touched"]:
                st["touched"][t] = now.isoformat()
                tf_now = trigger_tf(mins)
                lt, lb = fmt_level(r, price, tf_now, failed, plan_entry_sl(r, b, tf_now, today))
                if r.get("counter"):
                    lb = "*Against the regime (top quality) — for information only, the bot does not take it.*\n" + lb
                msgs.append((side, lt, lb,
                             dict(ticker=t, side=side, level=lvl, tf=tf_now, title=f"at {'support' if side == 'long' else 'resistance'}")))
            key = f"{t}|{side}|trigger"
            if not touched or not near or key in st["fired"]:     # ingresso solo vicino al livello [RONIN 14/10]
                continue
            if fk and not failed:          # tracking: solo il falso breakout/breakdown sul livello [RONIN 16/10]
                continue
            tf = trigger_tf(mins)
            rb = resample(b, tf, today)
            if len(rb) < 2:
                continue
            prev, cur = rb.iloc[-2], rb.iloc[-1]
            # la rottura deve avvenire nella barra in corso; ingresso al livello di rottura (o all'apertura se c'è gap)
            if side == "long":
                if not float(cur.High) > float(prev.High):
                    continue
                price = max(float(prev.High), float(cur.Open))
            else:
                if not float(cur.Low) < float(prev.Low):
                    continue
                price = min(float(prev.Low), float(cur.Open))
            # stop: LOD/HOD, oppure l'estremo della barra di trigger se il LOD/HOD è troppo lontano
            max_stop = min(C.STOP_MAX_PCT, C.STOP_MAX_ADR_FRAC * (r.get("adr") or 99))
            stop_src = "LOD" if side == "long" else "HOD"
            if side == "long":
                stop = float(b.Low.min())
                if (price - stop) / price * 100 > max_stop:
                    stop, stop_src = float(prev.Low), f"prior {tf}m bar low"
                stop_pct = (price - stop) / price * 100
                chase = price > lvl * (1 + C.CHASE_MAX_PCT / 100)
                gap_block = False             # gap up del QQQ: si aspetta (early_reason), non si blocca la seduta [RONIN 14/10]
            else:
                stop = float(b.High.max())
                if (stop - price) / price * 100 > max_stop:
                    stop, stop_src = float(prev.High), f"prior {tf}m bar high"
                stop_pct = (stop - price) / price * 100
                chase = price < lvl * (1 - C.CHASE_MAX_PCT / 100)
                gap_block = False             # gap down del QQQ: si aspetta (early_reason), non si blocca la seduta [RONIN 15/10]
            reason = None
            if stop_pct <= 0:
                continue
            # banda d'ingresso [20/10h, Andrea]: si entra un po' prima del livello, mai sul livello o oltre
            if C.ENTRY_BAND:
                dist = (lvl / price - 1) * 100 * (1 if side == "short" else -1)
                if not (C.ENTRY_DIST_MIN_PCT <= dist <= C.ENTRY_DIST_MAX_PCT):
                    continue               # fuori banda: si aspetta, il trigger resta libero
            if C.TF_60M_TRIGGER:       # consonanza a 60m sulla EMA50 oraria [RONIN 17/10; ML: "short sulla 50 EMA 60m
                #                        allineata con la 9 daily"]: per gli short 50 oraria in discesa e prezzo non sopra
                #                        (tolleranza H60_TOL_ADR ADR, l'overshoot del livello), per i long il contrario
                hb = hourly_bars([x["ticker"] for x in focus]).get(t)
                if hb is not None and len(hb) >= 25 and C.H60_MODE == "ema9_21":   # regola del 17/10a
                    ch = hb.Close.astype(float).copy()
                    ch.iloc[-1] = price
                    e9h, e21h = float(I.ema(ch, 9).iloc[-1]), float(I.ema(ch, 21).iloc[-1])
                    if (side == "long" and e9h < e21h) or (side == "short" and e9h > e21h):
                        continue
                elif hb is not None and len(hb) >= 60:
                    ch = hb.Close.astype(float).copy()
                    ch.iloc[-1] = price            # barra oraria in corso al prezzo di adesso
                    e50, e21 = I.ema(ch, 50), I.ema(ch, 21)
                    now50, prev50 = float(e50.iloc[-1]), float(e50.iloc[-1 - C.H60_SLOPE_BARS])
                    now21, prev21 = float(e21.iloc[-1]), float(e21.iloc[-1 - C.H60_SLOPE_BARS])   # anche la 21 [RONIN 17/10]
                    tol = C.H60_TOL_ADR * (r.get("adr") or 0) / 100 * now50
                    if side == "short" and not (now50 < prev50 and now21 < prev21 and price <= now50 + tol):
                        continue           # non ancora: il trigger resta libero per le barre dopo
                    if side == "long" and not (now50 > prev50 and now21 > prev21 and price >= now50 - tol):
                        continue
            why_q = qqq_gate(side, lst.get("qqq_ctx"), bars.get("QQQ"), hourly_bars([x["ticker"] for x in focus] + ["QQQ"]).get("QQQ"))
            if why_q:                  # QQQ non conferma: si aspetta, il trigger resta libero [RONIN 20/10c, Andrea]
                continue
            # apertura: il segnale diventa un trade ombra (per misurarlo) e il trigger vero resta libero per dopo
            early = early_reason(side, mins, b, gap, lvl, r.get("adr"))
            if early:
                ekey = f"{t}|{side}|early"
                if ekey not in st["fired"]:
                    J.open_trade(dict(r, bias=lst.get("bias"), risk_pct_day=lst.get("risk_pct"), trigger_tf=f"{tf}m"),
                                 price, stop, early, today, mins)
                    st["fired"][ekey] = now.isoformat()
                continue
            if stop_pct > max_stop:
                reason = f"stop largo {stop_pct:.1f}%"
            elif chase:
                reason = "inseguimento oltre il 3% dal livello"
            elif gap_block:
                reason = f"QQQ in gap {gap:+.2f}% contro il lato"
            elif (r.get("dv5") or 0) < (C.SHORT_DV_MIN if side == "short" else C.LONG_DV_MIN):
                reason = "liquidità sotto il minimo"
            elif paused:
                reason = "pausa dopo serie di perdite"
            elif not C.ALERTS_ONLY and st["new_trades"] >= C.MAX_NEW_TRADES_DAY:
                reason = "freno: massimo trade del giorno"
            elif side == "long" and (why_g := GR.long_near_support(r, bars.get(r.get("group_etf") or ""))):
                reason = why_g             # [RONIN 28/10a] ETF del gruppo lontano dal supporto: trade ombra, niente alert
            aware = bool(r.get("counter")) and reason is None     # lato opposto: alert solo se passa tutti gli altri filtri
            if r.get("counter"):
                reason = reason or "contro regime"
            risk_day = (lst.get("risk_pct") or C.RISK_PCT) * (C.EXLEADER_RISK_MULT if r.get("short_type") == "top ex-leader" else 1)
            ctx = dict(r, bias=lst.get("bias"), risk_pct_day=risk_day, qqq_trend=(lst.get("indices", {}).get("QQQ") or {}).get("trend"),
                       iwm_trend=(lst.get("indices", {}).get("IWM") or {}).get("trend"),
                       breadth_lead=(lst.get("breadth") or {}).get("share"), trigger_tf=f"{tf}m", confluence=r.get("confluence"))
            p = J.open_trade(ctx, price, stop, reason, today, mins)
            st["fired"][key] = now.isoformat()
            if not p["shadow"] or aware:
                if not p["shadow"]:
                    st["new_trades"] += 1
                tt, tb = fmt_trigger(p, tf, stop_src, r)
                if aware:
                    tb = "*Against the regime (top quality) — for information only: the bot does not take it, it is tracked separately and not counted in the trade limit.*\n" + tb
                msgs.append((side, tt, tb,
                             dict(ticker=t, side=side, level=lvl, entry=p["entry"], stop=p["stop"], tf=tf,
                                  title=f"{('failed breakdown' if side == 'long' else 'failed breakout') if fk else 'pullback'} {side} · {tf}m trigger")))
        sent = []
        for kind, title, body, ch in msgs:
            img = img2 = None
            if ch:            # grafico daily (il pannello intraday sotto solo con ALERT_INTRADAY_PANEL) [RONIN 13/10; 28/10]
                img = alert_chart(ch["ticker"], ch["side"], bars.get(ch["ticker"]), ch.get("tf", 5), today,
                                  level=ch.get("level"), entry=ch.get("entry"), stop=ch.get("stop"),
                                  exit_px=ch.get("exit_px"), title=ch.get("title", ""), panel=C.ALERT_INTRADAY_PANEL)
                img2 = group_chart(ch["ticker"], ch["side"], focus, bars, today)
            res = send_alert(title, body, kind, dry_run, image=img, image2=img2)
            if res.get("sent"):
                sent.append(title)
            else:
                log.warning("alert non inviato: %s %s", title, res.get("reason"))
        write_atomic(state_path(today), st)
        # pausa dopo serie di perdite
        if not C.ALERTS_ONLY and J.loss_streak() >= C.LOSS_STREAK_PAUSE and not paused:
            from .calendar_us import sessions_from
            js["pause_until"] = sessions_from(today, C.PAUSE_SESSIONS + 1)[-1].isoformat()
            J.save_state(js)
    return {"minutes": None if mins is None else round(mins, 1), "focus": len(focus), "positions": len(J.positions()), "sent": sent}


def group_chart(ticker: str, side: str, focus: list[dict], bars: dict, today: date) -> Optional[bytes]:
    """Seconda immagine degli alert [RONIN 28/10, Andrea]: il daily dell'ETF del gruppo del titolo, con le sue aree di
    supporto (long) o resistenza (short)."""
    if not C.ALERT_GROUP_CHART:
        return None
    r = next((x for x in focus if x["ticker"] == ticker and x.get("group_etf")), None)
    if r is None:
        r = next((x for x in focus if x["ticker"] == ticker), None)
    etf = (r or {}).get("group_etf")
    if not etf:
        return None
    try:
        areas = [(a[0], a[1]) for a in (r.get("group_sup") or [])] if side == "long" else None
        return alert_chart(etf, side, bars.get(etf), 5, today, title=f"group ETF of {ticker} · {r.get('group')}",
                           panel=False, areas=areas)
    except Exception as e:
        log.warning("grafico ETF del gruppo %s: %s", etf, e)
        return None


def prova_alert(ticker: Optional[str] = None, dry_run: bool = False) -> dict:
    """Alert d'ingresso di PROVA (titolo 'TEST · ...'): primo Focus, un ticker, oppure 'long'/'short' (primo nome
    di quel lato tra Focus e Stalk). Barre a 5 minuti
    dell'ultima seduta: serve solo a vedere formato e grafico su Discord. Non tocca giornale né stato degli alert."""
    lst = load_list(now_et().date()) or json.loads((C.LISTS / "today.json").read_text(encoding="utf-8"))
    focus = lst.get("focus") or []
    det_p = C.LISTS / f"work_{lst.get('session')}" / "detail.json"
    cands = json.loads(det_p.read_text(encoding="utf-8")).get("candidates", []) if det_p.exists() else []
    pool = focus + [c for c in cands if c.get("level") is not None]
    want = ticker.lower() if ticker and ticker.lower() in ("long", "short") else None
    if want:                                   # "short"/"long": il primo nome di quel lato (Focus, poi Stalk)
        r = next((x for x in pool if x["side"] == want), None)
    elif ticker:
        r = next((x for x in pool if x["ticker"] == ticker.upper()), None)
    else:
        r = focus[0] if focus else None
    if r is None:
        return {"sent": False, "reason": f"nessun nome adatto nella lista ({ticker or 'Focus'})"}
    raw = D.download_intraday([r["ticker"]], period="5d", interval="5m").get(r["ticker"])
    if raw is None or not len(raw):
        return {"sent": False, "reason": "barre intraday non disponibili"}
    day = raw.index[-1].date()
    b = today_bars(raw, day)
    if len(b) < 3:
        return {"sent": False, "reason": "poche barre"}
    k = max(2, len(b) // 3)
    long = r["side"] == "long"
    if long:                                   # rottura del massimo della barra precedente, stop sul LOD
        entry, stop = float(b.High.iloc[k - 1]), float(b.Low.iloc[:k + 1].min())
        if stop >= entry:
            stop = entry * 0.99
    else:                                      # rottura del minimo della barra precedente, stop sull'HOD
        entry, stop = float(b.Low.iloc[k - 1]), float(b.High.iloc[:k + 1].max())
        if stop <= entry:
            stop = entry * 1.01
    stop_pct = abs(entry - stop) / entry * 100
    size_pct = min(C.SIZE_MAX_PCT, C.RISK_PCT / stop_pct * 100)
    p = dict(ticker=r["ticker"], side=r["side"], entry=entry, stop=stop, stop_pct=stop_pct, size_pct=size_pct,
             risk_pct=size_pct * stop_pct / 100, level=r["level"], minutes_from_open=k * 5, date_open=day.isoformat())
    title, body = fmt_trigger(p, 5, "LOD" if long else "HOD", r)
    img = alert_chart(r["ticker"], r["side"], b.iloc[:k + 1], 5, day, level=r["level"], entry=entry, stop=stop,
                      title=f"pullback {r['side']} · 5m trigger (TEST)")
    body = f"*Test message: example built on {day} bars, not a real signal.*\n" + body
    return send_alert("TEST · " + title, body, r["side"], dry_run, image=img)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prova", nargs="?", const="", help="manda un alert di PROVA: ticker, long o short (facoltativo)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--service", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-window", action="store_true")
    a = ap.parse_args(argv)
    C.LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(C.LOGS / "alerts.log")])
    if a.prova is not None:
        print(json.dumps(prova_alert(a.prova or None, a.dry_run), default=str))
        return 0
    if a.service:
        while True:
            try:
                if in_window(now_et()):
                    log.info(json.dumps(run_once(a.dry_run)))
                    time.sleep(C.POLL_SEC)
                else:
                    time.sleep(60)
            except Exception as e:
                log.exception("ciclo: %s", e)
                time.sleep(C.POLL_SEC)
    if not in_window(now_et()) and not a.force_window:
        print(json.dumps({"skipped": True, "reason": "fuori seduta"}))
        return 0
    print(json.dumps(run_once(a.dry_run), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
