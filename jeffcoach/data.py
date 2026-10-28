"""Download dati (Yahoo via yfinance): universo, industrie, daily, intraday, utili.

Ripreso da jeff-coach (stesse funzioni collaudate), adattato alle soglie di Martin.
Solo barre RTH completate per il daily, auto_adjust=False.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
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
    """Screener Yahoo: azioni USA, mcap > 1 mld, borse NMS/NYQ/ASE/NGM/NCM.
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
            if px * av < C.SCREEN_DV_PREFILTER:
                continue
            et = x.get("earningsTimestamp")
            out[x["symbol"]] = dict(
                exchange=x.get("exchange"), mcap=x.get("marketCap"), name=x.get("longName") or x.get("shortName"),
                earnings=(datetime.fromtimestamp(et, timezone.utc).date().isoformat() if et else None),
                earnings_est=bool(x.get("isEarningsDateEstimate")),
                quote_type=x.get("quoteType"))
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


# ------------------------------------------------------------------ daily
def download_daily(symbols: Iterable[str], start: str, end_inclusive: date, chunk: int = 200) -> dict[str, pd.DataFrame]:
    """Daily OHLCV auto_adjust=False fino a end_inclusive (nessuna barra successiva)."""
    yf = _yf()
    syms = sorted(set(symbols))
    end = (end_inclusive + timedelta(days=2)).isoformat()   # +2: il giorno in corso a New York resta incluso
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
            sub = sub[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
            sub = sub[sub.index.date <= end_inclusive]
            if len(sub):
                sub.index = pd.DatetimeIndex(sub.index.date)
                out[s] = sub.astype(float)
        log.info("daily %d/%d", min(i + chunk, len(syms)), len(syms))
    fill_missing_closes(out, end_inclusive)
    return {s: df for s, df in ((s, df.dropna(subset=["Close"])) for s, df in out.items()) if len(df)}


def _download_60m(syms: list[str], start: date, end: date) -> pd.DataFrame:
    return _yf().download(syms, start=start.isoformat(), end=end.isoformat(), interval="60m", auto_adjust=False,
                          prepost=False, group_by="ticker", threads=True, progress=False)


def fill_missing_closes(frames: dict[str, pd.DataFrame], end_inclusive: date, days_back: int = 7,
                        fetch=None, chunk: int = 200) -> int:
    """Barre daily di Yahoo con Open/High/Low ma senza Close [28/10: la seduta del 27/10 su quasi tutto l'universo,
    la lista del mattino era vuota]: la chiusura si prende dall'ultima barra a 60 minuti (RTH) di quel giorno, dentro
    il minimo e il massimo della barra daily. Solo le barre degli ultimi `days_back` giorni; le altre restano scartate.
    Riempie `frames` sul posto e restituisce quante chiusure ha messo."""
    first = pd.Timestamp(end_inclusive - timedelta(days=days_back))
    need = {}
    for s, df in frames.items():
        m = df.Close.isna() & df.High.notna() & df.Low.notna() & (df.index >= first)
        if m.any():
            need[s] = list(df.index[m])
    if not need:
        return 0
    fetch = fetch or _download_60m
    syms = sorted(need)
    lo = min(d for ds in need.values() for d in ds).date()
    hi = max(d for ds in need.values() for d in ds).date() + timedelta(days=1)
    filled = 0
    for i in range(0, len(syms), chunk):
        ch = syms[i:i + chunk]
        try:
            h = fetch(ch, lo, hi)
        except Exception as e:
            log.warning("barre a 60 minuti per le chiusure mancanti: %s", e)
            continue
        if h is None or h.empty:
            continue
        for s in ch:
            try:
                sub = h[s] if isinstance(h.columns, pd.MultiIndex) else h
            except KeyError:
                continue
            sub = sub.dropna(subset=["Close"])
            if not len(sub):
                continue
            ix = sub.index.tz_convert(ET) if sub.index.tz is not None else sub.index
            days = pd.Series(ix.date, index=sub.index)
            df = frames[s]
            for d in need[s]:
                bars = sub[days.values == d.date()]
                if not len(bars):
                    continue
                c = float(bars.Close.iloc[-1])
                df.loc[d, "Close"] = min(max(c, float(df.loc[d, "Low"])), float(df.loc[d, "High"]))
                filled += 1
    log.warning("Yahoo senza chiusura daily: %d titoli; chiusure prese dalle barre a 60 minuti: %d", len(need), filled)
    return filled


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


# ------------------------------------------------------------------ Market Monitor (NEL / Stockbee)
MM_FILE = C.STATE / "market_monitor.json"


def fetch_market_monitor() -> list[dict]:
    """Market Monitor di Stockbee (righe dalla più recente). Fonti in ordine [RONIN 15/10]:
    1. il Google Sheet pubblico di Stockbee, letto direttamente (stockbee.py: è la fonte da cui legge anche NEL);
    2. il file già pronto nel repo pubblico di NEL;
    3. l'archivio nel repo (data/breadth/market_monitor_nel.json), a cui ogni download riuscito si aggiunge;
    4. se manca la riga del giorno, il regime usa il calcolo nostro (breadth.own_rows) — vedi daily.build."""
    import urllib.request
    from . import breadth as B
    from . import stockbee as SB
    try:
        return B.archive_nel(SB.fetch())[:300]
    except Exception as e:
        log.warning("Market Monitor dal foglio Stockbee: %s", e)
    for url in C.MM_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "JeffCoach/1.0"})
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


# ------------------------------------------------------------------ intraday
def download_intraday(symbols: Iterable[str], period: str = "1d", interval: str = "1m",
                      prepost: bool = False) -> dict[str, pd.DataFrame]:
    """Barre intraday in ora di New York (un solo download per tutti i nomi)."""
    yf = _yf()
    syms = sorted(set(symbols))
    if not syms:
        return {}
    df = None
    for attempt in range(3):
        try:
            df = yf.download(syms, period=period, interval=interval, prepost=prepost, auto_adjust=False,
                             group_by="ticker", progress=False, threads=True)
            break
        except Exception as e:
            log.warning("intraday %s: %s", interval, e)
            time.sleep(3)
    out: dict[str, pd.DataFrame] = {}
    if df is None or df.empty:
        return out
    for s in syms:
        try:
            sub = df[s] if isinstance(df.columns, pd.MultiIndex) else df
            sub = sub[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"]).copy()
        except KeyError:
            continue
        if len(sub):
            sub.index = sub.index.tz_convert(ET)
            out[s] = sub.astype(float)
    return out


def next_earnings(symbols: Iterable[str], since: date) -> dict[str, Optional[str]]:
    """Prossima data utili (la più vicina >= since) da calendar/get_earnings_dates."""
    res = fetch_earnings(symbols, since)
    out = {}
    for t, r in res.items():
        ds = sorted(d for d in set(r.get("calendar", [])) | set(r.get("earnings_dates", [])) if d >= since.isoformat())
        out[t] = ds[0] if ds else None
    return out
