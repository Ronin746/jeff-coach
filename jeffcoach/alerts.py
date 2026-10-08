"""Alert intraday (sostituisce rth_alert_loop.py di Sydney, stesse regole e stessi messaggi).

Regole [RONIN 30/09, 04/10, 05/10]:
  - legge SOLO coach-agreed/today.json; se session_date non è la seduta di oggi non parte nulla;
  - RVOL: Focus e Stalk, una volta per nome, quando il volume RTH cumulato arriva al 30% della
    media a 50 giorni, solo nella prima ora. Non è un ingresso;
  - ingresso: SOLO Focus, dopo 30 minuti, prezzo >= massimo dei primi 30 minuti (ORH). Una volta per nome;
  - il volume si mostra e non blocca; LoD 0,7 ATR si calcola e non blocca; niente PDH nei messaggi;
  - canale [RONIN 08/10]: i nomi nella parte bassa di un canale rialzista (lettura D, "channel_watch" in today.json)
    che hanno chiuso SOTTO la SMA30 65m: un alert, una volta per nome, quando il prezzo la recupera, anche se
    è ancora sotto la EMA9 giornaliera. Non è un ingresso Focus: è un "guardalo".

Correzioni rispetto al loop precedente:
  - orari calcolati in America/New_York: funziona anche nelle settimane in cui l'apertura è alle 14:30 di Roma
    (26-30 ottobre 2026, marzo) e nei giorni di chiusura anticipata;
  - nessun gate ATR%/adv$ ricalcolato sui dati live: la lista è già filtrata e un Focus concordato non viene
    più bloccato in silenzio;
  - un solo download a ciclo per tutti i nomi (prima: 2-3 chiamate Yahoo per nome ogni 90 secondi);
  - media volume e ATR dalle sole barre daily COMPLETATE (prima la barra di oggi in corso entrava nell'ATR).

Uso:  python -m jeffcoach.alerts --loop      (dal cron, esce da solo a fine seduta)
      python -m jeffcoach.alerts --once --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd

from . import config as C
from . import indicators as I
from .calendar_us import ET, ROME, close_et, is_session, now_et, open_et
from .discord import send_alert
from .output import write_atomic

log = logging.getLogger("jeffcoach.alerts")
FIRED = C.STATE / "alerts" / "fired.json"
LAST_SCAN = C.STATE / "alerts" / "last_scan.json"


# ------------------------------------------------------------------ finestra
def minutes_from_open(now: Optional[datetime] = None) -> Optional[float]:
    n = (now or now_et()).astimezone(ET)
    if not is_session(n.date()):
        return None
    return (n - open_et(n.date())).total_seconds() / 60.0


def in_window(now: Optional[datetime] = None) -> bool:
    n = (now or now_et()).astimezone(ET)
    if not is_session(n.date()):
        return False
    return open_et(n.date()) - timedelta(minutes=5) <= n <= close_et(n.date())


# ------------------------------------------------------------------ input
_last_fetch = [0.0]


def fetch_remote_today() -> None:
    """In locale: scarica coach-agreed/today.json dal repo GitHub (JEFF_COACH_AGREED_URL), al massimo ogni 5 minuti."""
    import os
    import urllib.request
    url = os.environ.get("JEFF_COACH_AGREED_URL")
    if not url or time.time() - _last_fetch[0] < 300:
        return
    _last_fetch[0] = time.time()
    try:
        req = urllib.request.Request(f"{url}?t={int(time.time())}", headers={"User-Agent": "JeffCoach/2.0", "Cache-Control": "no-cache"})
        raw = urllib.request.urlopen(req, timeout=20).read()
        json.loads(raw)                                     # solo JSON valido
        write_atomic(C.AGREED / "today.json", raw.decode("utf-8"), as_json=False)
    except Exception as e:
        log.warning("today.json remoto non scaricato: %s", e)


def load_rows(today: date) -> list[dict]:
    fetch_remote_today()
    p = C.AGREED / "today.json"
    if not p.exists():
        log.warning("manca %s", p)
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("session_date") != today.isoformat():
        log.info("today.json è della seduta %s, non di oggi %s: nessun alert", d.get("session_date"), today)
        return []
    rows = []
    for r in d.get("tickers") or []:
        if r.get("list") in ("Focus", "Stalk") and r.get("ticker"):
            rows.append({"ticker": r["ticker"].upper(), "list": r["list"], "extreme_rvol_ok": bool(r.get("extreme_rvol_ok"))})
    return rows


def load_channel(today: date) -> list[dict]:
    p = C.AGREED / "today.json"
    if not C.CHANNEL_ALERT or not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("session_date") != today.isoformat():
        return []
    return [c for c in d.get("channel_watch") or [] if c.get("above_sma30_65m") is False and c.get("ticker")]


_chan_cache: dict = {"ts": 0.0, "bars": {}}


def live_sma30_65m(tickers: list[str], today: date) -> dict[str, dict]:
    """SMA30 65m con il bucket in corso (come TradingView): ultimi 30 close di bucket, l'ultimo = prezzo attuale.
    Un download 5m di 7 giorni per i soli nomi del canale, al massimo ogni CHANNEL_POLL_SEC."""
    import yfinance as yf
    from .data import buckets_65m
    if time.time() - _chan_cache["ts"] >= C.CHANNEL_POLL_SEC or set(tickers) - set(_chan_cache["bars"]):
        df = yf.download(tickers, period="7d", interval="5m", prepost=False, auto_adjust=False,
                         group_by="ticker", progress=False, threads=True)
        bars = {}
        for t in tickers:
            try:
                sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
                bars[t] = buckets_65m(sub)
            except Exception:
                pass
        _chan_cache.update(ts=time.time(), bars=bars)
    out = {}
    for t, b in _chan_cache["bars"].items():
        if len(b) < C.SMA65_LEN or b[-1][0] != today.isoformat():
            continue
        last = b[-C.SMA65_LEN:]
        out[t] = dict(sma=sum(x[2] for x in last) / C.SMA65_LEN, price=b[-1][2], bucket=f"{b[-1][0]}#{b[-1][1]}")
    return out


def daily_refs(tickers: list[str], today: date) -> dict[str, dict]:
    """Media volume 50gg (= sma(volume[1],50) sulla barra di oggi) e ATR14 dalle barre completate. Cache giornaliera."""
    p = C.STATE / "alerts" / f"refs_{today}.json"
    cache = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    need = [t for t in tickers if t not in cache]
    if need:
        import yfinance as yf
        df = yf.download(need, period="6mo", interval="1d", auto_adjust=False, group_by="ticker",
                         progress=False, threads=True)
        for t in need:
            try:
                sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
                sub = sub.dropna(subset=["Close"])
                sub = sub[sub.index.date < today]              # solo sedute completate
                atr = float(I.atr(sub).iloc[-1])
                cache[t] = {"avg_vol_50": float(sub.Volume.iloc[-50:].mean()),
                            "adv": float((sub.Volume * sub.Close).iloc[-50:].mean()), "atr": atr}
            except Exception as e:
                log.warning("refs %s: %s", t, e)
        write_atomic(p, cache)
    return cache


def intraday(tickers: list[str], today: date) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    df = yf.download(tickers, period="1d", interval="5m", prepost=False, auto_adjust=False,
                     group_by="ticker", progress=False, threads=True)
    out = {}
    for t in tickers:
        try:
            sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
            sub = sub.dropna(subset=["Close"]).copy()
            sub.index = sub.index.tz_convert(ET)
            sub = sub[(sub.index.date == today)]
            o = open_et(today)
            sub = sub[(sub.index >= o) & (sub.index < close_et(today))]
            if len(sub):
                out[t] = sub
        except Exception:
            pass
    return out


# ------------------------------------------------------------------ messaggi (formato invariato)
def fmt_entry(t, orh, price, rvol, rvol30):
    return f"{t} · Focus", "\n".join([
        f"30m high `{orh:.2f}`", f"Price: `{price:.2f}`",
        f"RVOL now: `{100 * rvol:.0f}%`", f"RVOL first 30m: `{'n/a' if rvol30 is None else f'{100 * rvol30:.0f}%'}`"])


def fmt_channel(c, price, sma):
    under = price <= (c.get("ema9") or 0)
    return f"{c['ticker']} · Channel", "\n".join([
        f"65m SMA30 reclaimed `{sma:.2f}`", f"Price: `{price:.2f}`",
        f"Daily EMA9: `{c['ema9']:.2f}`" + (" (still under)" if under else ""),
        (f"Broken line (backtest): `{c['upper_line_next']:.2f}`" if c["state"] == "backtest of the broken line"
         else f"Channel lower line: `{c['lower_line_next']:.2f}`"), f"Position: {c['state']}"])


def fmt_rvol(t, rvol, minutes, price):
    return f"{t} · RVOL", "\n".join([f"RVOL `{100 * rvol:.0f}%`", f"`{minutes:.0f}` minutes from the open", f"Price: `{price:.2f}`"])


# ------------------------------------------------------------------ ciclo
def run_once(dry_run: bool = False) -> dict:
    now = now_et()
    today = now.date()
    mins = minutes_from_open(now)
    rows = load_rows(today)
    if (not rows and not load_channel(today)) or mins is None or mins < 0:
        return {"scanned": 0, "minutes": mins}
    tickers = [r["ticker"] for r in rows]
    refs = daily_refs(tickers, today) if tickers else {}
    bars = intraday(tickers, today) if tickers else {}
    state = json.loads(FIRED.read_text(encoding="utf-8")) if FIRED.exists() else {}
    day = state.setdefault(today.isoformat(), {})
    fired, scan = [], []
    for r in rows:
        t, lst = r["ticker"], r["list"]
        b, ref = bars.get(t), refs.get(t)
        if b is None or not ref or not ref.get("avg_vol_50"):
            continue
        price = float(b.Close.iloc[-1])
        cum = float(b.Volume.sum())
        rvol = cum / ref["avg_vol_50"]
        first = b[b.index < open_et(today) + timedelta(minutes=C.ORH_MINUTES)]
        orh = float(first.High.max()) if len(first) else None
        rvol30 = float(first.Volume.sum()) / ref["avg_vol_50"] if len(first) and mins >= C.ORH_MINUTES else None
        lod_atr = (price - float(b.Low.min())) / ref["atr"] if ref.get("atr") else None
        rec = dict(ticker=t, list=lst, price=price, rvol=round(rvol, 3), rvol30=rvol30, orh=orh,
                   lod_atr=None if lod_atr is None else round(lod_atr, 2), lod_ok=None if lod_atr is None else lod_atr <= C.LOD_ATR_RONIN,
                   mega_liquid=(ref.get("adv") or 0) >= C.MEGA_LIQUID_ADV)
        scan.append(rec)
        # RVOL 30% nella prima ora, Focus e Stalk
        k = f"{t}|{lst}|rvol-30"
        if 0 < mins <= C.RVOL_ALERT_WINDOW_MIN and rvol >= C.RVOL_ALERT and k not in day:
            res = {"sent": True, "dry_run": True} if dry_run else send_alert(*fmt_rvol(t, rvol, mins, price))
            if res.get("sent"):
                day[k] = {"ts": datetime.now(ROME).isoformat(), "rvol": rvol, "price": price}
                fired.append(k)
        # ingresso: solo Focus, dopo 30 minuti, rottura dell'ORH
        k = f"{t}|Focus|30m-high"
        if lst != "Focus" or orh is None or k in day:
            continue
        early_ok = r["extreme_rvol_ok"] and not rec["mega_liquid"]
        if mins < C.ORH_MINUTES and not early_ok:
            continue
        if price < orh:
            continue
        if C.CHASE_MAX_ATR_ABOVE_ORH is not None and ref.get("atr") and (price - orh) / ref["atr"] > C.CHASE_MAX_ATR_ABOVE_ORH:
            rec["skipped"] = "chase"
            continue
        res = {"sent": True, "dry_run": True} if dry_run else send_alert(*fmt_entry(t, orh, price, rvol, rvol30))
        if res.get("sent"):
            day[k] = {"ts": datetime.now(ROME).isoformat(), "price": price, "orh": orh, "rvol": rvol, "lod_atr": rec["lod_atr"]}
            fired.append(k)
        else:
            log.warning("alert %s non inviato: %s", t, res.get("reason"))
    # canale: recupero della SMA30 65m (una volta per nome)
    chan = [c for c in load_channel(today) if f"{c['ticker']}|Channel|sma30-65m" not in day]
    if chan and mins >= 0:
        try:
            live = live_sma30_65m([c["ticker"] for c in chan], today)
        except Exception as e:
            log.warning("canale 65m: %s", e)
            live = {}
        for c in chan:
            t, lv = c["ticker"], live.get(c["ticker"])
            if not lv:
                continue
            scan.append(dict(ticker=t, list="Channel", price=lv["price"], sma30_65m=round(lv["sma"], 2)))
            if lv["price"] <= lv["sma"]:
                continue
            k = f"{t}|Channel|sma30-65m"
            res = {"sent": True, "dry_run": True} if dry_run else send_alert(*fmt_channel(c, lv["price"], lv["sma"]))
            if res.get("sent"):
                day[k] = {"ts": datetime.now(ROME).isoformat(), "price": lv["price"], "sma30_65m": lv["sma"]}
                fired.append(k)
    for d in [d for d in state if d < (today - timedelta(days=7)).isoformat()]:
        del state[d]
    if not dry_run:                       # una prova non deve "consumare" gli alert veri del giorno
        write_atomic(FIRED, state)
    write_atomic(LAST_SCAN, {"ts_rome": datetime.now(ROME).isoformat(), "minutes": mins, "fired": fired, "scan": scan})
    return {"scanned": len(scan), "fired": fired, "minutes": round(mins, 1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-window", action="store_true")
    a = ap.parse_args(argv)
    C.LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(C.LOGS / "alerts.log")])
    if a.loop:
        while in_window():
            try:
                log.info(json.dumps(run_once(a.dry_run)))
            except Exception as e:
                log.exception("ciclo: %s", e)
            time.sleep(C.POLL_SEC)
        log.info("fuori finestra RTH: esco")
        return 0
    if not in_window() and not a.force_window:
        print(json.dumps({"skipped": True, "reason": "fuori seduta"}))
        return 0
    print(json.dumps(run_once(a.dry_run), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
