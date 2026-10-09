#!/usr/bin/env python3
"""Parallel yfinance 5m/10d (+ daily 1d/2y) refresh → cache, then optional scan.

RTH routine data path (NO TradingView browser confirmation):
  1) Parallel batch download (yf.download threads=True; ThreadPool per-ticker fallback)
  2) Write cache/*.json with source=yfinance:5m:10d, prepost=False
  2b) Also write cache/daily/*.json with source=yfinance:1d:2y (for DAILY EMA +
      RS Rating; includes ^GSPC for Fred6724 RS, not added to scan universe)
  3) Optional --scan via scanner.scan_all on scanner.build_scan_universes()
     (UNIVERSE_MODE='wl323848747' → ONLY TV WL 323848747, 30m pivot only)
     (Discord only on NEW; Remy webhook only)

Recommended cron (Europe/Rome, Mon–Fri). Parent owns install — do not resume paused jobs here:

  # Near US open (~09:15 ET winter / ~09:15 EDT summer — verify DST)
  15 15 * * 1-5  cd /workspace/tv-scanner && .venv/bin/python refresh_yfinance.py --scan >> /tmp/tv-scanner.log 2>&1

  # Optional: every 5m during US RTH (14:30–21:00 Rome; adjust for DST)
  # */5 14-20 * * 1-5  cd /workspace/tv-scanner && .venv/bin/python refresh_yfinance.py --scan >> /tmp/tv-scanner.log 2>&1

Fast path (preferred routine): one process, fetch+scan+Discord NEW:

  .venv/bin/python refresh_yfinance.py --scan

Scan alone (cache already warm) finishes in seconds.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BASE = Path(__import__("os").environ.get("TV_SCANNER_HOME") or Path(__file__).resolve().parent)  # locale o box
CACHE = BASE / "cache"
DAILY_CACHE = CACHE / "daily"
RESULTS = BASE / "results"
SYMBOLS_PATH = BASE / "symbols.txt"
SOURCE_LABEL = "yfinance:5m:10d"
DAILY_SOURCE_LABEL = "yfinance:1d:2y"
DAILY_PERIOD_DEFAULT = "2y"
REUSE_DAILY_SAME_DAY = True
SPX_YAHOO = "^GSPC"  # RS Rating reference; cached daily, not scanned
DAILY_INTERVAL = "1d"


def load_symbols(path: Path = SYMBOLS_PATH) -> list[str]:
    out: list[str] = []
    for line in path.read_text().splitlines():
        s = line.split("#", 1)[0].strip()  # skip comment lines / trailing comments
        if not s:
            continue
        out.append(s)
    return list(dict.fromkeys(out))


def bars_from_df(sub) -> list[dict]:
    import pandas as pd

    if sub is None or getattr(sub, "empty", True):
        raise ValueError("no rows returned")
    if isinstance(sub.columns, pd.MultiIndex):
        sub = sub.copy()
        # yfinance single-ticker: (Price, Ticker); batched slice: (Ticker, Price) or flat.
        lvl0 = [str(c).lower() for c in sub.columns.get_level_values(0)]
        if any(x in lvl0 for x in ("open", "close", "high", "low", "adj close", "adj_close")):
            sub.columns = [c[0] for c in sub.columns]
        else:
            sub.columns = [c[-1] for c in sub.columns]
    cols = {str(c).lower().replace(" ", "_"): c for c in sub.columns}
    needed = ["open", "high", "low", "close", "volume"]
    missing = [c for c in needed if c not in cols]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    rows: dict[int, dict] = {}
    for idx, row in sub.iterrows():
        vals = [row[cols[c]] for c in needed]
        if any(pd.isna(v) for v in vals[:4]):
            continue
        ts = int(pd.Timestamp(idx).timestamp())
        o, h, l, c, v = vals
        rows[ts] = {
            "t": ts,
            "o": float(o),
            "h": float(h),
            "l": float(l),
            "c": float(c),
            "v": 0.0 if pd.isna(v) else float(v),
        }
    bars = [rows[k] for k in sorted(rows)]
    if not bars:
        raise ValueError("no valid OHLC rows")
    return bars


def write_cache(symbol: str, bars: list[dict], fetched_at: str) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol": symbol,
        "bars": bars,
        "count": len(bars),
        "source": SOURCE_LABEL,
        "downloaded_at_utc": fetched_at,
    }
    (CACHE / f"{symbol.replace(':', '_')}.json").write_text(
        json.dumps(payload, separators=(",", ":")) + "\n"
    )


def write_daily_cache(symbol: str, bars: list[dict], fetched_at: str) -> None:
    DAILY_CACHE.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol": symbol,
        "bars": bars,
        "count": len(bars),
        "source": DAILY_SOURCE_LABEL,
        "downloaded_at_utc": fetched_at,
    }
    (DAILY_CACHE / f"{symbol.replace(':', '_')}.json").write_text(
        json.dumps(payload, separators=(",", ":")) + "\n"
    )


def fetch_one_ticker(ticker: str, period: str, interval: str, prepost: bool = False) -> Any:
    import yfinance as yf

    return yf.download(
        tickers=ticker,
        period=period,
        interval=interval,
        auto_adjust=False,
        prepost=prepost,
        threads=False,
        progress=False,
        timeout=30,
    )


def batch_download(tickers: list[str], period: str, interval: str, prepost: bool = False):
    import yfinance as yf
    import pandas as pd

    return yf.download(
        tickers=tickers,
        period=period,
        interval=interval,
        group_by="ticker",
        auto_adjust=False,
        prepost=prepost,
        threads=True,  # parallel inside yfinance
        progress=False,
        timeout=60,
        multi_level_index=True,
    )


def slice_for(df, ticker: str):
    import pandas as pd

    if df is None:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        lvl0 = set(df.columns.get_level_values(0))
        lvl1 = set(df.columns.get_level_values(1))
        if ticker in lvl0:
            return df[ticker]
        if ticker in lvl1:
            return df.xs(ticker, axis=1, level=1)
        return None
    return df


def refresh(
    symbols: Optional[list[str]] = None,
    period: str = "10d",
    interval: str = "5m",
    workers: int = 16,
    write_disk: bool = True,
) -> dict:
    """Parallel yfinance fetch. Returns report with in-memory bars_by_symbol.

    write_disk=True (default) still persists cache/*.json for other tools.
    Scan path should reuse report["bars_by_symbol"] to avoid re-reading disk.
    """
    symbols = symbols or load_symbols()
    tickers = [s.split(":", 1)[-1] for s in symbols]
    fetched_at = datetime.now(timezone.utc).isoformat()
    bars_by_symbol: dict[str, list] = {}
    report: dict[str, Any] = {
        "source": f"{SOURCE_LABEL} batch",
        "interval": interval,
        "period": period,
        "prepost": False,
        "parallel": {"yf_download_threads": True, "threadpool_fallback_workers": workers},
        "requested": len(symbols),
        "fetched_ok": 0,
        "errors": [],
        "bars": {},
        "bars_by_symbol": bars_by_symbol,
        "fetched_at_utc": fetched_at,
    }
    t0 = time.perf_counter()
    df = None
    try:
        df = batch_download(tickers, period, interval)
    except Exception as e:
        report["errors"].append({"stage": "batch_download", "error": f"{type(e).__name__}: {e}"})

    pending: list[tuple[str, str]] = []
    for sym, t in zip(symbols, tickers):
        try:
            sub = slice_for(df, t) if df is not None else None
            bars = bars_from_df(sub)
            bars_by_symbol[sym] = bars
            if write_disk:
                write_cache(sym, bars, fetched_at)
            report["fetched_ok"] += 1
            report["bars"][sym] = len(bars)
        except Exception:
            pending.append((sym, t))

    # Parallel per-ticker fallback for misses / batch failures
    if pending:
        def _one(pair: tuple[str, str]):
            sym, t = pair
            sub = fetch_one_ticker(t, period, interval)
            bars = bars_from_df(sub)
            return sym, bars

        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futs = {ex.submit(_one, p): p for p in pending}
            for fut in as_completed(futs):
                sym, t = futs[fut]
                try:
                    s, bars = fut.result()
                    bars_by_symbol[s] = bars
                    if write_disk:
                        write_cache(s, bars, fetched_at)
                    report["fetched_ok"] += 1
                    report["bars"][s] = len(bars)
                except Exception as e:
                    report["errors"].append({"symbol": sym, "error": f"{type(e).__name__}: {e}"})

    report["error_count"] = len(report["errors"])
    report["elapsed_sec"] = round(time.perf_counter() - t0, 3)
    if write_disk:
        RESULTS.mkdir(parents=True, exist_ok=True)
        # Drop in-memory bars from disk report (keep counts only)
        disk_report = {k: v for k, v in report.items() if k != "bars_by_symbol"}
        (RESULTS / "fetch_report.json").write_text(json.dumps(disk_report, indent=2) + "\n")
    return report



def refresh_spx_daily(
    period: str = DAILY_PERIOD_DEFAULT,
    write_disk: bool = True,
) -> dict:
    """Fetch Yahoo ^GSPC daily into cache/daily for RS Rating (not scan universe)."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    report: dict[str, Any] = {
        "source": f"{DAILY_SOURCE_LABEL} spx",
        "symbol": SPX_YAHOO,
        "period": period,
        "fetched_ok": 0,
        "errors": [],
        "bars": 0,
        "fetched_at_utc": fetched_at,
    }
    t0 = time.perf_counter()
    try:
        sub = fetch_one_ticker(SPX_YAHOO, period, DAILY_INTERVAL, prepost=False)
        bars = bars_from_df(sub)
        if write_disk:
            write_daily_cache(SPX_YAHOO, bars, fetched_at)
        report["fetched_ok"] = 1
        report["bars"] = len(bars)
        report["bars_list"] = bars
    except Exception as e:
        report["errors"].append({"symbol": SPX_YAHOO, "error": f"{type(e).__name__}: {e}"})
    report["error_count"] = len(report["errors"])
    report["elapsed_sec"] = round(time.perf_counter() - t0, 3)
    return report


def refresh_daily(
    symbols: Optional[list[str]] = None,
    period: str = DAILY_PERIOD_DEFAULT,
    workers: int = 16,
    write_disk: bool = True,
) -> dict:
    """Parallel yfinance daily (1d) fetch → cache/daily/*.json for EMA9/21/50 gate."""
    symbols = symbols or load_symbols()
    tickers = [s.split(":", 1)[-1] for s in symbols]
    fetched_at = datetime.now(timezone.utc).isoformat()
    bars_by_symbol: dict[str, list] = {}
    report: dict[str, Any] = {
        "source": f"{DAILY_SOURCE_LABEL} batch",
        "interval": DAILY_INTERVAL,
        "period": period,
        "prepost": False,
        "parallel": {"yf_download_threads": True, "threadpool_fallback_workers": workers},
        "requested": len(symbols),
        "fetched_ok": 0,
        "errors": [],
        "bars": {},
        "bars_by_symbol": bars_by_symbol,
        "fetched_at_utc": fetched_at,
    }
    t0 = time.perf_counter()
    # Ronin 09/10: il 30M PIVOT usa solo le daily chiuse (fino a ieri). Se la cache del titolo è già stata
    # scaricata oggi (New York) la riuso: una sola discesa al giorno invece che a ogni scansione.
    if REUSE_DAILY_SAME_DAY:
        from zoneinfo import ZoneInfo
        _et = ZoneInfo("America/New_York")
        today_et = datetime.now(_et).date()
        keep_sym, keep_tk = [], []
        for sym, t in zip(symbols, tickers):
            try:
                pth = DAILY_CACHE / f"{sym.replace(':', '_')}.json"
                j = json.loads(pth.read_text())
                got = datetime.fromisoformat(j["downloaded_at_utc"]).astimezone(_et).date()
                if got == today_et and len(j.get("bars") or []) >= 260:
                    bars_by_symbol[sym] = j["bars"]
                    report["fetched_ok"] += 1
                    report["bars"][sym] = len(j["bars"])
                    continue
            except Exception:
                pass
            keep_sym.append(sym)
            keep_tk.append(t)
        report["from_cache_today"] = len(symbols) - len(keep_sym)
        symbols, tickers = keep_sym, keep_tk
    df = None
    try:
        df = batch_download(tickers, period, DAILY_INTERVAL, prepost=False) if tickers else None
    except Exception as e:
        report["errors"].append({"stage": "batch_download", "error": f"{type(e).__name__}: {e}"})

    pending: list[tuple[str, str]] = []
    for sym, t in zip(symbols, tickers):
        try:
            sub = slice_for(df, t) if df is not None else None
            bars = bars_from_df(sub)
            bars_by_symbol[sym] = bars
            if write_disk:
                write_daily_cache(sym, bars, fetched_at)
            report["fetched_ok"] += 1
            report["bars"][sym] = len(bars)
        except Exception:
            pending.append((sym, t))

    if pending:
        def _one(pair: tuple[str, str]):
            sym, t = pair
            sub = fetch_one_ticker(t, period, DAILY_INTERVAL, prepost=False)
            bars = bars_from_df(sub)
            return sym, bars

        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futs = {ex.submit(_one, p): p for p in pending}
            for fut in as_completed(futs):
                sym, t = futs[fut]
                try:
                    s, bars = fut.result()
                    bars_by_symbol[s] = bars
                    if write_disk:
                        write_daily_cache(s, bars, fetched_at)
                    report["fetched_ok"] += 1
                    report["bars"][s] = len(bars)
                except Exception as e:
                    report["errors"].append({"symbol": sym, "error": f"{type(e).__name__}: {e}"})

    report["error_count"] = len(report["errors"])
    report["elapsed_sec"] = round(time.perf_counter() - t0, 3)
    if write_disk:
        RESULTS.mkdir(parents=True, exist_ok=True)
        disk_report = {k: v for k, v in report.items() if k != "bars_by_symbol"}
        (RESULTS / "fetch_report_daily.json").write_text(json.dumps(disk_report, indent=2) + "\n")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Parallel yfinance 5m/10d + daily 1d refresh (prepost=False) → cache. "
        "RTH routine: NO TradingView browser. Optional --scan: 30M PIVOT only on "
        "scanner UNIVERSE_MODE (TV WL 323848747)."
    )
    ap.add_argument("--period", default="10d", help="yfinance 5m period (default 10d)")
    ap.add_argument("--interval", default="5m", help="yfinance 5m interval (default 5m)")
    ap.add_argument(
        "--daily-period",
        default=DAILY_PERIOD_DEFAULT,
        help=f"yfinance daily period (default {DAILY_PERIOD_DEFAULT})",
    )
    ap.add_argument("--workers", type=int, default=16, help="ThreadPool workers for per-ticker fallback")
    ap.add_argument("--scan", action="store_true", help="Run scanner.scan_all after refresh (may Discord NEW)")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="With --scan: no Discord / no signal_state mutation; print universe counts.",
    )
    ap.add_argument(
        "--symbols-file",
        type=Path,
        default=None,
        help="Optional override symbols file (default: scanner.build_scan_universes()['fetch']).",
    )
    args = ap.parse_args()

    sys.path.insert(0, str(BASE))
    from scanner import build_scan_universes

    uni = build_scan_universes()
    if args.symbols_file is not None:
        symbols = load_symbols(args.symbols_file)
        # Still pass universes so per-symbol gates follow UNIVERSE_MODE
    else:
        symbols = list(uni["fetch"])

    print(json.dumps({"universes": uni["counts"], "day_monitor": uni["day_monitor"]}, indent=2))

    report = refresh(symbols, period=args.period, interval=args.interval, workers=args.workers)
    print(json.dumps({
        "source": report["source"],
        "requested": report["requested"],
        "fetched_ok": report["fetched_ok"],
        "error_count": report["error_count"],
        "elapsed_sec": report["elapsed_sec"],
        "parallel": report["parallel"],
        "errors": report["errors"][:10],
    }, indent=2))

    daily_report = refresh_daily(symbols, period=args.daily_period, workers=args.workers)
    spx_report = refresh_spx_daily(period=args.daily_period)
    print(json.dumps({
        "source": daily_report["source"],
        "requested": daily_report["requested"],
        "fetched_ok": daily_report["fetched_ok"],
        "error_count": daily_report["error_count"],
        "elapsed_sec": daily_report["elapsed_sec"],
        "errors": daily_report["errors"][:10],
    }, indent=2))
    print(json.dumps({
        "spx": spx_report.get("symbol"),
        "fetched_ok": spx_report.get("fetched_ok"),
        "bars": spx_report.get("bars"),
        "error_count": spx_report.get("error_count"),
        "elapsed_sec": spx_report.get("elapsed_sec"),
        "errors": spx_report.get("errors", [])[:5],
    }, indent=2))

    # Refresh RS Rating thresholds at most once per day (public Fred6725 CSV).
    try:
        from rs_rating import load_or_refresh_thresholds
        rs_meta = load_or_refresh_thresholds()
        print(json.dumps({
            "rs_thresholds_date": rs_meta.get("date"),
            "rs_thresholds_source": rs_meta.get("source"),
            "rs_thresholds": rs_meta.get("thresholds"),
        }, indent=2))
    except Exception as e:
        print(json.dumps({"rs_thresholds_error": f"{type(e).__name__}: {e}"}, indent=2))

    if args.scan:
        from scanner import scan_all
        t_scan = time.perf_counter()
        bars_by = report.get("bars_by_symbol") or {}
        daily_by = daily_report.get("bars_by_symbol") or {}
        cached = [s for s in symbols if s in bars_by]
        summary = scan_all(
            cached,
            bars_by_symbol=bars_by,
            daily_bars_by_symbol=daily_by,
            dry_run=args.dry_run,
            universes=uni,
        )
        scan_elapsed = round(time.perf_counter() - t_scan, 3)
        fetch_elapsed = round(report["elapsed_sec"] + daily_report["elapsed_sec"], 3)
        summary["fetch"] = {
            "fetched_ok": report["fetched_ok"],
            "elapsed_sec": report["elapsed_sec"],
            "error_count": report["error_count"],
            "daily_fetched_ok": daily_report["fetched_ok"],
            "daily_elapsed_sec": daily_report["elapsed_sec"],
            "daily_error_count": daily_report["error_count"],
        }
        summary["scan_elapsed_sec"] = scan_elapsed
        summary["total_elapsed_sec"] = round(fetch_elapsed + scan_elapsed, 3)
        (BASE / "last_scan_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps({
            "universes": summary.get("universes"),
            "scan_new": summary.get("new_signals"),
            "discord": summary.get("discord"),
            "symbols_scanned": summary.get("symbols_scanned"),
            "fetch_elapsed_sec": report["elapsed_sec"],
            "daily_fetch_elapsed_sec": daily_report["elapsed_sec"],
            "scan_elapsed_sec": scan_elapsed,
            "total_elapsed_sec": summary["total_elapsed_sec"],
            "latency_sec_after_close": summary.get("latency_sec_after_close"),
            "dry_run": args.dry_run,
        }, indent=2))


if __name__ == "__main__":
    main()
