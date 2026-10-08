#!/usr/bin/env python3
"""Recompute Session VWAP / EMA6 / EMA20 / MACD from cache at known alert bars.

Usage:
  .venv/bin/python verify_indicators.py
  .venv/bin/python verify_indicators.py --symbols NASDAQ:FORM NYSE:ASX

Prints current vs prior closed RTH 5m indicator values and trigger A/B flags.
Does not post Discord. Documents Yahoo≠TV OHLC caveat in output footer.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scanner import (
    ET,
    compute_indicators,
    detect_triggers,
    fetch_5m,
    rebuild_sma30_65m,
    to_et,
)

# Alert times from 2026-09-29 routine / TV verify screenshots (bar OPEN unix).
DEFAULT_ALERTS: list[tuple[str, int, str]] = [
    ("NASDAQ:FORM", 1790689800, "Trigger A candidate (TV close was below TV VWAP)"),
    ("NYSE:ASX", 1790689800, "Trigger B"),
    ("NASDAQ:SMTC", 1790697300, "Trigger B (later bar)"),
    ("NASDAQ:MRVL", 1790691000, "Trigger A candidate"),
]


def _row(sym: str, bar_t: int, note: str) -> dict:
    bars = fetch_5m(sym)
    now = bar_t + 301  # just after bar close
    ind = compute_indicators(bars, now=now)
    sma = rebuild_sma30_65m(bars, now=now)
    if ind is None:
        return {
            "symbol": sym,
            "bar_t": bar_t,
            "et": str(to_et(bar_t)),
            "note": note,
            "error": "indicators_unavailable",
        }
    cross_a = ind.prev_close <= ind.prev_vwap and ind.price > ind.vwap
    cross_b = ind.prev_ema6 <= ind.prev_ema20 and ind.ema6 > ind.ema20
    sigs = detect_triggers(sym, ind, sma) if sma is not None else []
    return {
        "symbol": sym,
        "bar_t": bar_t,
        "et": to_et(bar_t).strftime("%Y-%m-%d %H:%M %Z"),
        "rome": to_et(bar_t).astimezone(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M %Z"),
        "note": note,
        "close": round(ind.price, 6),
        "vwap": round(ind.vwap, 6),
        "prev_close": round(ind.prev_close, 6),
        "prev_vwap": round(ind.prev_vwap, 6),
        "ema6": round(ind.ema6, 6),
        "ema20": round(ind.ema20, 6),
        "prev_ema6": round(ind.prev_ema6, 6),
        "prev_ema20": round(ind.prev_ema20, 6),
        "macd": round(ind.macd, 6),
        "signal": round(ind.signal, 6),
        "hist": round(ind.hist, 6),
        "sma30_65m": None if sma is None else round(sma, 6),
        "cross_vwap_up": cross_a,
        "cross_ema_up": cross_b,
        "macd_line_gt_0": ind.macd > 0,
        "triggers": [s.trigger for s in sigs],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify RTH indicators at alert bars")
    ap.add_argument("--symbols", nargs="*", help="Optional EXCHANGE:TICKER filter")
    ap.add_argument(
        "--json-out",
        type=Path,
        default=Path("/workspace/tv-scanner/results/verify_indicators.json"),
    )
    args = ap.parse_args()
    want = set(args.symbols) if args.symbols else None
    rows = []
    for sym, bar_t, note in DEFAULT_ALERTS:
        if want is not None and sym not in want:
            continue
        rows.append(_row(sym, bar_t, note))

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_rome": datetime.now(tz=ZoneInfo("Europe/Rome")).isoformat(),
        "definition": (
            "RTH-only 5m series; Session VWAP reset 09:30 ET typical (H+L+C)/3; "
            "EMA6/EMA20 + MACD 6/20/9 on RTH closes; last CLOSED 5m only."
        ),
        "yahoo_vs_tv_caveat": (
            "Yahoo Finance RTH OHLC/volume can differ from TradingView Cboe/TV feed "
            "on the same timestamp. Indicators here are correct for Yahoo RTH session "
            "definitions (same formulas as TV Session VWAP / EMA / MACD on RTH bars). "
            "Occasional Trigger A/B mismatch vs a TV Cboe chart is expected when "
            "Yahoo close/VWAP diverge from TV."
        ),
        "rows": rows,
    }
    args.json_out.write_text(json.dumps(payload, indent=2) + "\n")

    for r in rows:
        print("=" * 72)
        print(f"{r['symbol']}  bar_t={r['bar_t']}  {r.get('et')}  ({r.get('rome')})")
        print(f"  note: {r.get('note')}")
        if "error" in r:
            print(f"  ERROR: {r['error']}")
            continue
        print(
            f"  close={r['close']:.4f}  vwap={r['vwap']:.4f}  "
            f"prev_c={r['prev_close']:.4f}  prev_vwap={r['prev_vwap']:.4f}"
        )
        print(
            f"  ema6={r['ema6']:.4f}  ema20={r['ema20']:.4f}  "
            f"prev_ema6={r['prev_ema6']:.4f}  prev_ema20={r['prev_ema20']:.4f}"
        )
        print(
            f"  macd={r['macd']:.4f}  signal={r['signal']:.4f}  hist={r['hist']:.4f}  "
            f"sma30_65m={r['sma30_65m']}"
        )
        print(
            f"  cross_vwap_up={r['cross_vwap_up']}  cross_ema_up={r['cross_ema_up']}  "
            f"macd>0={r['macd_line_gt_0']}  triggers={r['triggers']}"
        )
    print("=" * 72)
    print("Caveat: Yahoo RTH OHLC may ≠ TradingView Cboe; calcs are Yahoo-RTH-correct.")
    print(f"Wrote {args.json_out}")


if __name__ == "__main__":
    main()
