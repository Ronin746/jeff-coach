"""Download dati (Yahoo via yfinance): universo, daily, 5 minuti, info, utili.

Regole dati [RONIN 01/10]: solo barre RTH completate, auto_adjust=False, mai premarket.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from . import config as C
from .calendar_us import ET

log = logging.getLogger("jeffcoach.data")


def _yf():
    import yfinance as yf
    return yf


def yahoo_symbol(t: str) -> str:
    return t.replace(".", "-").upper()


# ------------------------------------------------------------------ universo
UNIVERSE_FILE = C.STATE / "universe_meta.json"


def build_universe(max_age_days: int = 6, force: bool = False) -> dict[str, dict]:
    """Screener Yahoo: azioni USA, mcap > 500M, borse NMS/NYQ/ASE/NGM/NCM.
    Si rinnova se più vecchio di `max_age_days` (mcap e utili cambiano: non usare una foto ferma)."""
    if UNIVERSE_FILE.exists() and not force:
        doc = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
        age = datetime.now(timezone.utc) - datetime.fromisoformat(doc["built_utc"])
        if age < timedelta(days=max_age_days):
            return doc["symbols"]
    yf = _yf()
    from yfinance import EquityQuery as Q
    q = Q("and", [Q("eq", ["region", "us"]), Q("gt", ["intradaymarketcap", C.MCAP_MIN]),
                  Q("is-in", ["exchange", *C.EXCHANGES]), Q("gt", ["avgdailyvol3m", 50_000])])
    out: dict[str, dict] = {}
    offset, total = 0, None
    while total is None or offset < total:
        for attempt in range(4):
            try:
                r = yf.screen(q, size=250, offset=offset, sortField="intradaymarketcap", sortAsc=False)
                break
            except Exception as e:  # rete / 429
                log.warning("screen offset %s: %s", offset, e)
                time.sleep(5 * (attempt + 1))
        else:
            if UNIVERSE_FILE.exists():          # meglio l'universo della settimana prima che nessuna lista
                log.error("screener Yahoo non disponibile: uso l'universo salvato")
                return json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))["symbols"]
            raise RuntimeError("screener Yahoo non disponibile")
        total = r.get("total") or 0
        quotes = r.get("quotes") or []
        if not quotes:
            break
        for x in quotes:
            if x.get("quoteType") != "EQUITY":
                continue
            px = x.get("regularMarketPrice") or 0
            av = x.get("averageDailyVolume3Month") or 0
            if px * av < C.SCREEN_ADV_PREFILTER:
                continue
            et = x.get("earningsTimestamp")
            out[x["symbol"]] = dict(
                exchange=x.get("exchange"), mcap=x.get("marketCap"), name=x.get("longName") or x.get("shortName"),
                earnings=(datetime.fromtimestamp(et, timezone.utc).date().isoformat() if et else None),
                earnings_est=bool(x.get("isEarningsDateEstimate")))
        offset += len(quotes)
    C.STATE.mkdir(parents=True, exist_ok=True)
    tmp = UNIVERSE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"built_utc": datetime.now(timezone.utc).isoformat(), "symbols": out}), encoding="utf-8")
    tmp.replace(UNIVERSE_FILE)
    log.info("universo Yahoo: %d azioni", len(out))
    return out


INDUSTRY_FILE = C.STATE / "industry_map.json"


def build_industry_map(max_age_days: int = 6, force: bool = False) -> dict[str, dict]:
    """Settore e industria Yahoo di ogni azione dell'universo, con uno screener per industria
    (circa 150 chiamate invece di una `info` per titolo). Si rinnova con l'universo, una volta a settimana."""
    if INDUSTRY_FILE.exists() and not force:
        doc = json.loads(INDUSTRY_FILE.read_text(encoding="utf-8"))
        age = datetime.now(timezone.utc) - datetime.fromisoformat(doc["built_utc"])
        if age < timedelta(days=max_age_days):
            return doc["symbols"]
    yf = _yf()
    from yfinance import EquityQuery as Q
    groups = Q("eq", ["region", "us"]).valid_values.get("industry") or {}
    out: dict[str, dict] = {}
    failed = 0
    for sector, inds in sorted(groups.items()):
        for ind in sorted(inds):
            q = Q("and", [Q("eq", ["region", "us"]), Q("eq", ["industry", ind]),
                          Q("gt", ["intradaymarketcap", C.MCAP_MIN]), Q("is-in", ["exchange", *C.EXCHANGES])])
            offset, total = 0, None
            while total is None or offset < total:
                r = None
                for attempt in range(3):
                    try:
                        r = yf.screen(q, size=250, offset=offset, sortField="intradaymarketcap", sortAsc=False)
                        break
                    except Exception as e:
                        log.warning("industria %s: %s", ind, e)
                        time.sleep(3 * (attempt + 1))
                if r is None:
                    failed += 1
                    break
                total = r.get("total") or 0
                quotes = r.get("quotes") or []
                if not quotes:
                    break
                for x in quotes:
                    out[x["symbol"]] = {"sector": sector, "industry": ind}
                offset += len(quotes)
    if failed > 20 and INDUSTRY_FILE.exists():
        log.error("mappa industrie incompleta (%d errori): tengo quella salvata", failed)
        return json.loads(INDUSTRY_FILE.read_text(encoding="utf-8"))["symbols"]
    C.STATE.mkdir(parents=True, exist_ok=True)
    tmp = INDUSTRY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"built_utc": datetime.now(timezone.utc).isoformat(), "symbols": out}), encoding="utf-8")
    tmp.replace(INDUSTRY_FILE)
    log.info("mappa industrie: %d azioni, %d errori", len(out), failed)
    return out


def extra_symbols() -> set[str]:
    """Simboli in più da non perdere: cache daily di Remy (solo lettura) + lista del giorno prima."""
    s: set[str] = set()
    if C.REMY_DAILY_CACHE.exists():
        for p in C.REMY_DAILY_CACHE.glob("*.json"):
            s.add(p.stem.split("_", 1)[-1])
    prev = C.AGREED / "today.json"
    if prev.exists():
        try:
            s.update(t["ticker"] for t in json.loads(prev.read_text(encoding="utf-8")).get("tickers", []))
        except Exception:
            pass
    return {yahoo_symbol(x) for x in s if x and not x.startswith("^")}


# ------------------------------------------------------------------ daily
def download_daily(symbols: Iterable[str], start: str, end_inclusive: date, chunk: int = 200) -> dict[str, pd.DataFrame]:
    """Daily OHLCV auto_adjust=False fino a end_inclusive (nessuna barra successiva)."""
    yf = _yf()
    syms = sorted(set(symbols))
    end = (end_inclusive + timedelta(days=1)).isoformat()
    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(syms), chunk):
        ch = syms[i:i + chunk]
        df = None
        for attempt in range(3):
            try:
                df = yf.download(ch, start=start, end=end, interval="1d", auto_adjust=False,
                                 group_by="ticker", threads=True, progress=False)
                break
            except Exception as e:
                log.warning("daily %s: %s", i, e)
                time.sleep(5)
        if df is None or df.empty:
            continue
        for s in ch:
            try:
                sub = df[s] if isinstance(df.columns, pd.MultiIndex) else df
            except KeyError:
                continue
            sub = sub[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
            sub = sub[sub.index.date <= end_inclusive]
            if len(sub):
                sub.index = pd.DatetimeIndex(sub.index.date)
                out[s] = sub.astype(float)
        log.info("daily %d/%d", min(i + chunk, len(syms)), len(syms))
    return out


# ------------------------------------------------------------------ 65 minuti
def buckets_65m(sub: pd.DataFrame, days: Optional[set] = None) -> list[tuple]:
    """Barre 5m RTH -> bucket 65m (giorno, n. bucket, close, n. barre 5m). Il bucket in corso usa l'ultima 5m."""
    sub = sub.dropna(subset=["Close"]).copy()
    sub.index = sub.index.tz_convert(ET)
    mins = sub.index.hour * 60 + sub.index.minute - (9 * 60 + 30)
    keep = (mins >= 0) & (mins < 390)
    if days is not None:
        keep &= pd.Index([d.isoformat() in days for d in sub.index.date])
    sub = sub[keep]
    mins = sub.index.hour * 60 + sub.index.minute - (9 * 60 + 30)
    sub["d"] = [d.isoformat() for d in sub.index.date]
    sub["b"] = (mins // C.BUCKET_MIN).astype(int)
    return [(d, b, float(g.Close.iloc[-1]), len(g)) for (d, b), g in sub.groupby(["d", "b"], sort=True)]


def sma30_65m(symbols: Iterable[str], sessions: list[date], chunk: int = 60) -> dict[str, dict]:
    """SMA30 su barre a 65 minuti RTH costruite dai 5 minuti (prepost=False).
    6 bucket al giorno dalle 09:30 ET (09:30, 10:35, 11:40, 12:45, 13:50, 14:55); close del bucket =
    close dell'ultima 5m disponibile nel bucket (come TradingView). SMA = media degli ultimi 30 close."""
    yf = _yf()
    syms = sorted(set(symbols))
    want = {d.isoformat() for d in sessions}
    start = (sessions[0] - timedelta(days=1)).isoformat()
    end = (sessions[-1] + timedelta(days=1)).isoformat()
    out: dict[str, dict] = {}
    for i in range(0, len(syms), chunk):
        ch = syms[i:i + chunk]
        df = None
        for attempt in range(3):
            try:
                df = yf.download(ch, start=start, end=end, interval="5m", prepost=False, auto_adjust=False,
                                 group_by="ticker", threads=True, progress=False)
                break
            except Exception as e:
                log.warning("5m %s: %s", i, e)
                time.sleep(5)
        for s in ch:
            try:
                sub = df[s].dropna(subset=["Close"]) if df is not None else None
            except KeyError:
                sub = None
            if sub is None or sub.empty:
                out[s] = {"err": "no 5m data"}
                continue
            buckets = buckets_65m(sub, want)
            missing_days = sorted(want - {d for d, *_ in buckets})
            if len(buckets) < C.SMA65_LEN:
                out[s] = {"err": f"solo {len(buckets)} bucket 65m", "missing_days": missing_days}
                continue
            last = buckets[-C.SMA65_LEN:]
            out[s] = {"sma30_65m": sum(x[2] for x in last) / C.SMA65_LEN, "n_buckets": len(buckets),
                      "last_bucket": f"{last[-1][0]}#{last[-1][1]}", "incomplete": sum(1 for x in last if x[3] < 13),
                      "missing_days": missing_days}
        log.info("65m %d/%d", min(i + chunk, len(syms)), len(syms))
    return out


# ------------------------------------------------------------------ info e utili
def fetch_info(symbols: Iterable[str], workers: int = 10) -> dict[str, dict]:
    yf = _yf()

    def one(t):
        err = ""
        for _ in range(3):
            try:
                i = yf.Ticker(t).info or {}
                if not i.get("quoteType"):          # risposta vuota (crumb/429): non è un dato, si riprova
                    raise RuntimeError("info vuota")
                return t, {k: i.get(k) for k in ("quoteType", "marketCap", "sector", "industry", "longName", "exchange")}
            except Exception as e:
                err = str(e)[:120]
                time.sleep(3)
        return t, {"err": err}
    with ThreadPoolExecutor(workers) as ex:
        return dict(ex.map(one, sorted(set(symbols))))


def fetch_earnings(symbols: Iterable[str], since: date, workers: int = 8) -> dict[str, dict]:
    """Prossime date utili da due fonti yfinance: calendar e get_earnings_dates."""
    yf = _yf()

    def one(t):
        res = {"calendar": [], "earnings_dates": [], "past_dates": [], "errors": []}
        tk = yf.Ticker(t)
        try:
            cal = tk.calendar or {}
            res["calendar"] = sorted({str(x)[:10] for x in (cal.get("Earnings Date") or [])})
        except Exception as e:
            res["errors"].append(f"calendar: {str(e)[:80]}")
        try:
            ed = tk.get_earnings_dates(limit=8)
            if ed is not None and len(ed):
                res["earnings_dates"] = sorted({ix.date().isoformat() for ix in ed.index if ix.date() >= since})
                res["past_dates"] = sorted({ix.date().isoformat() for ix in ed.index
                                            if since - timedelta(days=120) <= ix.date() < since})   # per la lista PEG
        except Exception as e:
            res["errors"].append(f"earnings_dates: {str(e)[:80]}")
        return t, res
    with ThreadPoolExecutor(workers) as ex:
        return dict(ex.map(one, sorted(set(symbols))))
