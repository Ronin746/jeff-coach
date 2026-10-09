#!/usr/bin/env python3
"""CONFIRMED-only LONG scanner (RTH routine: yfinance cache; no TV browser).

Triggers (last fully closed 5m only; Yahoo RTH prepost=False):
  A) PRICE/VWAP CROSS — SUSPENDED; set ENABLE_VWAP_CROSS=True to re-enable.
  B) EMA 6/20 CROSS + MACD — SUSPENDED (ENABLE_DAY_MONITOR_EMA=False, 2026-10-06).
     On-demand only via day_monitor.txt (Rome calendar day). Empty/expired = no
     generic EMA6/20 alerts. Gate: EMA6>EMA20 cross + MACD bull (no SMA30 filter on day-monitor).
  C) DAILY EMA PULLBACK — SUSPENDED (ENABLE_DAILY_EMA_PULLBACK=False). EMA9+21:
     1) Daily EMAs from history ending at last COMPLETED daily close.
     2) ARM only when that RTH session opened strictly above the specific EMA,
        then sticky ≤1% pullback or session cross-down through that EMA.
     3) FIRE later same session on EMA6>EMA20 cross + MACD line>signal.
     4) If SMA30 65m is below Daily EMA9, EMA9 is skipped. Daily EMA21
        remains eligible unless the SMA30 65m pullback is also armed; when
        both are relevant, the SMA30 65m setup has priority for that ticker.
     Universe: Focus WL ∪ Sydney ranked top 50.
  D) SMA30 65m PULLBACK — SUSPENDED (ENABLE_SMA30_PULLBACK=False). Was:
     (not the old hard trend filter "price must be strictly above SMA30"):
     1) sma30 = mean of last 30 complete 65m closes (reconstructed from RTH 5m).
     2) ARM sticky for session when today's RTH open > sma30 and
        |price - sma30| / sma30 <= 0.02 on any closed RTH 5m today.
     3) FIRE later same session on EMA6>EMA20 cross + MACD line>signal.
     Universe: same Focus ∪ Sydney top 50.
  E) 30M PIVOT — ≥PIVOT30_MIN_REDS (2) consecutive same-session red 30m RTH
     candles, then first green. Drop gate: reference is prior-day close on a
     gap-down (RTH open < prior close) else today's RTH open; drop = reference −
     min low of same-day 30m bars from session open through the reds before the
     green; require drop ≥ PIVOT30_ATR_MULT (0.5) × daily ATR(14). ATR =
     Wilder/RMA on closed dailies (today forming excluded); missing ATR/ref →
     skip. Pivot high/low = green H/L. FIRE on later 5m high > pivot high;
     invalidate if 5m low < pivot low. RS gate off (2026-10-06, RS info only). Universe:
     Universe (UNIVERSE_MODE='wl323848747'): ONLY TV WL 323848747 "Main"
     (pivot_wl_323848747.txt). Flag: ENABLE_30M_PIVOT. 30m pivot = only alert.
EARLY signals disabled (delayed_streaming_900).
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

# Suspended: VWAP crosses flood Discord; flip True to restore.
ENABLE_VWAP_CROSS = False
# 30m pivot (ATR-sized red 30m run → first green; 5m break of green high). No MA/MACD gate.
ENABLE_30M_PIVOT = True
# Ronin 2026-10-05: live alerts = 30m pivot + day_monitor EMA6/20 only.
# Pullback detectors kept in code; flip True to restore Discord alerts.
ENABLE_DAILY_EMA_PULLBACK = False
ENABLE_SMA30_PULLBACK = False
# Ronin 2026-10-06: day_monitor EMA6/20 extras OFF → 30m pivot is the ONLY alert.
ENABLE_DAY_MONITOR_EMA = False
# Universe source. "wl323848747" = ONLY TradingView WL 323848747 "Main"
# (pivot_wl_323848747.txt; read-only shared on TV — never modify it there).
# "legacy" = Focus symbols.txt ∪ Sydney top50 ∪ day_monitor ∪ pivot30_list.
UNIVERSE_MODE = "wl323848747"

BASE_DIR = Path(__import__("os").environ.get("TV_SCANNER_HOME") or Path(__file__).resolve().parent)  # locale o box
CACHE_DIR = BASE_DIR / "cache"
STATE_PATH = BASE_DIR / "signal_state.json"
SIGNALS_MD = BASE_DIR / "last_signals.md"
SUMMARY_PATH = BASE_DIR / "last_scan_summary.json"
WATCHLIST_PATH = BASE_DIR / "watchlist.json"
SYMBOLS_TXT_PATH = BASE_DIR / "symbols.txt"
DAY_MONITOR_PATH = BASE_DIR / "day_monitor.txt"
PIVOT30_LIST_PATH = BASE_DIR / "pivot30_list.txt"  # legacy only (unused in wl mode)
PIVOT_WL_PATH = BASE_DIR / "pivot_wl_323848747.txt"  # TV WL 323848747 "Main" (universe)
PIVOT_WL_FOCUS_PATH = BASE_DIR / "pivot_wl_318147906.txt"  # TV WL 318147906 "Focus" (2026-10-06: both WLs)
PIVOT_WL_EXTRA_PATH = BASE_DIR / "pivot_wl_327715885.txt"  # TV WL 327715885 (Ronin 2026-10-09: aggiunta)
PIVOT_WL_PATHS = [PIVOT_WL_PATH, PIVOT_WL_FOCUS_PATH, PIVOT_WL_EXTRA_PATH]
# Tickers never scanned even if present in the WL (user cannot trade ETFs).
# sync_pivot_wl.py comments ETFs out of the WL file automatically; this is a
# manual override list (bare tickers, upper-case).
UNIVERSE_EXCLUDE: set[str] = set()
SYDNEY_RANKED_PATH = Path("/workspace/sydney-scanner/watchlist_ranked.json")
SYDNEY_TOP_N = 50

WATCHLIST_ID = "318147906"  # Remy Focus WL on TradingView
BAR_SEC = 300  # 5m
BUCKET_STARTS_ET = [(9, 30), (10, 35), (11, 40), (12, 45), (13, 50), (14, 55)]
BARS_PER_65M = 13
SMA_PERIOD = 30
EMA_FAST = 6
EMA_SLOW = 20
MACD_FAST = 6
MACD_SLOW = 20
MACD_SIGNAL = 9
DAILY_CACHE_DIR = CACHE_DIR / "daily"
# EMA50 dropped 2026-09-30 (user: mantieni solo EMA daily 9 e 21).
DAILY_EMA_PERIODS = (9, 21)
DAILY_NEAR_PCT = 0.01  # after session open > EMA: price>=ema and <=1% above
TRIGGER_DAILY_PULLBACK = "DAILY EMA PULLBACK"
# SMA30 65m pullback: session open > sma30, then |price-sma30|/sma30 <=2%.
SMA30_NEAR_PCT = 0.02
TRIGGER_SMA30_PULLBACK = "SMA30 65m PULLBACK"
BARS_PER_30M = 6  # 30m = six RTH 5m bars; anchors 09:30, 10:00, … 15:30 ET
TRIGGER_30M_PIVOT = "30M PIVOT"
MAX_30M_PIVOT_BREAKS = 3  # 1st + (2°) + (3°); no further breaks per pivot
ENABLE_30M_PIVOT_BREAK = False  # 2026-10-06 19:11 Ronin: only crossback, no alerts on pivot-high touches
RS_MIN_30M_PIVOT = None  # 2026-10-06 Ronin: no RS exclusion on WL 323848747 (RS shown as info only)
PIVOT30_MIN_REDS = 2  # consecutive same-session red 30m bars before the green
# 2026-10-07 Ronin: a gap-down open (RTH open < prior close) counts as one red
PIVOT30_GAP_DOWN_COUNTS_AS_RED = True
# 2026-10-06 (proposed, calibrated on @1ChartMaster refs NBIS/LITE/STX/MRVL/CRDO):
# drop = max(prior-day high, session high before the green) − min low before the
# green ("high_ref"); refs = 0.77–1.37×ATR → threshold 0.75. "gap_ref" = old rule
# (prior close on gap-down else RTH open; refs 0.39–1.06, CRDO fails at 0.5).
PIVOT30_DROP_MODE = "high_ref"  # "high_ref" | "gap_ref"
PIVOT30_ATR_MULT = 0.55  # drop must be >= this × daily ATR(14)
# Pivot valid only in its own ET session: no alerts on previous-day pivots
# (2026-10-06: 40/48 crosses came from 1–8 day old pivots).
PIVOT30_SAME_SESSION_ONLY = True
# Max crossback alerts per pivot (counted from the 5m EMA6/20+MACD series after
# the green, so restarts don't matter). None = unlimited.
PIVOT30_MAX_CROSSES = 1
SPX_DAILY_SYMBOL = "^GSPC"  # Yahoo SPX for RS Rating (not in scan universe)

ROME = ZoneInfo("Europe/Rome")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_unix() -> int:
    return int(time.time())


def floor_bar_open(ts: int, period: int = BAR_SEC) -> int:
    return (ts // period) * period


def last_closed_5m_open(now: Optional[int] = None) -> int:
    """Open time of the last fully closed 5m bar."""
    n = now if now is not None else now_unix()
    forming_open = floor_bar_open(n)
    return forming_open - BAR_SEC


def to_et(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=UTC).astimezone(ET)


def is_rth_5m(ts: int) -> bool:
    """True if 5m bar open is within RTH 09:30–16:00 ET (bar must start < 16:00)."""
    dt = to_et(ts)
    if dt.weekday() >= 5:
        return False
    minutes = dt.hour * 60 + dt.minute
    # RTH session bars: 09:30 inclusive through 15:55 (last 5m ending 16:00)
    return 9 * 60 + 30 <= minutes <= 15 * 60 + 55


def session_date_et(ts: int):
    return to_et(ts).date()


def bucket_start_for_bar(ts: int) -> Optional[int]:
    """Return unix open of the 65m bucket containing this RTH 5m bar, or None."""
    dt = to_et(ts)
    if not is_rth_5m(ts):
        return None
    day = dt.date()
    bar_minutes = dt.hour * 60 + dt.minute
    for h, m in BUCKET_STARTS_ET:
        start_m = h * 60 + m
        end_m = start_m + BARS_PER_65M * 5  # exclusive end in minutes from midnight
        if start_m <= bar_minutes < end_m:
            bucket_dt = datetime(day.year, day.month, day.day, h, m, tzinfo=ET)
            return int(bucket_dt.timestamp())
    return None


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

def load_watchlist(path: Path | str | dict | list | None = None) -> list[str]:
    """Load symbols from watchlist JSON / dict / list. Skip ### headers."""
    if path is None:
        path = WATCHLIST_PATH
    if isinstance(path, list):
        raw = path
    elif isinstance(path, dict):
        wl = path.get("watchlist", path)
        raw = wl.get("symbols", [])
    else:
        p = Path(path)
        data = json.loads(p.read_text())
        if isinstance(data, list):
            raw = data
        else:
            wl = data.get("watchlist", data)
            raw = wl.get("symbols", data.get("symbols", []))
    symbols = []
    for s in raw:
        if not isinstance(s, str):
            continue
        if s.startswith("###"):
            continue
        symbols.append(s)
    return symbols


def _norm_symbol(s: str) -> str:
    """Strip whitespace; accept bare TICKER or EXCHANGE:TICKER."""
    s = (s or "").strip().upper()
    if not s or s.startswith("#") or s.startswith("###"):
        return ""
    return s


def load_symbols_txt(path: Path | str | None = None) -> list[str]:
    """Focus symbols from symbols.txt (same set as watchlist.json normally)."""
    p = Path(path) if path else SYMBOLS_TXT_PATH
    if not p.exists():
        return load_watchlist()
    out: list[str] = []
    for line in p.read_text().splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith("###"):
            continue
        raw = raw.split("#", 1)[0].strip()
        if raw:
            out.append(raw)
    return list(dict.fromkeys(out))


def load_focus_symbols() -> list[str]:
    """Remy Focus watchlist (TV 318147906) via watchlist.json, else symbols.txt."""
    try:
        syms = load_watchlist(WATCHLIST_PATH)
        if syms:
            return syms
    except Exception:
        pass
    return load_symbols_txt()


def load_sydney_top(n: int = SYDNEY_TOP_N, path: Path | str | None = None) -> list[str]:
    """Top N by Sydney rank from watchlist_ranked.json (or symbols.txt fallback empty).

    Does NOT invent tickers. Missing/empty ranked file → [].
    Prefers `ranked` list ordered by rank; else first N lines of sydney symbols.txt.
    """
    p = Path(path) if path else SYDNEY_RANKED_PATH
    if p.exists():
        try:
            data = json.loads(p.read_text())
            ranked = data.get("ranked") or []
            out: list[str] = []
            for row in ranked:
                if len(out) >= n:
                    break
                sym = None
                if isinstance(row, dict):
                    sym = row.get("symbol") or row.get("ticker")
                elif isinstance(row, str):
                    sym = row
                if not sym:
                    continue
                sym = str(sym).strip()
                if not sym or sym.startswith("#"):
                    continue
                # bare ticker → leave bare (refresh strips exchange); prefer EXCHANGE:TICKER
                out.append(sym)
            return list(dict.fromkeys(out))[:n]
        except Exception:
            pass
    # Fallback: sydney symbols.txt is already ranked top-100 by build_watchlist
    alt = Path("/workspace/sydney-scanner/symbols.txt")
    if not alt.exists():
        return []
    out = []
    for line in alt.read_text().splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith("###"):
            continue
        out.append(raw.split("#", 1)[0].strip())
        if len(out) >= n:
            break
    return list(dict.fromkeys(out))


def rome_today(now: Optional[int] = None):
    """Europe/Rome calendar date for day_monitor expiry."""
    n = now if now is not None else now_unix()
    return datetime.fromtimestamp(n, tz=ROME).date()


def load_day_monitor(
    path: Path | str | None = None,
    now: Optional[int] = None,
) -> list[str]:
    """On-demand EMA6/20 day list. Valid only for stamped Rome calendar day.

    File format (`day_monitor.txt`):
      # Optional comments
      date: 2026-09-30          # or DATE=2026-09-30 / rome_date: ...
      NASDAQ:AMD
      NVDA                       # bare ticker ok

    How to set (Rome day):
      printf 'date: %s\nNASDAQ:AMD\nNVDA\n' "$(TZ=Europe/Rome date +%F)" \
        > /workspace/tv-scanner/day_monitor.txt

    Expiry: if `date:` line present and != Rome today → treat as empty (no EMA6/20).
    If no date stamp → use file mtime's Rome date; expires next Rome calendar day.
    Empty file / missing file → [].
    """
    p = Path(path) if path else DAY_MONITOR_PATH
    if not p.exists():
        return []
    text = p.read_text()
    today = rome_today(now)
    stamp = None
    symbols: list[str] = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        # Date stamp: "date: YYYY-MM-DD" or "# date: YYYY-MM-DD" (exact key, not docs)
        body = raw[1:].strip() if raw.startswith("#") else raw
        lower = body.lower()
        is_date_key = False
        for prefix in ("date:", "date=", "rome_date:", "rome_date="):
            if lower.startswith(prefix):
                is_date_key = True
                val = body.split(":" if ":" in prefix else "=", 1)[1].strip().split()[0]
                try:
                    parsed = datetime.strptime(val, "%Y-%m-%d").date()
                except ValueError:
                    parsed = None
                if parsed is not None:
                    stamp = parsed
                break
        if is_date_key:
            continue
        if raw.startswith("#"):
            continue
        sym = raw.split("#", 1)[0].strip()
        if sym:
            symbols.append(sym)

    if stamp is None:
        # fallback: mtime Rome date
        try:
            mtime = p.stat().st_mtime
            stamp = datetime.fromtimestamp(mtime, tz=ROME).date()
        except Exception:
            stamp = today

    if stamp != today:
        return []  # expired — no generic EMA6/20
    return list(dict.fromkeys(symbols))


def load_pivot_wl(path: Path | str | None = None) -> list[str]:
    """Symbols from the WL 323848747 file (one EXCHANGE:TICKER per line).

    ``#`` lines / trailing comments ignored (ETFs are written as comments by
    sync_pivot_wl.py). UNIVERSE_EXCLUDE tickers dropped. Missing file → [].
    """
    paths = [Path(path)] if path else [Path(x) for x in PIVOT_WL_PATHS]
    lines: list[str] = []
    for p in paths:
        if p.exists():
            lines.extend(p.read_text().splitlines())
    out: list[str] = []
    seen_tk: set[str] = set()
    for line in lines:
        raw = line.split("#", 1)[0].strip()
        if not raw:
            continue
        tk = raw.split(":")[-1].upper()
        if tk in UNIVERSE_EXCLUDE or tk in seen_tk:
            continue
        seen_tk.add(tk)
        out.append(raw)
    return list(dict.fromkeys(out))


def _build_wl_universe() -> dict:
    """UNIVERSE_MODE='wl323848747': WL is the ONLY universe (30m pivot only)."""
    wl = load_pivot_wl()
    return {
        "mode": UNIVERSE_MODE,
        "focus": [],
        "sydney_top50": [],
        "union": [],
        "day_monitor": [],
        "pivot30": wl,
        "fetch": list(wl),
        "counts": {
            "mode": UNIVERSE_MODE,
            "focus": 0,
            "sydney_top50": 0,
            "union": 0,
            "day_monitor": 0,
            "pivot30": len(wl),
            "fetch": len(wl),
        },
    }


def build_scan_universes(now: Optional[int] = None) -> dict:
    """Scan universes for the active UNIVERSE_MODE.

    wl323848747 (live): WL file only → pivot30 = fetch = WL; focus / sydney /
    union / day_monitor empty (symbols.txt, Sydney, day_monitor.txt and
    pivot30_list.txt are NOT read).
    legacy: Focus, Sydney top50, union (Daily EMA + SMA30), day_monitor
    (EMA6/20), pivot30_list.
    """
    if UNIVERSE_MODE == "wl323848747":
        return _build_wl_universe()
    focus = load_focus_symbols()
    sydney = load_sydney_top(SYDNEY_TOP_N)
    union = list(dict.fromkeys(focus + sydney))
    union_by_tk = {s.split(":")[-1].upper(): s for s in union}
    # Map bare day_monitor tickers onto the universe symbol (avoid scanning STX twice
    # as "STX" and "NASDAQ:STX" -> duplicate 30m pivot alerts).
    day_mon = list(dict.fromkeys(
        union_by_tk.get(s.split(":")[-1].upper(), s) for s in load_day_monitor(now=now)
    ))
    # Dua Focus+Stalk (RS 80+) list: 30m pivot only (no EMA6/20 generic, no pullbacks).
    # Same "date: YYYY-MM-DD" stamp as day_monitor; expires next Rome day.
    known = {s.split(":")[-1].upper(): s for s in union + day_mon}
    pivot_raw = load_day_monitor(path=PIVOT30_LIST_PATH, now=now)
    pivot30 = list(dict.fromkeys(known.get(s.split(":")[-1].upper(), s) for s in pivot_raw))
    # Fetch set = union ∪ day_monitor ∪ pivot30 list (warm cache for all scanned names)
    fetch = list(dict.fromkeys(union + day_mon + pivot30))
    return {
        "mode": "legacy",
        "focus": focus,
        "sydney_top50": sydney,
        "union": union,
        "day_monitor": day_mon,
        "pivot30": pivot30,
        "fetch": fetch,
        "counts": {
            "mode": "legacy",
            "focus": len(focus),
            "sydney_top50": len(sydney),
            "union": len(union),
            "day_monitor": len(day_mon),
            "pivot30": len(pivot30),
            "fetch": len(fetch),
        },
    }


# ---------------------------------------------------------------------------
# Fetch (cache populated by MCP orchestrator)
# ---------------------------------------------------------------------------

def _symbol_cache_path(symbol: str) -> Path:
    safe = symbol.replace(":", "_")
    return CACHE_DIR / f"{safe}.json"


def fetch_5m(
    symbol: str,
    count: int = 500,
    bars: Optional[list] = None,
    cache_dir: Optional[Path] = None,
) -> list[dict]:
    """Return raw 5m OHLCV bars for symbol.

    Prefer explicit `bars`. Else load from cache written by MCP orchestrator.
    Does not invent data — raises FileNotFoundError if cache missing.
    """
    if bars is not None:
        return list(bars)
    cdir = cache_dir or CACHE_DIR
    path = cdir / f"{symbol.replace(':', '_')}.json"
    if not path.exists():
        raise FileNotFoundError(f"No cached OHLCV for {symbol} at {path}")
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return data
    if "bars" in data:
        return data["bars"]
    if "data" in data and isinstance(data["data"], list):
        return data["data"]
    raise ValueError(f"Unrecognized OHLCV cache format for {symbol}")


def drop_forming_bars(bars: list[dict], now: Optional[int] = None) -> list[dict]:
    """Exclude forming 5m: drop bars with t >= floor(now/300)*300."""
    n = now if now is not None else now_unix()
    cutoff = floor_bar_open(n)
    return [b for b in bars if int(b["t"]) < cutoff]


def closed_rth_5m(bars: list[dict], now: Optional[int] = None) -> list[dict]:
    closed = drop_forming_bars(bars, now)
    return [b for b in closed if is_rth_5m(int(b["t"]))]


# ---------------------------------------------------------------------------
# Daily bars (yfinance 1d cache) + session-vs-daily-EMA pullback gate
# ---------------------------------------------------------------------------

def _symbol_daily_cache_path(symbol: str, cache_dir: Optional[Path] = None) -> Path:
    cdir = cache_dir or DAILY_CACHE_DIR
    return cdir / f"{symbol.replace(':', '_')}.json"


def fetch_daily(
    symbol: str,
    bars: Optional[list] = None,
    cache_dir: Optional[Path] = None,
) -> list[dict]:
    """Return raw daily OHLCV bars for symbol from explicit bars or cache/daily/."""
    if bars is not None:
        return list(bars)
    path = _symbol_daily_cache_path(symbol, cache_dir)
    if not path.exists():
        raise FileNotFoundError(f"No cached daily OHLCV for {symbol} at {path}")
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return data
    if "bars" in data:
        return data["bars"]
    if "data" in data and isinstance(data["data"], list):
        return data["data"]
    raise ValueError(f"Unrecognized daily OHLCV cache format for {symbol}")


def daily_session_date(ts: int):
    """US equity session date for a Yahoo 1d bar.

    yfinance daily indexes are typically midnight UTC on the session calendar
    date (e.g. 2026-09-29 00:00 UTC → session 2026-09-29), which is 20:00 ET
    the prior evening during EDT. Do NOT use ET-of-timestamp.date().
    """
    return datetime.fromtimestamp(int(ts), tz=UTC).date()


def drop_forming_daily(bars: list[dict], now: Optional[int] = None) -> list[dict]:
    """Exclude today's daily bar while RTH session is still open (before 16:00 ET).

    After 16:00 ET on a weekday, today's bar is treated as closed. Weekends keep
    the last weekday's closed daily.
    """
    n = now if now is not None else now_unix()
    dt = to_et(n)
    today = dt.date()  # US equity session calendar date
    minutes = dt.hour * 60 + dt.minute
    market_closed_today = dt.weekday() >= 5 or minutes >= 16 * 60
    out: list[dict] = []
    for b in bars:
        bday = daily_session_date(int(b["t"]))
        if bday == today and not market_closed_today:
            continue
        out.append(b)
    return out


def daily_atr14(
    daily_bars: list[dict],
    now: Optional[int] = None,
) -> Optional[float]:
    """Wilder / RMA ATR(14) on closed daily bars (excludes today's forming bar).

    True range = max(H-L, |H-prevC|, |L-prevC|). First ATR = SMA of the first
    14 TRs; then ATR = (prev_ATR * 13 + TR) / 14. Returns None if history is
    insufficient (< 15 closed dailies after drop_forming_daily).
    """
    if not daily_bars:
        return None
    closed = drop_forming_daily(
        sorted(daily_bars, key=lambda b: int(b["t"])), now=now,
    )
    if len(closed) < 15:
        return None
    trs: list[float] = []
    for i in range(1, len(closed)):
        h = float(closed[i]["h"])
        l = float(closed[i]["l"])
        pc = float(closed[i - 1]["c"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < 14:
        return None
    atr = sum(trs[:14]) / 14.0
    for tr in trs[14:]:
        atr = (atr * 13.0 + tr) / 14.0
    return float(atr)


def daily_ema_levels(
    daily_bars: list[dict],
    now: Optional[int] = None,
) -> Optional[dict]:
    """EMA9/21 of daily ``close`` matching TradingView (includes forming daily).

    TradingView updates the daily EMA with today's live/forming close during RTH.
    We keep today's Yahoo 1d bar in the series so levels match the chart (e.g.
    MPC EMA9 ≈ 404.3, not the prior-close-only ≈ 400). ``now`` is accepted for
    call-site compatibility but does not drop today's bar.
    Returns dict with emas, bar_t, close (last daily close in series), or None
    if insufficient history.
    """
    del now  # levels follow the cached daily series, including forming today
    closed = sorted(daily_bars, key=lambda b: int(b["t"]))
    need = max(DAILY_EMA_PERIODS)
    if len(closed) < need:
        return None
    closes = [float(b["c"]) for b in closed]
    series = {p: ema_series(closes, p) for p in DAILY_EMA_PERIODS}
    i = len(closes) - 1
    emas_at: dict[str, float] = {}
    for p in DAILY_EMA_PERIODS:
        e = series[p][i]
        if e is None or e == 0:
            continue
        emas_at[f"EMA{p}"] = float(e)
    if not emas_at:
        return None
    return {
        "emas": emas_at,
        "close": closes[i],
        "bar_t": int(closed[i]["t"]),
    }


def _today_rth_session_bars(
    bars_5m: Optional[list[dict]],
    now: Optional[int] = None,
) -> list[dict]:
    """Today's closed RTH 5m bars (ET session date), sorted by time."""
    if not bars_5m:
        return []
    n = now if now is not None else now_unix()
    today = to_et(n).date()
    session = [
        b for b in closed_rth_5m(bars_5m, now)
        if session_date_et(int(b["t"])) == today
    ]
    return sorted(session, key=lambda b: int(b["t"]))


def _rth_session_open_bar(session: list[dict]) -> Optional[dict]:
    """Return today's actual 09:30 ET bar, or None if it is unavailable."""
    if not session:
        return None
    first = session[0]
    dt = to_et(int(first["t"]))
    return first if (dt.hour, dt.minute) == (9, 30) else None


def _session_cross_down_from_above(session: list[dict], ema: float) -> bool:
    """True if today's RTH 5m bars show a top-down cross of fixed daily EMA.

    Evidence of coming from above then crossing/touching downward, e.g.:
      - earlier bar high/close > EMA and later bar low/close <= EMA
      - a bar opens > EMA and closes <= EMA
      - session high > EMA and last close <= EMA after having been above
    EMA level is fixed (last completed daily close); not recomputed intraday.
    """
    if not session or ema <= 0:
        return False
    ever_above = False
    for b in session:
        o = float(b["o"])
        h = float(b["h"])
        l = float(b["l"])
        c = float(b["c"])
        if h > ema or c > ema or o > ema:
            ever_above = True
        if ever_above and (l <= ema or c <= ema):
            return True
    # Session-level fallback (covers last price vs session high)
    sess_high = max(float(b["h"]) for b in session)
    last_c = float(session[-1]["c"])
    return bool(ever_above and sess_high > ema and last_c <= ema)


def daily_ema_nearness(
    daily_bars: list[dict],
    now: Optional[int] = None,
    bars_5m: Optional[list[dict]] = None,
    live_price: Optional[float] = None,
    allowed_emas: Optional[set[str]] = None,
) -> Optional[dict]:
    """Session-sticky daily EMA9/21 pullback / cross-down gate (EMA50 dropped).

    1) Daily EMA levels from the daily series including today's forming close
       (TradingView-aligned). Levels move as Yahoo's daily close updates.
    2) Gate *arms* for the current RTH session when EITHER becomes true on any
       closed RTH 5m so far today:
         (a) pullback ≤1% from above: that session's open > EMA, then bar
             close (or live_price on last bar) >= EMA and
             (price-EMA)/EMA <= 0.01, OR
         (b) session cross from above: among today's RTH 5m bars through that
             bar, evidence of coming from above then crossing/touching the EMA
             downward.
       Once armed, stays armed for the rest of the same RTH session even if
       price later leaves the 1% band (sticky). The 5m EMA6/20 cross + MACD
       fire can happen later the same session.
    3) nearest_ma is frozen at the first arm moment: closest qualifying EMA
       (min abs distance) among those that qualified on the arming bar. When
       allowed_emas is supplied, only those EMA labels are considered.
    Returns dict with keys: near (bool, sticky armed), nearest_ma (str|None),
    dist (float|None at arm), close (current session/live price), daily_close,
    emas, bar_t (daily), armed_bar_t (5m open when armed, or None) — or None if
    insufficient daily history.
    """
    levels = daily_ema_levels(daily_bars, now=now)
    if levels is None:
        return None
    emas_at: dict[str, float] = levels["emas"]

    session = _today_rth_session_bars(bars_5m, now)

    # Evaluate chronologically through today's closed RTH bars; arm once.
    armed = False
    nearest_ma: Optional[str] = None
    nearest_dist: Optional[float] = None
    armed_bar_t: Optional[int] = None
    current_price: Optional[float] = None

    def _qualify_at(price: float, session_so_far: list[dict]) -> tuple[Optional[str], Optional[float]]:
        best_ma: Optional[str] = None
        best_dist: Optional[float] = None
        best_score: Optional[float] = None
        # A pullback is valid only when this session's actual 09:30 ET bar opened
        # strictly above the specific EMA being tested. Without that bar,
        # there is no session-open evidence, so a live price alone cannot arm.
        session_open_bar = _rth_session_open_bar(session_so_far)
        if session_open_bar is None:
            return None, None
        session_open = float(session_open_bar["o"])
        for name, e in emas_at.items():
            if allowed_emas is not None and name not in allowed_emas:
                continue
            e = float(e)
            if e <= 0 or not (session_open > e):
                continue
            upper = e * (1.0 + DAILY_NEAR_PCT)
            pullback = e <= price <= upper
            cross_down = _session_cross_down_from_above(session_so_far, e)
            if not (pullback or cross_down):
                continue
            dist = (price - e) / e
            score = abs(dist)
            if best_score is None or score < best_score:
                best_score = score
                best_dist = dist
                best_ma = name
        return best_ma, best_dist

    if session:
        for i, b in enumerate(session):
            price = float(b["c"])
            if live_price is not None and i == len(session) - 1:
                price = float(live_price)
            current_price = price
            if armed:
                continue  # keep scanning only to refresh current_price
            session_so_far = session[: i + 1]
            ma, dist = _qualify_at(price, session_so_far)
            if ma is not None:
                armed = True
                nearest_ma = ma
                nearest_dist = dist
                armed_bar_t = int(b["t"])
        # current_price: prefer live override, else last session close
        if live_price is not None:
            current_price = float(live_price)
        else:
            current_price = float(session[-1]["c"])
    elif live_price is not None:
        # No closed RTH bars yet — evaluate live only (pre-arm window).
        current_price = float(live_price)
        ma, dist = _qualify_at(current_price, [])
        if ma is not None:
            armed = True
            nearest_ma = ma
            nearest_dist = dist

    return {
        "near": armed,
        "nearest_ma": nearest_ma,
        "dist": nearest_dist,
        "close": current_price,
        "daily_close": levels["close"],
        "emas": emas_at,
        "bar_t": levels["bar_t"],
        "armed_bar_t": armed_bar_t,
    }



# ---------------------------------------------------------------------------
# 65m reconstruction + SMA30
# ---------------------------------------------------------------------------

def rebuild_65m_bars(bars_5m_closed: list[dict]) -> list[dict]:
    """Rebuild complete 65m bars from closed RTH 5m bars.

    Complete only if all 13 constituents present AND bucket end <= last closed 5m end.
    """
    if not bars_5m_closed:
        return []
    by_t = {int(b["t"]): b for b in bars_5m_closed}
    last_closed_open = max(by_t)
    last_closed_end = last_closed_open + BAR_SEC

    # Collect candidate bucket starts from bars
    bucket_map: dict[int, list[dict]] = {}
    for b in bars_5m_closed:
        t = int(b["t"])
        bs = bucket_start_for_bar(t)
        if bs is None:
            continue
        bucket_map.setdefault(bs, []).append(b)

    complete = []
    for bs in sorted(bucket_map):
        constituents = sorted(bucket_map[bs], key=lambda x: int(x["t"]))
        expected = [bs + i * BAR_SEC for i in range(BARS_PER_65M)]
        got = {int(c["t"]) for c in constituents}
        if not all(e in got for e in expected):
            continue
        bucket_end = bs + BARS_PER_65M * BAR_SEC
        if bucket_end > last_closed_end:
            continue
        ordered = [by_t[e] for e in expected]
        complete.append({
            "t": bs,
            "o": float(ordered[0]["o"]),
            "h": max(float(x["h"]) for x in ordered),
            "l": min(float(x["l"]) for x in ordered),
            "c": float(ordered[-1]["c"]),
            "v": sum(float(x.get("v") or 0) for x in ordered),
        })
    return complete


def rebuild_sma30_65m(bars_5m: list[dict], now: Optional[int] = None) -> Optional[float]:
    """TradingView ``ta.sma(close, 30)`` on complete 65m bars.

    The source is the reconstructed 65m close and the window is the latest
    30 complete bars, exactly matching a rolling Pine SMA.
    """
    closed = closed_rth_5m(bars_5m, now)
    bars_65 = rebuild_65m_bars(closed)
    if len(bars_65) < SMA_PERIOD:
        return None
    closes = [b["c"] for b in bars_65[-SMA_PERIOD:]]
    return sum(closes) / SMA_PERIOD


# ---------------------------------------------------------------------------
# 30m reconstruction (RTH, anchored 09:30 ET) + 30m pivot
# ---------------------------------------------------------------------------

def bucket_start_30m(ts: int) -> Optional[int]:
    """Unix open of the 30m RTH bucket containing this 5m bar, or None.

    Buckets: 09:30–10:00, 10:00–10:30, … 15:30–16:00 ET (13 per session).
    """
    if not is_rth_5m(ts):
        return None
    dt = to_et(ts)
    day = dt.date()
    bar_minutes = dt.hour * 60 + dt.minute
    sess_start = 9 * 60 + 30
    if bar_minutes < sess_start or bar_minutes > 15 * 60 + 55:
        return None
    off = bar_minutes - sess_start
    bucket_mins = sess_start + (off // 30) * 30
    if bucket_mins > 15 * 60 + 30:
        return None
    h, m = divmod(bucket_mins, 60)
    bucket_dt = datetime(day.year, day.month, day.day, h, m, tzinfo=ET)
    return int(bucket_dt.timestamp())


def rebuild_30m_bars(bars_5m_closed: list[dict]) -> list[dict]:
    """Rebuild complete 30m RTH bars from closed RTH 5m (prepost=False cache).

    Complete only if all 6 constituents are present AND bucket end <= last
    closed 5m end. Multi-day history is preserved so patterns can span days.
    """
    if not bars_5m_closed:
        return []
    by_t = {int(b["t"]): b for b in bars_5m_closed}
    last_closed_open = max(by_t)
    last_closed_end = last_closed_open + BAR_SEC

    bucket_map: dict[int, list[dict]] = {}
    for b in bars_5m_closed:
        t = int(b["t"])
        bs = bucket_start_30m(t)
        if bs is None:
            continue
        bucket_map.setdefault(bs, []).append(b)

    complete: list[dict] = []
    for bs in sorted(bucket_map):
        expected = [bs + i * BAR_SEC for i in range(BARS_PER_30M)]
        got = {int(c["t"]) for c in bucket_map[bs]}
        if not all(e in got for e in expected):
            continue
        bucket_end = bs + BARS_PER_30M * BAR_SEC
        if bucket_end > last_closed_end:
            continue
        ordered = [by_t[e] for e in expected]
        complete.append({
            "t": bs,
            "o": float(ordered[0]["o"]),
            "h": max(float(x["h"]) for x in ordered),
            "l": min(float(x["l"]) for x in ordered),
            "c": float(ordered[-1]["c"]),
            "v": sum(float(x.get("v") or 0) for x in ordered),
        })
    return complete


def _bar_is_red(b: dict) -> bool:
    return float(b["c"]) < float(b["o"])


def _bar_is_green(b: dict) -> bool:
    return float(b["c"]) > float(b["o"])


def _30m_emas_at(bars_30m: list[dict], index: int) -> tuple[Optional[float], Optional[float]]:
    """EMA8 / EMA40 on 30m closes through ``index`` (Pine ta.ema seeding)."""
    if index < 0 or index >= len(bars_30m):
        return None, None
    closes = [float(b["c"]) for b in bars_30m[: index + 1]]
    e8 = ema_series(closes, 8)
    e40 = ema_series(closes, 40)
    return e8[index], e40[index]



def _prior_session_close(
    session_day,
    daily_bars: Optional[list[dict]],
    bars_5m: Optional[list[dict]] = None,
) -> Optional[float]:
    """Prior session close: last closed daily before ``session_day``.

    Falls back to the last RTH 5m close of any prior ET session day when daily
    history is missing.
    """
    if daily_bars:
        prior = [
            b for b in daily_bars
            if daily_session_date(int(b["t"])) < session_day
        ]
        if prior:
            prior.sort(key=lambda b: int(b["t"]))
            return float(prior[-1]["c"])
    if bars_5m:
        prior5 = [
            b for b in bars_5m
            if is_rth_5m(int(b["t"])) and _et_day(int(b["t"])) < session_day
        ]
        if prior5:
            prior5.sort(key=lambda b: int(b["t"]))
            return float(prior5[-1]["c"])
    return None


def _session_rth_open_price(
    session_day,
    bars_30: list[dict],
    bars_5m: Optional[list[dict]] = None,
) -> Optional[float]:
    """RTH open (09:30 ET) on ``session_day`` from 30m or 5m bars."""
    for b in bars_30:
        if _et_day(int(b["t"])) != session_day:
            continue
        dt = to_et(int(b["t"]))
        if (dt.hour, dt.minute) == (9, 30):
            return float(b["o"])
        break  # first same-day 30m is not 09:30 → incomplete session
    if bars_5m:
        sess = [
            b for b in bars_5m
            if is_rth_5m(int(b["t"])) and _et_day(int(b["t"])) == session_day
        ]
        if not sess:
            return None
        sess.sort(key=lambda b: int(b["t"]))
        first = sess[0]
        dt = to_et(int(first["t"]))
        if (dt.hour, dt.minute) == (9, 30):
            return float(first["o"])
    return None


def _pivot30_gap_ref_drop(
    bars_30: list[dict],
    green_idx: int,
    daily_bars: Optional[list[dict]] = None,
    bars_5m: Optional[list[dict]] = None,
) -> Optional[tuple[float, float, str, float]]:
    """Gap-aware drop for a candidate green at ``green_idx``.

    Reference: prior close if RTH open < prior close (gap_down), else RTH open
    (gap_up). Min low = lowest low of same-day 30m bars from session open
    through the bar immediately before the green (includes the red sequence).
    Returns (drop, ref, ref_kind, min_low) or None if ref/open unavailable.
    """
    if green_idx <= 0 or green_idx >= len(bars_30):
        return None
    g_day = _et_day(bars_30[green_idx]["t"])
    before = [b for b in bars_30[:green_idx] if _et_day(int(b["t"])) == g_day]
    if not before:
        return None
    min_low = min(float(b["l"]) for b in before)
    open_px = _session_rth_open_price(g_day, bars_30, bars_5m)
    prior = _prior_session_close(g_day, daily_bars, bars_5m)
    if open_px is None or prior is None:
        return None
    if open_px < prior:
        ref, kind = float(prior), "gap_down"
    else:
        ref, kind = float(open_px), "gap_up"
    return float(ref - min_low), ref, kind, float(min_low)


def _prior_session_high(
    session_day,
    daily_bars: Optional[list[dict]],
    bars_5m: Optional[list[dict]] = None,
) -> Optional[float]:
    """Prior session HIGH: last closed daily before ``session_day``.

    Fallback: max RTH 5m high of the most recent prior ET session day.
    """
    if daily_bars:
        prior = [
            b for b in daily_bars
            if daily_session_date(int(b["t"])) < session_day
        ]
        if prior:
            prior.sort(key=lambda b: int(b["t"]))
            return float(prior[-1]["h"])
    if bars_5m:
        prior5 = [
            b for b in bars_5m
            if is_rth_5m(int(b["t"])) and _et_day(int(b["t"])) < session_day
        ]
        if prior5:
            last_day = max(_et_day(int(b["t"])) for b in prior5)
            return max(float(b["h"]) for b in prior5 if _et_day(int(b["t"])) == last_day)
    return None


def _pivot30_high_ref_drop(
    bars_30: list[dict],
    green_idx: int,
    daily_bars: Optional[list[dict]] = None,
    bars_5m: Optional[list[dict]] = None,
) -> Optional[tuple[float, float, str, float]]:
    """High-ref drop: max(prior-day high, session high before green) − min low.

    Session high / min low = same-day 30m bars from the open through the bar
    before the green. Returns (drop, ref, ref_kind, min_low); ref_kind is
    ``prior_close`` (gap down) or ``session_high``. Missing data → None.
    """
    if green_idx <= 0 or green_idx >= len(bars_30):
        return None
    g_day = _et_day(bars_30[green_idx]["t"])
    before = [b for b in bars_30[:green_idx] if _et_day(int(b["t"])) == g_day]
    if not before:
        return None
    min_low = min(float(b["l"]) for b in before)
    sess_high = max(float(b["h"]) for b in before)
    # 2026-10-07 Ronin: gap down → ref = max(prior close, session high);
    # otherwise session high only (prior-day high no longer used).
    ref, kind = float(sess_high), "session_high"
    if _pivot30_gap_down(g_day, bars_30, daily_bars, bars_5m):
        prior = _prior_session_close(g_day, daily_bars, bars_5m)
        if prior is not None and float(prior) > sess_high:
            ref, kind = float(prior), "prior_close"
    return float(ref - min_low), ref, kind, float(min_low)


def _pivot30_gap_down(session_day, bars_30, daily_bars=None, bars_5m=None) -> bool:
    """True if RTH open of ``session_day`` < prior session close."""
    open_px = _session_rth_open_price(session_day, bars_30, bars_5m)
    prior = _prior_session_close(session_day, daily_bars, bars_5m)
    return open_px is not None and prior is not None and float(open_px) < float(prior)


def _pivot30_min_reds(session_day, bars_30, daily_bars=None, bars_5m=None) -> int:
    """Required same-session reds before the green (gap down counts as one red)."""
    if PIVOT30_GAP_DOWN_COUNTS_AS_RED and _pivot30_gap_down(session_day, bars_30, daily_bars, bars_5m):
        return max(1, PIVOT30_MIN_REDS - 1)
    return PIVOT30_MIN_REDS


def _pivot30_drop(
    bars_30: list[dict],
    green_idx: int,
    daily_bars: Optional[list[dict]] = None,
    bars_5m: Optional[list[dict]] = None,
) -> Optional[tuple[float, float, str, float]]:
    """Dispatch on PIVOT30_DROP_MODE ("high_ref" | "gap_ref")."""
    if PIVOT30_DROP_MODE == "gap_ref":
        return _pivot30_gap_ref_drop(bars_30, green_idx, daily_bars=daily_bars, bars_5m=bars_5m)
    return _pivot30_high_ref_drop(bars_30, green_idx, daily_bars=daily_bars, bars_5m=bars_5m)


def _pivot30_prior_cross_count(
    closed_5m: list[dict],
    green_end: int,
    last_t: int,
) -> int:
    """Crossback events (EMA6 crosses above EMA20 + MACD > signal) on closed
    RTH 5m bars with green_end <= t < last_t. Same math as compute_indicators.
    """
    rth = sorted(
        (b for b in closed_5m if is_rth_5m(int(b["t"])) and int(b["t"]) <= last_t),
        key=lambda b: int(b["t"]),
    )
    if len(rth) < 2:
        return 0
    closes = [float(b["c"]) for b in rth]
    e6 = ema_series(closes, EMA_FAST)
    e20 = ema_series(closes, EMA_SLOW)
    mf = ema_series(closes, MACD_FAST)
    ms = ema_series(closes, MACD_SLOW)
    macd = [a - b for a, b in zip(mf, ms)]
    sig = ema_series(macd, MACD_SIGNAL)
    n = 0
    for i in range(1, len(rth)):
        t = int(rth[i]["t"])
        if t < green_end or t >= last_t:
            continue
        if e6[i - 1] <= e20[i - 1] and e6[i] > e20[i] and macd[i] > sig[i]:
            n += 1
    return n


def iter_30m_pivot_events(
    bars_5m: list[dict],
    now: Optional[int] = None,
    daily_bars: Optional[list[dict]] = None,
    atr14: Optional[float] = None,
) -> list[dict]:
    """List 30m-pivot patterns over the closed RTH history (for logs / verify).

    Each event: green_t, pivot_high, pivot_low, n_reds, pivot_drop, pivot_atr,
    pivot_ref, pivot_ref_kind, breaks, invalidated, ema8_30m / ema40_30m.

    Pattern: ≥PIVOT30_MIN_REDS same-session reds, then first green same day;
    gap-ref drop (prior close on gap-down else RTH open, minus min same-day
    low before green) ≥ PIVOT30_ATR_MULT × ATR(14). Missing ATR/ref → no events.

    Breaks: first 5m high > pivot high after green; then after a closed 5m
    close < pivot high (without low < pivot low), another high > pivot high
    counts as the next alert. Unlimited until stop is hit.
    """
    atr = atr14
    if atr is None and daily_bars is not None:
        atr = daily_atr14(daily_bars, now=now)
    if atr is None or atr <= 0:
        return []
    closed = closed_rth_5m(bars_5m, now)
    if not closed:
        return []
    bars_30 = rebuild_30m_bars(closed)
    if len(bars_30) < 2:
        return []
    closed_sorted = sorted(closed, key=lambda b: int(b["t"]))
    threshold = PIVOT30_ATR_MULT * float(atr)
    events: list[dict] = []
    i = 0
    while i < len(bars_30):
        if not _bar_is_red(bars_30[i]):
            i += 1
            continue
        j = i
        day0 = _et_day(bars_30[i]["t"])
        while (
            j < len(bars_30)
            and _bar_is_red(bars_30[j])
            and _et_day(bars_30[j]["t"]) == day0
        ):
            j += 1
        n_reds = j - i
        if (
            j >= len(bars_30)
            or n_reds < _pivot30_min_reds(day0, bars_30, daily_bars, closed_sorted)
            or not _bar_is_green(bars_30[j])
            or _et_day(bars_30[j]["t"]) != day0
        ):
            i = j if j > i else i + 1
            continue
        ref_info = _pivot30_drop(
            bars_30, j, daily_bars=daily_bars, bars_5m=closed_sorted,
        )
        if ref_info is None or ref_info[0] < threshold:
            i = j if j > i else i + 1
            continue
        drop, pivot_ref, pivot_ref_kind, _min_low = ref_info
        green = bars_30[j]
        green_t = int(green["t"])
        green_end = green_t + BARS_PER_30M * BAR_SEC
        pivot_high = float(green["h"])
        pivot_low = float(green["l"])
        e8, e40 = _30m_emas_at(bars_30, j)
        breaks: list[dict] = []
        invalidated = False
        # state: "seek_break" | "seek_dip" after an alert
        state = "seek_break"
        for b5 in closed_sorted:
            t5 = int(b5["t"])
            if t5 < green_end:
                continue
            if float(b5["l"]) < pivot_low:
                invalidated = True
                break
            if state == "seek_break":
                if float(b5["h"]) > pivot_high:
                    n = len(breaks) + 1
                    if n > MAX_30M_PIVOT_BREAKS:
                        state = "capped"
                        continue
                    breaks.append({
                        "bar_t": t5,
                        "price": float(b5["c"]),
                        "alert_n": n,
                    })
                    if n >= MAX_30M_PIVOT_BREAKS:
                        state = "capped"
                    else:
                        state = "seek_break" if float(b5["c"]) < pivot_high else "seek_dip"
            elif state == "seek_dip":
                if float(b5["c"]) < pivot_high:
                    state = "seek_break"
            # state == "capped": no more break alerts for this pivot
        events.append({
            "green_t": green_t,
            "pivot_high": pivot_high,
            "pivot_low": pivot_low,
            "n_reds": n_reds,
            "pivot_drop": drop,
            "pivot_atr": float(atr),
            "pivot_ref": pivot_ref,
            "pivot_ref_kind": pivot_ref_kind,
            "breaks": breaks,
            "break_5m_t": breaks[0]["bar_t"] if breaks else None,
            "break_price": breaks[0]["price"] if breaks else None,
            "invalidated": invalidated,
            "ema8_30m": e8,
            "ema40_30m": e40,
        })
        i = j + 1
    return events


def _resolve_30m_pivot_alert(
    after_5m: list[dict],
    pivot_high: float,
    pivot_low: float,
    last_t: int,
) -> Optional[tuple[dict, int]]:
    """Walk 5m bars after green; return (break_bar, alert_n) if last_t is a fire bar.

    alert_n is 1-based, capped at MAX_30M_PIVOT_BREAKS (3). Re-breaks require a
    closed 5m close < pivot_high after the prior alert, without trading below
    pivot_low. After the 3rd break, no further break alerts for this pivot.
    """
    state = "seek_break"
    alert_n = 0
    fire_bar = None
    fire_n = None
    for b5 in after_5m:
        t5 = int(b5["t"])
        if float(b5["l"]) < pivot_low:
            return None  # pivot dead
        if state == "seek_break":
            if float(b5["h"]) > pivot_high:
                alert_n += 1
                if alert_n > MAX_30M_PIVOT_BREAKS:
                    state = "capped"
                    continue
                if t5 == last_t:
                    fire_bar = b5
                    fire_n = alert_n
                if alert_n >= MAX_30M_PIVOT_BREAKS:
                    state = "capped"
                else:
                    state = "seek_break" if float(b5["c"]) < pivot_high else "seek_dip"
        elif state == "seek_dip":
            if float(b5["c"]) < pivot_high:
                state = "seek_break"
        # state == "capped": ignore further breaks
    if fire_bar is None or fire_n is None:
        return None
    if int(fire_bar["t"]) != last_t:
        return None
    return fire_bar, fire_n


def _pivot30_stop_violated(after_5m: list[dict], pivot_low: float) -> bool:
    """True if any post-green 5m traded below pivot low (pivot dead)."""
    return any(float(b["l"]) < pivot_low for b in after_5m)


def _et_day(t: int):
    """US/Eastern calendar date of a bar open (session day for RTH 30m)."""
    return datetime.fromtimestamp(int(t), tz=ET).date()


def _find_latest_30m_pivot(
    bars_30: list[dict],
    atr14: Optional[float] = None,
    *,
    daily_bars: Optional[list[dict]] = None,
    bars_5m: Optional[list[dict]] = None,
) -> Optional[tuple[int, dict, int, float, float, float, str]]:
    """Most recent ATR-qualified 30m pivot.

    Returns (idx, green, n_reds, drop, atr, ref, ref_kind). Needs
    ≥PIVOT30_MIN_REDS consecutive same-session reds before the green. Drop per
    PIVOT30_DROP_MODE (high_ref: max(prior-day high, session high) − min low
    before green; gap_ref: prior close on gap-down else RTH open − min low).
    Require drop ≥ PIVOT30_ATR_MULT × atr14. atr14 / ref missing → None.
    """
    if atr14 is None or atr14 <= 0:
        return None
    threshold = PIVOT30_ATR_MULT * float(atr14)
    for j in range(len(bars_30) - 1, 0, -1):
        if not _bar_is_green(bars_30[j]):
            continue
        g_day = _et_day(bars_30[j]["t"])
        k = j - 1
        reds: list[dict] = []
        while k >= 0 and _bar_is_red(bars_30[k]) and _et_day(bars_30[k]["t"]) == g_day:
            reds.append(bars_30[k])
            k -= 1
        n_reds = len(reds)
        if n_reds < _pivot30_min_reds(g_day, bars_30, daily_bars, bars_5m):
            continue
        ref_info = _pivot30_drop(
            bars_30, j, daily_bars=daily_bars, bars_5m=bars_5m,
        )
        if ref_info is None:
            continue
        drop, ref, ref_kind, _min_low = ref_info
        if drop >= threshold:
            return (
                j, bars_30[j], n_reds, float(drop), float(atr14),
                float(ref), str(ref_kind),
            )
    return None


def detect_30m_pivot(
    symbol: str,
    bars_5m: list[dict],
    ind: "Indicators",
    now: Optional[int] = None,
    rs_rating: Optional[int] = None,
    min_rs: Optional[int] = None,
    daily_bars: Optional[list] = None,
) -> Optional["Signal"]:
    """30M PIVOT — break / re-break and/or EMA6/20+MACD cross while pivot active.

    Pattern: ≥PIVOT30_MIN_REDS consecutive red 30m on the same ET session day,
    then first green that same day. Drop = gap-ref − min same-day 30m low from
    session open through the reds; gap-ref = prior close if RTH open < prior
    close else RTH open. Require drop ≥ PIVOT30_ATR_MULT × daily ATR(14).
    ATR from closed dailies (today's forming excluded); missing ATR/ref → no
    alert. Pivot high/low = green H/L. While ACTIVE (stop not violated):

      (a) BREAK: later 5m high > pivot high (re-breaks after a close back
          below pivot high without hitting stop; max 3 breaks per pivot).
      (b) CROSS: EMA6 crosses above EMA20 on last closed 5m + MACD line > signal
          (same gate as day-monitor EMA 6/20; no SMA30 / day_monitor gate).

    Same bar with both → one signal, pivot_kind ``break + cross``. Stop hit
    (5m low < pivot low) kills the pivot (no further alerts). Only the most
    recent closed 5m may fire (no late-fire). EMA8/EMA40 on 30m are info-only.

    RS gate: when ``min_rs`` is set (scan path uses RS_MIN_30M_PIVOT), require
    ``rs_rating >= min_rs``; missing rating → no alert. Unit tests pass
    ``min_rs=None`` to exercise pattern logic alone (still need daily_bars/ATR).
    """
    if not ENABLE_30M_PIVOT:
        return None
    if min_rs is not None:
        if rs_rating is None or int(rs_rating) < int(min_rs):
            return None
    atr = daily_atr14(daily_bars, now=now) if daily_bars else None
    if atr is None:
        return None
    closed = closed_rth_5m(bars_5m, now)
    if not closed:
        return None
    bars_30 = rebuild_30m_bars(closed)
    if len(bars_30) < 2:
        return None

    found = _find_latest_30m_pivot(
        bars_30, atr14=atr, daily_bars=daily_bars, bars_5m=closed,
    )
    if found is None:
        return None
    green_idx, green, _n_reds, pivot_drop, pivot_atr, pivot_ref, pivot_ref_kind = found
    green_t = int(green["t"])
    green_end = green_t + BARS_PER_30M * BAR_SEC
    pivot_high = float(green["h"])
    pivot_low = float(green["l"])
    e8, e40 = _30m_emas_at(bars_30, green_idx)

    last_t = int(ind.bar_t)
    # Pivot only valid within its own ET session (no previous-day pivots).
    if PIVOT30_SAME_SESSION_ONLY and _et_day(green_t) != _et_day(last_t):
        return None
    after = [
        b for b in sorted(closed, key=lambda x: int(x["t"]))
        if green_end <= int(b["t"]) <= last_t
    ]
    if not after:
        return None
    # Pivot dead if stop violated anywhere after green through last bar.
    if _pivot30_stop_violated(after, pivot_low):
        return None

    break_resolved = (
        _resolve_30m_pivot_alert(after, pivot_high, pivot_low, last_t)
        if ENABLE_30M_PIVOT_BREAK else None
    )
    is_break = break_resolved is not None
    # Cross uses same EMA6/20 + MACD gate as detect_triggers (defined later; ok at call time).
    is_cross = _ema6_cross_up(ind) and _macd_bull(ind)
    if is_cross and PIVOT30_MAX_CROSSES is not None:
        if _pivot30_prior_cross_count(closed, green_end, last_t) >= int(PIVOT30_MAX_CROSSES):
            is_cross = False  # cap reached for this pivot

    if not is_break and not is_cross:
        return None

    if is_break and is_cross:
        kind = "break + cross"
        alert_n = int(break_resolved[1])
        price = float(break_resolved[0]["c"])
    elif is_break:
        kind = "break"
        alert_n = int(break_resolved[1])
        price = float(break_resolved[0]["c"])
    else:
        kind = "cross"
        alert_n = None
        price = float(ind.price)

    return Signal(
        symbol=symbol,
        trigger=TRIGGER_30M_PIVOT,
        price=price,
        ema6=ind.ema6,
        ema20=ind.ema20,
        vwap=ind.vwap,
        sma30_65m=None,
        macd=ind.macd,
        signal=ind.signal,
        hist=ind.hist,
        bar_t=last_t,
        nearest_daily_ma=None,
        pivot_high=pivot_high,
        pivot_low=pivot_low,
        pivot_green_t=green_t,
        pivot_alert_n=alert_n,
        pivot_kind=kind,
        ema8_30m=float(e8) if e8 is not None else None,
        ema40_30m=float(e40) if e40 is not None else None,
        rs_rating=int(rs_rating) if rs_rating is not None else None,
        pivot_drop=float(pivot_drop),
        pivot_atr=float(pivot_atr),
        pivot_ref=float(pivot_ref),
        pivot_ref_kind=str(pivot_ref_kind),
    )


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def _sma(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(closes: list[float], period: int) -> list[Optional[float]]:
    """TradingView/Pine ``ta.ema(close, period)`` for a dense close series.

    Pine seeds EMA with the first non-na source value, then applies
    ``alpha = 2 / (period + 1)`` recursively. This is intentionally different
    from an SMA-seeded textbook EMA; using the first close matches the MA
    ribbon and also lets MACD's signal EMA start on the first MACD value.
    """
    n = len(closes)
    out: list[Optional[float]] = [None] * n
    if n == 0 or period <= 0:
        return out
    k = 2.0 / (period + 1)
    prev = float(closes[0])
    out[0] = prev
    for i in range(1, n):
        prev = float(closes[i]) * k + prev * (1.0 - k)
        out[i] = prev
    return out


def session_vwap_series(bars: list[dict]) -> list[Optional[float]]:
    """Session VWAP matching TradingView Session VWAP on RTH bars only.

    Resets at each new ET calendar day (RTH open 09:30). Typical price (H+L+C)/3
    volume-weighted. Non-RTH (pre/AH) bars append None and do not accumulate —
    Yahoo extended volume is 0, so VWAP must stay RTH-only even when the 5m
    cache includes prepost bars for EMA/MACD.
    """
    out: list[Optional[float]] = []
    cum_tp_v = 0.0
    cum_v = 0.0
    cur_day = None
    for b in bars:
        t = int(b["t"])
        day = session_date_et(t)
        if day != cur_day:
            cum_tp_v = 0.0
            cum_v = 0.0
            cur_day = day
        if not is_rth_5m(t):
            out.append(None)
            continue
        h, l, c = float(b["h"]), float(b["l"]), float(b["c"])
        v = float(b.get("v") or 0)
        tp = (h + l + c) / 3.0
        cum_tp_v += tp * v
        cum_v += v
        if cum_v <= 0:
            out.append(None)
        else:
            out.append(cum_tp_v / cum_v)
    return out


@dataclass
class Indicators:
    price: float
    ema6: float
    ema20: float
    vwap: float
    macd: float
    signal: float
    hist: float
    prev_close: float
    prev_vwap: float
    prev_ema6: float
    prev_ema20: float
    bar_t: int  # open time of last closed 5m


def compute_indicators(bars_5m: list[dict], now: Optional[int] = None) -> Optional[Indicators]:
    """Compute close-based EMA6/20, MACD 6/20/9, Session VWAP on closed **RTH-only** 5m bars.

    EMA/MACD math follows TradingView/Pine ``ta.ema`` (first close seed,
    alpha ``2/(length+1)``); the MA source is always the bar close.
    Yahoo extended hours were tried then reverted (unreliable). Hard RTH filter:
      - Series excludes pre/AH bars (must not seed EMA/MACD).
      - Session VWAP resets at each RTH open (09:30 ET), typical (H+L+C)/3 × volume.
      - Crosses on last fully closed RTH 5m only (and its prior RTH bar).
    If the last fully closed 5m is not RTH, returns None.
    """
    # Hard RTH filter — never let pre/post leak into EMA/MACD/VWAP series.
    rth = closed_rth_5m(bars_5m, now)
    if len(rth) < max(EMA_SLOW + MACD_SIGNAL, 50):
        return None
    rth = sorted(rth, key=lambda b: int(b["t"]))

    closes = [float(b["c"]) for b in rth]
    ema6s = ema_series(closes, EMA_FAST)
    ema20s = ema_series(closes, EMA_SLOW)
    macd_fast = ema_series(closes, MACD_FAST)
    macd_slow = ema_series(closes, MACD_SLOW)
    macd_line = []
    for a, b in zip(macd_fast, macd_slow):
        if a is None or b is None:
            macd_line.append(None)
        else:
            macd_line.append(a - b)
    macd_vals_for_ema = []
    macd_idx_map = []
    for i, m in enumerate(macd_line):
        if m is not None:
            macd_vals_for_ema.append(m)
            macd_idx_map.append(i)
    signal_series: list[Optional[float]] = [None] * len(macd_line)
    if len(macd_vals_for_ema) >= MACD_SIGNAL:
        sig_partial = ema_series(macd_vals_for_ema, MACD_SIGNAL)
        for j, idx in enumerate(macd_idx_map):
            signal_series[idx] = sig_partial[j]

    vwaps = session_vwap_series(rth)

    i = len(rth) - 1
    last_closed_open = last_closed_5m_open(now)
    if int(rth[i]["t"]) != last_closed_open:
        if not is_rth_5m(last_closed_open):
            return None
        return None

    if i < 1:
        return None
    need = [ema6s[i], ema20s[i], ema6s[i - 1], ema20s[i - 1], vwaps[i], vwaps[i - 1],
            macd_line[i], signal_series[i]]
    if any(x is None for x in need):
        return None

    macd_v = macd_line[i]
    sig_v = signal_series[i]
    return Indicators(
        price=closes[i],
        ema6=ema6s[i],
        ema20=ema20s[i],
        vwap=vwaps[i],
        macd=macd_v,
        signal=sig_v,
        hist=macd_v - sig_v,
        prev_close=closes[i - 1],
        prev_vwap=vwaps[i - 1],
        prev_ema6=ema6s[i - 1],
        prev_ema20=ema20s[i - 1],
        bar_t=int(rth[i]["t"]),
    )


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    symbol: str
    trigger: str  # "PRICE/VWAP CROSS" | "EMA 6/20 CROSS" | "DAILY EMA PULLBACK" | "30M PIVOT"
    price: float
    ema6: float
    ema20: float
    vwap: float
    sma30_65m: Optional[float]
    macd: float
    signal: float
    hist: float
    bar_t: int
    nearest_daily_ma: Optional[str] = None
    pivot_high: Optional[float] = None
    pivot_low: Optional[float] = None
    pivot_green_t: Optional[int] = None
    pivot_alert_n: Optional[int] = None
    pivot_kind: Optional[str] = None  # "break" | "cross" | "break + cross"
    ema8_30m: Optional[float] = None
    ema40_30m: Optional[float] = None
    rs_rating: Optional[int] = None  # Fred6724 RS Rating (30m pivot gate)
    pivot_drop: Optional[float] = None  # gap-ref − min same-day low before green
    pivot_atr: Optional[float] = None  # daily ATR(14) used for the gate
    pivot_ref: Optional[float] = None  # high_ref: PDH/session high; gap_ref: prior close/open
    pivot_ref_kind: Optional[str] = None  # prior_close|session_high (high_ref) or gap_down|gap_up


def _macd_bull(ind: Indicators) -> bool:
    """MACD line > signal (chart blue above orange) on last closed 5m."""
    return ind.macd > ind.signal


def _ema6_cross_up(ind: Indicators) -> bool:
    """EMA6 crosses above EMA20 on last closed 5m vs prior RTH bar."""
    return ind.prev_ema6 <= ind.prev_ema20 and ind.ema6 > ind.ema20



def detect_triggers(
    symbol: str,
    ind: Indicators,
    sma30: Optional[float] = None,
) -> list[Signal]:
    """Day-monitor EMA6/20 (+ optional VWAP). No SMA30 gate — extras fire on cross+MACD.

    Full-Focus generic EMA6/20 is suspended — caller must only invoke this for
    symbols listed in day_monitor.txt for the current Rome calendar day.
    """
    out: list[Signal] = []
    macd_bull = _macd_bull(ind)
    sma_val = float(sma30) if sma30 is not None else 0.0

    # VWAP cross UP + MACD (SUSPENDED — ENABLE_VWAP_CROSS)
    if ENABLE_VWAP_CROSS:
        cross_vwap = ind.prev_close <= ind.prev_vwap and ind.price > ind.vwap
        if cross_vwap and macd_bull:
            out.append(Signal(
                symbol=symbol,
                trigger="PRICE/VWAP CROSS",
                price=ind.price,
                ema6=ind.ema6,
                ema20=ind.ema20,
                vwap=ind.vwap,
                sma30_65m=sma_val,
                macd=ind.macd,
                signal=ind.signal,
                hist=ind.hist,
                bar_t=ind.bar_t,
            ))

    # EMA 6/20 cross up + MACD line above signal
    if _ema6_cross_up(ind) and macd_bull:
        out.append(Signal(
            symbol=symbol,
            trigger="EMA 6/20 CROSS",
            price=ind.price,
            ema6=ind.ema6,
            ema20=ind.ema20,
            vwap=ind.vwap,
            sma30_65m=sma_val,
            macd=ind.macd,
            signal=ind.signal,
            hist=ind.hist,
            bar_t=ind.bar_t,
        ))
    return out


def daily_pullback_eligible_emas(
    daily_bars: list[dict],
    sma30: Optional[float],
    bars_5m: Optional[list] = None,
    now: Optional[int] = None,
    live_price: Optional[float] = None,
) -> Optional[set[str]]:
    """Return Daily EMA setups still eligible after the 5 MA priority rule.

    The 5 MA Daily is the reconstructed SMA30 65m setup. If its level is
    below Daily EMA9, EMA9 is never considered for this ticker. EMA21 keeps
    its normal behavior unless the 5 MA pullback is itself armed for this
    session; an armed 5 MA setup takes priority over both daily EMA setups.
    """
    levels = daily_ema_levels(daily_bars, now=now)
    if levels is None:
        return None
    eligible = set(levels.get("emas") or {})
    if sma30 is None:
        return eligible

    # An actually armed 5 MA setup takes precedence over either daily EMA,
    # including EMA21. Otherwise the level relationship only suppresses EMA9.
    sma_gate = sma30_nearness(
        float(sma30), bars_5m=bars_5m, now=now, live_price=live_price,
    )
    if sma_gate is not None and sma_gate.get("near"):
        return set()

    ema9 = levels.get("emas", {}).get("EMA9")
    if ema9 is not None and float(sma30) < float(ema9):
        eligible.discard("EMA9")
    return eligible


def detect_daily_ema_pullback(
    symbol: str,
    ind: Indicators,
    daily_bars: list[dict],
    sma30: Optional[float] = None,
    now: Optional[int] = None,
    bars_5m: Optional[list] = None,
) -> Optional[Signal]:
    """DAILY EMA PULLBACK — ARM sticky; FIRE only on EMA6/EMA20 crossback + MACD.

    Authoritative rule (ARM ≠ FIRE; never Discord on arm/touch alone):
      1) Daily EMA9/21 from daily closes including today's forming bar (TV-aligned).
      2) ARM (sticky for session) only if the session opened strictly above
         that EMA, then anytime in current RTH price is within ≤1% of it
         (price >= EMA and (price-EMA)/EMA <= 0.01), OR
         session cross from above downward through the EMA. nearest_daily_ma
         frozen at arm (closest qualifying EMA).
      3) FIRE only later same session on last CLOSED 5m when: EMA6 crosses
         ABOVE EMA20 (crossback: prev_ema6 <= prev_ema20 and ema6 > ema20) AND
         MACD line > signal — even if price left the 1% band (sticky). Do NOT
         fire on arm alone.
      4) 5 MA priority: if SMA30 65m < Daily EMA9, skip EMA9. EMA21 remains
         eligible unless the SMA30 pullback is also armed; then the 5 MA setup
         is the only daily pullback considered.
    """
    allowed_emas = daily_pullback_eligible_emas(
        daily_bars, sma30=sma30, bars_5m=bars_5m, now=now, live_price=ind.price,
    )
    if not allowed_emas:
        return None
    gate = daily_ema_nearness(
        daily_bars, now=now, bars_5m=bars_5m, live_price=ind.price,
        allowed_emas=allowed_emas,
    )
    if gate is None or not gate["near"]:
        return None
    if not _ema6_cross_up(ind):
        return None
    if not _macd_bull(ind):
        return None
    return Signal(
        symbol=symbol,
        trigger=TRIGGER_DAILY_PULLBACK,
        price=ind.price,
        ema6=ind.ema6,
        ema20=ind.ema20,
        vwap=ind.vwap,
        sma30_65m=sma30,
        macd=ind.macd,
        signal=ind.signal,
        hist=ind.hist,
        bar_t=ind.bar_t,
        nearest_daily_ma=gate.get("nearest_ma"),
    )


def sma30_nearness(
    sma30: float,
    bars_5m: Optional[list[dict]] = None,
    now: Optional[int] = None,
    live_price: Optional[float] = None,
) -> Optional[dict]:
    """Session-sticky SMA30 65m pullback gate (distance ≤ SMA30_NEAR_PCT = 2%).

    Gate math (authoritative):
      session open > sma30 (strict; required for a pullback)
      dist = (price - sma30) / sma30
      near  = abs(dist) <= 0.02
    i.e. price within 2% of SMA30 on either side — NOT the old hard filter
    `price > sma30`. Uses last closed 65m SMA30 level (fixed for the arm window
    of this scan; SMA30 itself updates when a new 65m bucket completes).

    ARM sticky for the current RTH session once today's RTH open is strictly
    above sma30 and any closed RTH 5m satisfies near. A live price alone cannot
    arm without a session-open bar. FIRE is separate (EMA6>EMA20 + MACD).
    """
    if sma30 is None or sma30 <= 0:
        return None
    session = _today_rth_session_bars(bars_5m, now)
    armed = False
    armed_dist: Optional[float] = None
    armed_bar_t: Optional[int] = None
    current_price: Optional[float] = None

    def _near(price: float) -> Optional[float]:
        # The setup is a pullback only if today's actual 09:30 ET bar opened
        # strictly above the SMA30. A live price without that session-open
        # evidence cannot arm the gate.
        session_open_bar = _rth_session_open_bar(session)
        if session_open_bar is None or not (float(session_open_bar["o"]) > sma30):
            return None
        dist = (price - sma30) / sma30
        if abs(dist) <= SMA30_NEAR_PCT:
            return dist
        return None

    if session:
        for i, b in enumerate(session):
            price = float(b["c"])
            if live_price is not None and i == len(session) - 1:
                price = float(live_price)
            current_price = price
            if armed:
                continue
            d = _near(price)
            if d is not None:
                armed = True
                armed_dist = d
                armed_bar_t = int(b["t"])
        if live_price is not None:
            current_price = float(live_price)
        else:
            current_price = float(session[-1]["c"])
    elif live_price is not None:
        current_price = float(live_price)
        d = _near(current_price)
        if d is not None:
            armed = True
            armed_dist = d

    return {
        "near": armed,
        "dist": armed_dist,
        "close": current_price,
        "sma30": float(sma30),
        "armed_bar_t": armed_bar_t,
    }


def detect_sma30_pullback(
    symbol: str,
    ind: Indicators,
    sma30: Optional[float],
    now: Optional[int] = None,
    bars_5m: Optional[list] = None,
) -> Optional[Signal]:
    """SMA30 65m PULLBACK — ARM sticky ≤2%; FIRE on EMA6>EMA20 + MACD.

    Replaces the old A/B hard trend filter (price must be strictly above SMA30)
    with a Discord-alertable pullback setup mirroring Daily EMA fire pattern:
      1) sma30 from last 30 complete 65m closes.
      2) ARM only when the RTH session open is strictly above sma30, and
         |price-sma30|/sma30 <= 0.02 anytime this RTH session (sticky).
      3) FIRE only later same session on last CLOSED 5m when EMA6 crosses ABOVE
         EMA20 AND MACD line > signal. Do NOT fire on arm/touch alone.
    """
    if sma30 is None:
        return None
    gate = sma30_nearness(sma30, bars_5m=bars_5m, now=now, live_price=ind.price)
    if gate is None or not gate["near"]:
        return None
    if not _ema6_cross_up(ind):
        return None
    if not _macd_bull(ind):
        return None
    return Signal(
        symbol=symbol,
        trigger=TRIGGER_SMA30_PULLBACK,
        price=ind.price,
        ema6=ind.ema6,
        ema20=ind.ema20,
        vwap=ind.vwap,
        sma30_65m=float(sma30),
        macd=ind.macd,
        signal=ind.signal,
        hist=ind.hist,
        bar_t=ind.bar_t,
        nearest_daily_ma=None,
    )


def signal_key(sig: Signal) -> str:
    return f"{sig.symbol}|{sig.trigger}|{sig.bar_t}"


# Historical Trigger B names (EMA5 lead era) alias to EMA 6/20 for dedup.
_TRIGGER_B_ALIASES = ("EMA 6/20 CROSS", "EMA 5/20 CROSS")
_PULLBACK_TRIGGERS = (TRIGGER_DAILY_PULLBACK, TRIGGER_SMA30_PULLBACK)


def _rome_day_for_bar(bar_t: Any) -> Optional[str]:
    """Return the Rome calendar day for a signal/state bar timestamp."""
    try:
        return datetime.fromtimestamp(int(bar_t), tz=UTC).astimezone(ROME).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _pullback_setup(sig_or_entry: Any) -> Optional[str]:
    """Return the MA/setup identity used for same-day pullback dedupe."""
    trigger = getattr(sig_or_entry, "trigger", None)
    if isinstance(sig_or_entry, dict):
        trigger = sig_or_entry.get("trigger")
    if trigger == TRIGGER_DAILY_PULLBACK:
        raw = (
            getattr(sig_or_entry, "nearest_daily_ma", None)
            if not isinstance(sig_or_entry, dict)
            else sig_or_entry.get("nearest_daily_ma")
        )
        # EMA9 and EMA 9 are the same setup; keep EMA9/EMA21 distinct.
        label = "".join(str(raw or "").upper().split())
        if label in {"9", "21"}:
            label = f"EMA{label}"
        return label or "EMA_UNSPECIFIED"
    if trigger == TRIGGER_SMA30_PULLBACK:
        return "SMA30"
    return None


def _pullback_session_key(sig: Signal) -> Optional[str]:
    """Stable ticker + MA/setup + Rome-day identity for pullback alerts."""
    setup = _pullback_setup(sig)
    day = _rome_day_for_bar(sig.bar_t)
    if setup is None or day is None:
        return None
    return f"{sig.symbol}|{sig.trigger}|{setup}|{day}"


def _same_pullback_session(emitted: dict, sig: Signal) -> bool:
    """True when this ticker/setup already emitted during this Rome day."""
    wanted = _pullback_session_key(sig)
    if wanted is None:
        return False
    wanted_setup = _pullback_setup(sig)
    wanted_day = _rome_day_for_bar(sig.bar_t)
    for key, entry in emitted.items():
        if key == wanted:
            return True
        if not isinstance(entry, dict):
            continue
        if (
            entry.get("symbol") != sig.symbol
            or entry.get("trigger") != sig.trigger
            or _pullback_setup(entry) != wanted_setup
        ):
            continue
        entry_day = entry.get("rome_session_day") or _rome_day_for_bar(entry.get("bar_t"))
        if entry_day == wanted_day:
            return True
    return False


def _pivot30_kind_has_break(kind: Optional[str]) -> bool:
    return (kind or "break") in ("break", "break + cross")


def _pivot30_kind_has_cross(kind: Optional[str]) -> bool:
    return (kind or "break") in ("cross", "break + cross")


def _pivot30_break_key(sig: Signal) -> Optional[str]:
    """Dedupe: ticker + pivot green_t + break alert_n."""
    if sig.trigger != TRIGGER_30M_PIVOT or sig.pivot_green_t is None:
        return None
    if sig.pivot_alert_n is None:
        return None
    return (
        f"{sig.symbol}|{TRIGGER_30M_PIVOT}|{int(sig.pivot_green_t)}"
        f"|break|{int(sig.pivot_alert_n)}"
    )


def _pivot30_cross_key(sig: Signal) -> Optional[str]:
    """Dedupe: ticker + pivot green_t + cross bar_t."""
    if sig.trigger != TRIGGER_30M_PIVOT or sig.pivot_green_t is None:
        return None
    return (
        f"{sig.symbol}|{TRIGGER_30M_PIVOT}|{int(sig.pivot_green_t)}"
        f"|cross|{int(sig.bar_t)}"
    )


def _pivot30_state_keys(sig: Signal) -> list[str]:
    """All state keys to persist for this 30m pivot signal."""
    keys: list[str] = []
    kind = sig.pivot_kind or "break"
    if _pivot30_kind_has_break(kind):
        bk = _pivot30_break_key(sig)
        if bk:
            keys.append(bk)
    if _pivot30_kind_has_cross(kind):
        ck = _pivot30_cross_key(sig)
        if ck:
            keys.append(ck)
    return keys


def _pivot30_key_emitted(emitted: dict, key: Optional[str]) -> bool:
    if not key:
        return False
    if key in emitted:
        return True
    return False


def refine_30m_pivot_signal(emitted: dict, sig: Signal) -> Optional[Signal]:
    """Drop already-emitted break/cross parts; merge remaining into one kind.

    Same-bar break+cross stays one row when both parts are new. If only one
    part is new, emit that kind alone. If neither is new, return None.
    """
    if sig.trigger != TRIGGER_30M_PIVOT:
        return sig
    kind = sig.pivot_kind or "break"
    want_b = _pivot30_kind_has_break(kind)
    want_c = _pivot30_kind_has_cross(kind)
    b_new = want_b and not _pivot30_key_emitted(emitted, _pivot30_break_key(sig))
    c_new = want_c and not _pivot30_key_emitted(emitted, _pivot30_cross_key(sig))
    if not b_new and not c_new:
        return None
    if b_new and c_new:
        new_kind = "break + cross"
        alert_n = sig.pivot_alert_n
    elif b_new:
        new_kind = "break"
        alert_n = sig.pivot_alert_n
    else:
        new_kind = "cross"
        alert_n = None
    if new_kind == kind and alert_n == sig.pivot_alert_n:
        return sig
    # Rebuild with refined kind (dataclass replace)
    return Signal(
        symbol=sig.symbol,
        trigger=sig.trigger,
        price=sig.price,
        ema6=sig.ema6,
        ema20=sig.ema20,
        vwap=sig.vwap,
        sma30_65m=sig.sma30_65m,
        macd=sig.macd,
        signal=sig.signal,
        hist=sig.hist,
        bar_t=sig.bar_t,
        nearest_daily_ma=sig.nearest_daily_ma,
        pivot_high=sig.pivot_high,
        pivot_low=sig.pivot_low,
        pivot_green_t=sig.pivot_green_t,
        pivot_alert_n=alert_n,
        pivot_kind=new_kind,
        ema8_30m=sig.ema8_30m,
        ema40_30m=sig.ema40_30m,
        rs_rating=sig.rs_rating,
        pivot_drop=sig.pivot_drop,
        pivot_atr=sig.pivot_atr,
        pivot_ref=sig.pivot_ref,
        pivot_ref_kind=sig.pivot_ref_kind,
    )


def _pivot30_session_key(sig: Signal) -> Optional[str]:
    """Primary persist key (first of state keys) for scan_all compatibility."""
    keys = _pivot30_state_keys(sig)
    return keys[0] if keys else None


def already_emitted(emitted: dict, sig: Signal) -> bool:
    """True if this signal is already recorded.

    EMA6/20 keeps its existing per-bar (and historical alias) dedupe. Daily
    EMA and SMA30 pullbacks are first-fire-only per ticker/setup/Rome day.
    30M PIVOT: break keys = ticker+green_t+alert_n; cross keys = ticker+green_t+bar_t.
    Use refine_30m_pivot_signal to keep partial (break xor cross) fires.
    """
    key = signal_key(sig)
    if key in emitted:
        return True
    if sig.trigger == TRIGGER_30M_PIVOT:
        refined = refine_30m_pivot_signal(emitted, sig)
        return refined is None
    if sig.trigger in _PULLBACK_TRIGGERS and _same_pullback_session(emitted, sig):
        return True
    if sig.trigger in _TRIGGER_B_ALIASES:
        for alt in _TRIGGER_B_ALIASES:
            if f"{sig.symbol}|{alt}|{sig.bar_t}" in emitted:
                return True
    return False


# ---------------------------------------------------------------------------
# State / output
# ---------------------------------------------------------------------------

def load_state(path: Path = STATE_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"emitted": {}}


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def format_signal_md(sig: Signal) -> str:
    ticker = sig.symbol.split(":")[-1] if ":" in sig.symbol else sig.symbol
    macd_str = f"{sig.macd:.4f} / {sig.signal:.4f} / {sig.hist:.4f}"
    sma_str = f"{sig.sma30_65m:.4f}" if sig.sma30_65m is not None else "n/a"
    lines = [
        f"🟢 CONFIRMED LONG — {ticker}",
        "",
        f"Trigger: {sig.trigger}",
        f"Price: {sig.price:.4f}",
        f"EMA 6: {sig.ema6:.4f}",
        f"EMA 20: {sig.ema20:.4f}",
        f"VWAP: {sig.vwap:.4f}",
        f"SMA30 65m: {sma_str}",
        f"MACD 6/20/9: {macd_str}",
    ]
    if sig.nearest_daily_ma:
        lines.append(f"Nearest daily MA: {sig.nearest_daily_ma}")
    if sig.trigger == TRIGGER_30M_PIVOT:
        if sig.pivot_kind:
            lines.append(f"Pivot kind: {sig.pivot_kind}")
        if sig.pivot_alert_n is not None:
            lines.append(f"Pivot alert #: {sig.pivot_alert_n}")
        if sig.pivot_green_t is not None:
            lines.append(f"Pivot green_t: {sig.pivot_green_t}")
        if sig.pivot_high is not None and sig.pivot_low is not None:
            lines.append(f"Pivot high/low: {sig.pivot_high:.4f} / {sig.pivot_low:.4f}")
        if sig.pivot_drop is not None and sig.pivot_atr is not None:
            ref_s = ""
            if sig.pivot_ref is not None and sig.pivot_ref_kind:
                ref_s = f" ref={sig.pivot_ref:.4f}({sig.pivot_ref_kind})"
            lines.append(
                f"Pivot drop/ATR: {sig.pivot_drop:.4f} / {sig.pivot_atr:.4f} "
                f"(×{sig.pivot_drop / sig.pivot_atr:.2f}){ref_s}"
            )
        if sig.ema8_30m is not None:
            lines.append(f"EMA8 30m: {sig.ema8_30m:.4f}")
        if sig.ema40_30m is not None:
            lines.append(f"EMA40 30m: {sig.ema40_30m:.4f}")
        if sig.rs_rating is not None:
            lines.append(f"RS Rating: {sig.rs_rating}")
    lines.extend(["", "Status: CONFIRMED", "5m candle: CLOSED", ""])
    return "\n".join(lines)


def append_signals_md(signals: list[Signal], path: Path = SIGNALS_MD) -> None:
    if not signals:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    block = "\n".join(format_signal_md(s) for s in signals)
    with path.open("a") as f:
        if path.exists() and path.stat().st_size > 0:
            f.write("\n")
        f.write(block)
        if not block.endswith("\n"):
            f.write("\n")


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def scan_symbol(
    symbol: str,
    bars: Optional[list] = None,
    now: Optional[int] = None,
    daily_bars: Optional[list] = None,
    enable_ema_cross: bool = False,
    enable_daily_pullback: bool = True,
    enable_sma30_pullback: bool = True,
    enable_30m_pivot: bool = True,
) -> tuple[list[Signal], Optional[str]]:
    """Returns (signals, skip_or_error_reason).

    enable_ema_cross: day_monitor only (generic Focus EMA6/20 suspended).
    enable_daily_pullback / enable_sma30_pullback: Focus ∪ Sydney top50.
    enable_30m_pivot: Focus ∪ Sydney top50 ∪ day_monitor (gated by ENABLE_30M_PIVOT).
    """
    try:
        raw = fetch_5m(symbol, bars=bars)
    except Exception as e:
        return [], f"fetch_error:{e}"
    if not raw:
        return [], "empty_bars"
    ind = compute_indicators(raw, now)
    if ind is None:
        return [], "indicators_unavailable"

    sma = rebuild_sma30_65m(raw, now)
    out: list[Signal] = []

    # B: day-monitor EMA6/20 only — cross + MACD, no SMA30 gate
    if enable_ema_cross and ENABLE_DAY_MONITOR_EMA:
        out.extend(detect_triggers(symbol, ind, sma))

    # C: Daily EMA 9/21 pullback (master flag ENABLE_DAILY_EMA_PULLBACK).
    # Detector still applies 5 MA priority when re-enabled.
    d_bars = daily_bars
    if enable_daily_pullback and ENABLE_DAILY_EMA_PULLBACK:
        if d_bars is None:
            try:
                d_bars = fetch_daily(symbol)
            except Exception:
                d_bars = None
        if d_bars:
            pb = detect_daily_ema_pullback(
                symbol, ind, d_bars, sma30=sma, now=now, bars_5m=raw,
            )
            if pb is not None:
                out.append(pb)

    # D: SMA30 65m ≤2% pullback (master flag ENABLE_SMA30_PULLBACK)
    if enable_sma30_pullback and ENABLE_SMA30_PULLBACK and sma is not None:
        sp = detect_sma30_pullback(symbol, ind, sma, now=now, bars_5m=raw)
        if sp is not None:
            out.append(sp)

    # E: 30m pivot (ATR-sized red run → green; 5m break of green high) + RS >= 80
    if ENABLE_30M_PIVOT and enable_30m_pivot:
        rs_val: Optional[int] = None
        try:
            from rs_rating import compute_rs_rating
            if d_bars is None:
                try:
                    d_bars = fetch_daily(symbol)
                except Exception:
                    d_bars = None
            rs_val = compute_rs_rating(symbol, daily_bars=d_bars, now=now)
        except Exception as e:
            print(f"[rs_rating] {symbol}: compute error {type(e).__name__}: {e}")
            rs_val = None
        if rs_val is None:
            print(f"[rs_rating] {symbol}: missing/insufficient daily data — RS n/a (info only)")
        if True:
            p30 = detect_30m_pivot(
                symbol, raw, ind, now=now,
                rs_rating=rs_val, min_rs=RS_MIN_30M_PIVOT,
                daily_bars=d_bars,
            )
            if p30 is not None:
                out.append(p30)

    if (
        not out and sma is None
        and enable_sma30_pullback and ENABLE_SMA30_PULLBACK
        and not (enable_daily_pullback and ENABLE_DAILY_EMA_PULLBACK)
    ):
        closed = closed_rth_5m(raw, now)
        n65 = len(rebuild_65m_bars(closed))
        return [], f"insufficient_65m:{n65}"

    if (
        not out and sma is None
        and enable_daily_pullback and ENABLE_DAILY_EMA_PULLBACK
        and d_bars is None and not enable_ema_cross
    ):
        closed = closed_rth_5m(raw, now)
        n65 = len(rebuild_65m_bars(closed))
        return [], f"insufficient_65m:{n65}"

    return out, None


def scan_all(
    symbols: Optional[list[str]] = None,
    now: Optional[int] = None,
    state: Optional[dict] = None,
    bars_by_symbol: Optional[dict[str, list]] = None,
    daily_bars_by_symbol: Optional[dict[str, list]] = None,
    state_path: Optional[Path] = None,
    summary_path: Optional[Path] = None,
    persist_signals_md: bool = True,
    dry_run: bool = False,
    universes: Optional[dict] = None,
) -> dict:
    """Scan universes. Persist new signals; skip duplicates via state.

    If `symbols` is None, builds Focus ∪ Sydney top50 ∪ day_monitor.
    Per-symbol triggers:
      - day_monitor (Rome today): EMA 6/20 (+ legacy price>SMA30) [+ VWAP if enabled]
      - Focus ∪ Sydney top50: Daily EMA / SMA30 pullbacks gated by
        ENABLE_DAILY_EMA_PULLBACK / ENABLE_SMA30_PULLBACK (both False live)
    EMA6/20 keeps per-bar dedupe; Daily EMA/SMA30 are first-fire per ticker+setup/Rome day;
    30M PIVOT: break dedupe ticker+green_t+n; cross dedupe ticker+green_t+bar_t; cross while active (EMA6/20+MACD, no day_monitor/SMA30). Silent Discord if no NEW.
    dry_run: compute signals but do not Discord / do not mutate signal_state or md
      (still writes summary with dry_run flag). When dry_run and no prior state
      mutation desired, pass a throwaway state dict.
    """
    uni = universes or build_scan_universes(now=now)
    day_set = set(uni.get("day_monitor") or [])
    pullback_set = set(uni.get("union") or [])
    pivot30_set = set(uni.get("pivot30") or [])

    if symbols is None:
        symbols = list(dict.fromkeys(
            list(uni.get("union") or [])
            + list(uni.get("day_monitor") or [])
            + list(uni.get("pivot30") or [])
        ))

    if state is None:
        state = load_state() if not dry_run else {"emitted": {}}
    emitted = state.setdefault("emitted", {})

    scanned = 0
    skipped = []
    errors = []
    new_signals: list[Signal] = []

    for sym in symbols:
        bars = None
        if bars_by_symbol and sym in bars_by_symbol:
            bars = bars_by_symbol[sym]
        d_bars = None
        if daily_bars_by_symbol and sym in daily_bars_by_symbol:
            d_bars = daily_bars_by_symbol[sym]
        in_day = sym in day_set
        in_pb = sym in pullback_set
        # If caller passed an explicit symbols list without universes context,
        # default pullbacks on (union semantics) and EMA only if in day_set.
        if universes is None and symbols is not None and not pullback_set:
            in_pb = True
        # 30m pivot: same fetch universe (Focus ∪ Sydney top50 ∪ day_monitor)
        in_30m = in_pb or in_day or (sym in pivot30_set) or (universes is None)
        sigs, reason = scan_symbol(
            sym,
            bars=bars,
            now=now,
            daily_bars=d_bars,
            enable_ema_cross=in_day and ENABLE_DAY_MONITOR_EMA,
            enable_daily_pullback=in_pb and ENABLE_DAILY_EMA_PULLBACK,
            enable_sma30_pullback=in_pb and ENABLE_SMA30_PULLBACK,
            enable_30m_pivot=in_30m,
        )
        if reason:
            if reason.startswith("fetch_error") or reason.startswith("empty"):
                errors.append({"symbol": sym, "error": reason})
            else:
                skipped.append({"symbol": sym, "reason": reason})
            continue
        scanned += 1
        for sig in sigs:
            if sig.trigger == TRIGGER_30M_PIVOT:
                refined = refine_30m_pivot_signal(emitted, sig)
                if refined is None:
                    continue
                sig = refined
            elif already_emitted(emitted, sig):
                continue
            # Persist pullbacks under ticker/setup/Rome-day; 30M PIVOT under
            # break and/or cross keys; else per-bar key for EMA6/20.
            entry = {
                "symbol": sig.symbol,
                "trigger": sig.trigger,
                "bar_t": sig.bar_t,
                "price": sig.price,
                "ts_emitted": now_unix(),
            }
            if sig.nearest_daily_ma:
                entry["nearest_daily_ma"] = sig.nearest_daily_ma
            if sig.pivot_high is not None:
                entry["pivot_high"] = sig.pivot_high
            if sig.pivot_low is not None:
                entry["pivot_low"] = sig.pivot_low
            if sig.pivot_green_t is not None:
                entry["pivot_green_t"] = sig.pivot_green_t
            if sig.pivot_alert_n is not None:
                entry["pivot_alert_n"] = sig.pivot_alert_n
            if sig.pivot_kind:
                entry["pivot_kind"] = sig.pivot_kind
            if sig.rs_rating is not None:
                entry["rs_rating"] = sig.rs_rating
            if sig.pivot_drop is not None:
                entry["pivot_drop"] = sig.pivot_drop
            if sig.pivot_atr is not None:
                entry["pivot_atr"] = sig.pivot_atr
            if sig.pivot_ref is not None:
                entry["pivot_ref"] = sig.pivot_ref
            if sig.pivot_ref_kind:
                entry["pivot_ref_kind"] = sig.pivot_ref_kind
            if sig.trigger == TRIGGER_30M_PIVOT:
                keys = _pivot30_state_keys(sig)
            else:
                keys = [
                    _pullback_session_key(sig) or signal_key(sig)
                ]
            if not dry_run:
                for key in keys:
                    emitted[key] = entry
            new_signals.append(sig)

    if new_signals and not dry_run:
        if persist_signals_md:
            append_signals_md(new_signals)
        try:
            from discord_notify import send_discord
            discord_result = send_discord(new_signals)
        except Exception as e:
            discord_result = {"sent": False, "reason": f"discord_error:{e}"}
    elif new_signals and dry_run:
        try:
            from discord_notify import send_discord
            discord_result = send_discord(new_signals, dry_run=True)
        except Exception as e:
            discord_result = {"sent": False, "reason": f"discord_dry_run_error:{e}"}
    else:
        discord_result = {"sent": False, "reason": "no_signals"}

    if not dry_run:
        save_state(state, path=state_path or STATE_PATH)

    latency_sec = None
    if new_signals:
        close_t = max(int(s.bar_t) for s in new_signals) + 300
        latency_sec = round(now_unix() - close_t, 1)

    summary = {
        "timestamp": datetime.now(tz=ET).isoformat(),
        "rome_date": str(rome_today(now)),
        "universes": uni.get("counts"),
        "day_monitor": list(uni.get("day_monitor") or []),
        "symbols_scanned": scanned,
        "symbols_skipped": skipped,
        "new_signals": [
            {
                "symbol": s.symbol,
                "trigger": s.trigger,
                "bar_t": s.bar_t,
                "price": s.price,
                **({"nearest_daily_ma": s.nearest_daily_ma} if s.nearest_daily_ma else {}),
                **({"pivot_high": s.pivot_high} if s.pivot_high is not None else {}),
                **({"pivot_low": s.pivot_low} if s.pivot_low is not None else {}),
                **({"pivot_green_t": s.pivot_green_t} if s.pivot_green_t is not None else {}),
                **({"pivot_alert_n": s.pivot_alert_n} if s.pivot_alert_n is not None else {}),
                **({"pivot_kind": s.pivot_kind} if s.pivot_kind else {}),
                **({"rs_rating": s.rs_rating} if s.rs_rating is not None else {}),
                **({"pivot_drop": s.pivot_drop} if s.pivot_drop is not None else {}),
                **({"pivot_atr": s.pivot_atr} if s.pivot_atr is not None else {}),
                **({"pivot_ref": s.pivot_ref} if s.pivot_ref is not None else {}),
                **({"pivot_ref_kind": s.pivot_ref_kind} if s.pivot_ref_kind else {}),
            }
            for s in new_signals
        ],
        "errors": errors,
        "discord": discord_result,
        "latency_sec_after_close": latency_sec,
        "dry_run": dry_run,
        "note": (
            f"30M PIVOT ONLY on {uni.get('mode', UNIVERSE_MODE)} universe "
            f"(RS gate={RS_MIN_30M_PIVOT}); day_monitor EMA6/20="
            f"{'on' if ENABLE_DAY_MONITOR_EMA else 'off'}; Daily EMA / SMA30 pullbacks="
            f"{'on' if (ENABLE_DAILY_EMA_PULLBACK or ENABLE_SMA30_PULLBACK) else 'off'}; "
            f"VWAP={'on' if ENABLE_VWAP_CROSS else 'off'}"
        ),
    }
    (summary_path or SUMMARY_PATH).write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="CONFIRMED LONG scanner: 30M PIVOT only on TV WL 323848747 "
        "(UNIVERSE_MODE); day_monitor EMA6/20, Daily/SMA30 pullbacks, VWAP off. "
        "Uses cache (yfinance RTH 5m + daily)."
    )
    ap.add_argument(
        "--symbols",
        nargs="*",
        help="Optional symbol list override (default: UNIVERSE_MODE universe, WL 323848747).",
    )
    ap.add_argument(
        "--now",
        type=int,
        default=None,
        help="Unix now override for dry recompute (last closed 5m derived from this).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and print counts/signals; no Discord post; no signal_state mutation.",
    )
    ap.add_argument(
        "--print-universes",
        action="store_true",
        help="Print Focus/Sydney/union/day_monitor counts and exit (no scan).",
    )
    args = ap.parse_args()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    uni = build_scan_universes(now=args.now)
    c = uni["counts"]
    print(
        f"Universes: mode={c.get('mode')} pivot30={c['pivot30']} "
        f"Focus={c['focus']} Sydney_top50={c['sydney_top50']} "
        f"union={c['union']} day_monitor={c['day_monitor']} fetch={c['fetch']} "
        f"rome_date={rome_today(args.now)} "
        f"EMA_FAST={EMA_FAST} DAILY_EMA={DAILY_EMA_PERIODS} SMA30_NEAR_PCT={SMA30_NEAR_PCT}"
    )
    if args.print_universes:
        print(json.dumps({
            "counts": c,
            "day_monitor": uni["day_monitor"],
            "sydney_top50": uni["sydney_top50"][:10],
            "sydney_top50_tail": uni["sydney_top50"][-5:],
            "focus_sample": uni["focus"][:5],
            "pivot30_sample": uni["pivot30"][:10],
        }, indent=2))
        return
    symbols = args.symbols if args.symbols else None
    summary = scan_all(
        symbols,
        now=args.now,
        dry_run=args.dry_run,
        universes=uni,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
